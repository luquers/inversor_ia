"""Cartera con dinero ficticio que sigue las reglas de Greenblatt."""
from __future__ import annotations

import math

import pandas as pd


def _precio_valido(p):
    return p is not None and not pd.isna(p) and p > 0


class Cartera:
    def __init__(self, efectivo, reglas, posiciones=None, operaciones=None):
        self.efectivo = float(efectivo)
        self.reglas = reglas
        # ticker -> {acciones, precio_compra, fecha_compra, inicio_periodo, ultimo_precio}
        self.posiciones = posiciones or {}
        self.operaciones = operaciones or []

    # ------------------------------------------------------------ utilidades
    def _comision(self, importe):
        if importe <= 0:
            return 0.0
        return max(importe * self.reglas["comision_pct"], self.reglas["comision_minima"])

    def actualizar_precios(self, precios: dict):
        for t, pos in self.posiciones.items():
            if _precio_valido(precios.get(t)):
                pos["ultimo_precio"] = float(precios[t])

    def _precio(self, t, precios):
        p = precios.get(t)
        return float(p) if _precio_valido(p) else self.posiciones[t].get("ultimo_precio", self.posiciones[t]["precio_compra"])

    def valor(self, precios: dict) -> float:
        return self.efectivo + sum(pos["acciones"] * self._precio(t, precios) for t, pos in self.posiciones.items())

    # ------------------------------------------------------------ operaciones
    def vender(self, ticker, precio, fecha, motivo):
        pos = self.posiciones.pop(ticker)
        importe = pos["acciones"] * precio
        comision = self._comision(importe)
        self.efectivo += importe - comision
        op = {
            "fecha": str(pd.Timestamp(fecha).date()), "tipo": "VENTA", "ticker": ticker,
            "acciones": pos["acciones"], "precio": round(precio, 4), "importe": round(importe, 2),
            "comision": round(comision, 2),
            "resultado_pct": round((precio / pos["precio_compra"] - 1) * 100, 2), "motivo": motivo,
        }
        self.operaciones.append(op)
        return op

    def comprar(self, ticker, importe_maximo, precio, fecha, motivo):
        disponible = min(importe_maximo, self.efectivo)
        acciones = (disponible - self._comision(disponible)) / precio
        if not self.reglas.get("acciones_fraccionadas", False):
            acciones = math.floor(acciones)
        if acciones <= 0:
            return None
        importe = acciones * precio
        comision = self._comision(importe)
        self.efectivo -= importe + comision
        fecha_txt = str(pd.Timestamp(fecha).date())
        self.posiciones[ticker] = {
            "acciones": acciones, "precio_compra": float(precio), "fecha_compra": fecha_txt,
            "inicio_periodo": fecha_txt, "ultimo_precio": float(precio),
        }
        op = {
            "fecha": fecha_txt, "tipo": "COMPRA", "ticker": ticker, "acciones": acciones,
            "precio": round(precio, 4), "importe": round(importe, 2), "comision": round(comision, 2),
            "resultado_pct": None, "motivo": motivo,
        }
        self.operaciones.append(op)
        return op

    # ------------------------------------------------------------ la regla
    def rebalancear(self, fecha, candidatos: list[str], precios: dict) -> list[dict]:
        if self.reglas.get("estilo") in ("diaria", "semanal"):
            return self._rebalancear_por_ranking(fecha, candidatos, precios)
        return self._rebalancear_periodico(fecha, candidatos, precios)

    def _rebalancear_por_ranking(self, fecha, candidatos: list[str], precios: dict) -> list[dict]:
        """Estilos diaria y semanal (solo cambia cada cuánto se llama).
        1. Vende lo que ha caído fuera de las `vender_fuera_del_top` mejores (o ya no pasa el F-Score).
        2. Compra las que están entre las `num_posiciones` mejores y no tiene, si hay hueco.
        """
        r = self.reglas
        fecha = pd.Timestamp(fecha)
        self.actualizar_precios(precios)
        if not candidatos:
            # Sin ranking (fallo de datos) no se toca nada: vender todo sería un error
            return []
        nuevas_ops = []
        top_n = r["num_posiciones"]
        limite = max(r.get("vender_fuera_del_top", 50), top_n)
        puesto = {t: i for i, t in enumerate(candidatos, 1)}

        for t in list(self.posiciones):
            p = puesto.get(t)
            if p is None:
                motivo = "Ya no pasa el filtro (F-Score o datos incompletos)"
            elif p > limite:
                motivo = f"Cae al puesto {p} del ranking (fuera de las {limite} mejores)"
            else:
                continue
            nuevas_ops.append(self.vender(t, self._precio(t, precios), fecha, motivo))

        por_comprar = min(top_n - len(self.posiciones), r["compras_por_tanda"])
        if por_comprar > 0:
            objetivo = self.valor(precios) / top_n
            for p, t in enumerate(candidatos[:top_n], 1):
                if por_comprar == 0 or self.efectivo <= 0:
                    break
                if t in self.posiciones or not _precio_valido(precios.get(t)):
                    continue
                op = self.comprar(t, objetivo, float(precios[t]), fecha, f"Entra en el puesto {p} del ranking")
                if op:
                    nuevas_ops.append(op)
                    por_comprar -= 1
        return nuevas_ops

    def _rebalancear_periodico(self, fecha, candidatos: list[str], precios: dict) -> list[dict]:
        """
        1. Vende lo que ya ha cumplido su periodo (salvo que siga entre las mejores y la
           regla de renovar esté activa; en ese caso se queda otro periodo).
        2. Rellena huecos con las mejores del ranking, como mucho `compras_por_tanda`.
        """
        r = self.reglas
        fecha = pd.Timestamp(fecha)
        self.actualizar_precios(precios)
        nuevas_ops = []
        mejores = set(candidatos[: r["num_posiciones"]])

        for t in list(self.posiciones):
            pos = self.posiciones[t]
            dias = (fecha - pd.Timestamp(pos["inicio_periodo"])).days
            if dias < r["mantener_dias"]:
                continue
            if r.get("renovar_si_sigue_en_lista") and t in mejores:
                pos["inicio_periodo"] = str(fecha.date())
                op = {"fecha": str(fecha.date()), "tipo": "MANTENER", "ticker": t, "acciones": pos["acciones"],
                      "precio": round(self._precio(t, precios), 4), "importe": None, "comision": 0.0,
                      "resultado_pct": round((self._precio(t, precios) / pos["precio_compra"] - 1) * 100, 2),
                      "motivo": "Cumple un año pero sigue entre las mejores"}
                self.operaciones.append(op)
                nuevas_ops.append(op)
            else:
                nuevas_ops.append(self.vender(t, self._precio(t, precios), fecha, "Cumplido el periodo de mantenimiento"))

        huecos = r["num_posiciones"] - len(self.posiciones)
        por_comprar = min(huecos, r["compras_por_tanda"])
        if por_comprar > 0:
            objetivo = self.valor(precios) / r["num_posiciones"]
            for puesto, t in enumerate(candidatos, 1):
                if por_comprar == 0 or self.efectivo <= 0:
                    break
                if t in self.posiciones or not _precio_valido(precios.get(t)):
                    continue
                op = self.comprar(t, objetivo, float(precios[t]), fecha, f"Puesto {puesto} del ranking")
                if op:
                    nuevas_ops.append(op)
                    por_comprar -= 1
        return nuevas_ops

    # ------------------------------------------------------------ guardar/cargar
    def a_dict(self):
        return {"efectivo": self.efectivo, "posiciones": self.posiciones, "operaciones": self.operaciones}

    @classmethod
    def desde_dict(cls, d, reglas):
        return cls(d["efectivo"], reglas, d.get("posiciones"), d.get("operaciones"))
