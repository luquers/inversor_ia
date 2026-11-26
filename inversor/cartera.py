"""Cartera con dinero ficticio que sigue las reglas de Greenblatt."""
from __future__ import annotations

import math

import pandas as pd


def _precio_valido(p):
    return p is not None and not pd.isna(p) and p > 0


class Cartera:
    def __init__(self, efectivo, reglas, posiciones=None, operaciones=None, vetadas=None):
        self.efectivo = float(efectivo)
        self.reglas = reglas
        # ticker -> {acciones, precio_compra, fecha_compra, inicio_periodo, ultimo_precio, maximo}
        self.posiciones = posiciones or {}
        self.operaciones = operaciones or []
        # ticker -> fecha hasta la que no se vuelve a comprar (tras vender por protección)
        self.vetadas = vetadas or {}

    # ------------------------------------------------------------ utilidades
    def _comision(self, importe):
        if importe <= 0:
            return 0.0
        return max(importe * self.reglas["comision_pct"], self.reglas["comision_minima"])

    def aplicar_splits(self, splits: dict) -> list[str]:
        """Si una empresa que se tiene hace un split (p. ej. 8 por 1), Yahoo reescribe todo su historial
        de precios dividido entre 8: aquí se multiplican las acciones y se dividen los precios guardados.
        Solo cuentan los splits posteriores a la compra y cada uno se aplica una vez."""
        notas = []
        for t, pos in self.posiciones.items():
            serie = splits.get(t)
            if serie is None or not len(serie):
                continue
            hechos = set(pos.get("splits", []))
            for fecha, ratio in serie.items():
                dia = str(pd.Timestamp(fecha).date())
                if dia <= pos["fecha_compra"] or dia in hechos or not ratio or ratio == 1:
                    continue
                pos["acciones"] = pos["acciones"] * ratio
                for campo in ("precio_compra", "ultimo_precio", "maximo"):
                    if campo in pos:
                        pos[campo] = pos[campo] / ratio
                hechos.add(dia)
                notas.append(f"{t}: split {ratio:g} por 1 el {dia}")
            if hechos:
                pos["splits"] = sorted(hechos)
        return notas

    def actualizar_precios(self, precios: dict):
        for t, pos in self.posiciones.items():
            if _precio_valido(precios.get(t)):
                pos["ultimo_precio"] = float(precios[t])
                pos["maximo"] = max(pos.get("maximo", pos["precio_compra"]), pos["ultimo_precio"])

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
            "inicio_periodo": fecha_txt, "ultimo_precio": float(precio), "maximo": float(precio),
        }
        op = {
            "fecha": fecha_txt, "tipo": "COMPRA", "ticker": ticker, "acciones": acciones,
            "precio": round(precio, 4), "importe": round(importe, 2), "comision": round(comision, 2),
            "resultado_pct": None, "motivo": motivo,
        }
        self.operaciones.append(op)
        return op

    # ------------------------------------------------------------ la regla
    def rebalancear(self, fecha, candidatos: list[str], precios: dict, ctx: dict | None = None) -> list[dict]:
        estilo = self.reglas.get("estilo")
        if estilo == "reactiva":
            return self._rebalancear_reactivo(fecha, candidatos, precios, ctx or {})
        if estilo in ("diaria", "semanal"):
            return self._rebalancear_por_ranking(fecha, candidatos, precios)
        return self._rebalancear_periodico(fecha, candidatos, precios)

    # ------------------------------------------------------------ cartera reactiva
    def vigilar(self, fecha, precios: dict, ctx: dict) -> list[dict]:
        """Protecciones que se comprueban varias veces al día (cartera reactiva):
        - stop móvil: vende si cae `stop_movil_pct` % desde su máximo desde la compra
        - noticia grave reciente que el mercado ya castiga (cae `caida_noticia_pct` % en 5 sesiones)
        """
        r = self.reglas
        fecha = pd.Timestamp(fecha)
        self.actualizar_precios(precios)
        nuevas_ops = []
        veto_hasta = str((fecha + pd.Timedelta(days=r.get("vetar_dias", 30))).date())
        for t in list(self.posiciones):
            pos = self.posiciones[t]
            precio = self._precio(t, precios)
            maximo = pos.get("maximo", pos["precio_compra"])
            caida = (1 - precio / maximo) * 100 if maximo else 0
            motivo = None
            if caida >= r.get("stop_movil_pct", 15):
                motivo = f"Stop móvil: cae un {caida:.0f} % desde su máximo de {maximo:.2f}"
            elif r.get("noticias", True):
                grave = ((ctx.get("noticias") or {}).get(t) or {}).get("grave_reciente")
                cambio_5d = (ctx.get("cambio_5d") or {}).get(t)
                if grave and cambio_5d is not None and cambio_5d <= -r.get("caida_noticia_pct", 5):
                    motivo = f"Noticia grave y caída del {abs(cambio_5d):.0f} % en 5 sesiones: «{grave['titulo'][:120]}»"
            if motivo:
                nuevas_ops.append(self.vender(t, precio, fecha, motivo))
                self.vetadas[t] = veto_hasta
        return nuevas_ops

    def _motivo_para_no_comprar(self, t, fecha, ctx) -> str | None:
        r = self.reglas
        if self.vetadas.get(t) and str(pd.Timestamp(fecha).date()) <= self.vetadas[t]:
            return "vendida hace poco por protección"
        cambio = (ctx.get("cambio_dia") or {}).get(t)
        if cambio is not None and cambio <= -r.get("caida_brusca_pct", 7):
            return f"cae un {abs(cambio):.0f} % hoy"
        if r.get("noticias", True):
            cuenta = (((ctx.get("noticias") or {}).get(t) or {}).get("cuenta") or {})
            if cuenta.get("grave", 0) > 0:
                return "tiene noticias graves recientes"
            if cuenta.get("negativa", 0) >= 2 and cuenta.get("negativa", 0) > cuenta.get("positiva", 0):
                return "acumula noticias negativas"
        return None

    def _rebalancear_reactivo(self, fecha, candidatos: list[str], precios: dict, ctx: dict) -> list[dict]:
        """Protecciones + reglas del ranking + filtros antes de comprar (noticias, caídas, mercado)."""
        nuevas_ops = self.vigilar(fecha, precios, ctx)
        prudente = self.reglas.get("filtro_mercado", True) and not (ctx.get("indice") or {}).get("sobre_media", True)
        nuevas_ops += self._rebalancear_por_ranking(
            fecha, candidatos, precios, sin_compras=prudente,
            filtro_compra=lambda t: self._motivo_para_no_comprar(t, fecha, ctx) is None)
        # Los vetos caducados se olvidan
        hoy = str(pd.Timestamp(fecha).date())
        self.vetadas = {t: h for t, h in self.vetadas.items() if h >= hoy}
        return nuevas_ops

    def _rebalancear_por_ranking(self, fecha, candidatos: list[str], precios: dict,
                                 sin_compras=False, filtro_compra=None) -> list[dict]:
        """Estilos diaria, semanal y reactiva (solo cambia cada cuánto se llama y los filtros).
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

        por_comprar = 0 if sin_compras else min(top_n - len(self.posiciones), r["compras_por_tanda"])
        if por_comprar > 0:
            objetivo = self.valor(precios) / top_n
            for p, t in enumerate(candidatos[:top_n], 1):
                if por_comprar == 0 or self.efectivo <= 0:
                    break
                if t in self.posiciones or not _precio_valido(precios.get(t)):
                    continue
                if filtro_compra is not None and not filtro_compra(t):
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
        d = {"efectivo": self.efectivo, "posiciones": self.posiciones, "operaciones": self.operaciones}
        if self.vetadas:
            d["vetadas"] = self.vetadas
        return d

    @classmethod
    def desde_dict(cls, d, reglas):
        return cls(d["efectivo"], reglas, d.get("posiciones"), d.get("operaciones"), d.get("vetadas"))
