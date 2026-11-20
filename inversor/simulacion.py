"""Dinero ficticio: carteras simuladas que avanzan día a día y simulaciones del pasado (backtest)."""
from __future__ import annotations

import json

import pandas as pd

from .analisis import HISTORICO, RESULTADOS, grafico, metricas_serie, preparar_empresas, ranking_actual
from .cartera import Cartera
from .datos import RAIZ, descargar_precios
from .puntuacion import elegibles, evaluar, ordenar

CARPETA_CARTERAS = RAIZ / "carteras"


# ================================================================ HACIA DELANTE
def _ruta(nombre):
    return CARPETA_CARTERAS / f"{nombre}.json"


def listar_carteras():
    return sorted(p.stem for p in CARPETA_CARTERAS.glob("*.json")) if CARPETA_CARTERAS.exists() else []


def cargar(nombre):
    with open(_ruta(nombre), encoding="utf-8") as f:
        return json.load(f)


def guardar(estado):
    CARPETA_CARTERAS.mkdir(exist_ok=True)
    with open(_ruta(estado["nombre"]), "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


ESTILOS = ("trimestral", "diaria")


def reglas_para(cfg, estilo="trimestral"):
    if estilo not in ESTILOS:
        raise SystemExit(f"Estilo desconocido '{estilo}'. Usa uno de: {', '.join(ESTILOS)}")
    reglas = dict(cfg["cartera"])
    if estilo == "diaria":
        reglas.update(cfg.get("cartera_diaria") or {})
        reglas["estilo"] = "diaria"
    return reglas


def es_diaria(estado):
    return estado["reglas"].get("estilo") == "diaria"


def crear_cartera(nombre, capital, cfg, estilo="trimestral"):
    if _ruta(nombre).exists():
        raise SystemExit(f"Ya existe una cartera llamada '{nombre}'.")
    reglas = reglas_para(cfg, estilo)
    estado = {
        "nombre": nombre, "capital_inicial": float(capital),
        "fecha_inicio": str(pd.Timestamp.today().date()), "ultimo_rebalanceo": None,
        # Las reglas se congelan: cambiar config.yaml después no altera esta cartera
        "reglas": reglas, "fscore_minimo": cfg["fscore_minimo"],
        "referencia": cfg["referencia"], "precio_referencia_inicio": None,
        "cartera": Cartera(capital, reglas).a_dict(), "historial": [],
    }
    guardar(estado)
    return estado


def proxima_revision(estado):
    """Fecha de la próxima revisión, o None si no hay ninguna prevista o la cartera se revisa a diario."""
    if not estado["ultimo_rebalanceo"] or es_diaria(estado):
        return None
    return pd.Timestamp(estado["ultimo_rebalanceo"]) + pd.DateOffset(months=estado["reglas"]["frecuencia_meses"])


def toca_rebalancear(estado, hoy=None):
    if not estado["ultimo_rebalanceo"]:
        return True
    hoy = hoy or pd.Timestamp.today().normalize()
    if es_diaria(estado):
        return hoy > pd.Timestamp(estado["ultimo_rebalanceo"])
    return hoy >= proxima_revision(estado)


def actualizar_cartera(nombre, cfg, ranking=None):
    """Valora la cartera con los precios de hoy y, si toca, aplica las reglas de compra/venta."""
    estado = cargar(nombre)
    cartera = Cartera.desde_dict(estado["cartera"], estado["reglas"])
    hoy = pd.Timestamp.today().normalize()
    rebalanceo = toca_rebalancear(estado, hoy)

    candidatos = []
    if rebalanceo:
        if ranking is None:
            ranking = ranking_actual(cfg)
        candidatos = elegibles(ranking, estado["fscore_minimo"])

    ref = estado["referencia"]
    tickers = set(cartera.posiciones) | set(candidatos[:80]) | {ref}
    cierres, _, _ = descargar_precios(tickers, periodo="10d")
    precios = cierres.ffill().iloc[-1].to_dict()
    cartera.actualizar_precios(precios)

    operaciones = []
    if rebalanceo:
        operaciones = cartera.rebalancear(hoy, candidatos, precios)
        estado["ultimo_rebalanceo"] = str(hoy.date())

    if estado["precio_referencia_inicio"] is None:
        estado["precio_referencia_inicio"] = precios.get(ref)
    valor = cartera.valor(precios)
    valor_ref = estado["capital_inicial"] * precios[ref] / estado["precio_referencia_inicio"]
    registro = {"fecha": str(hoy.date()), "cartera": round(valor, 2), "referencia": round(valor_ref, 2)}
    historial = [h for h in estado["historial"] if h["fecha"] != registro["fecha"]]
    estado["historial"] = historial + [registro]
    estado["cartera"] = cartera.a_dict()
    guardar(estado)
    return estado, operaciones


def describir_cartera(estado, operaciones=()) -> str:
    c = estado["cartera"]
    ultimo = estado["historial"][-1] if estado["historial"] else None
    lineas = [f"💼 Cartera simulada «{estado['nombre']}» (desde {estado['fecha_inicio']}, "
              f"capital inicial {estado['capital_inicial']:,.0f} $)"]
    if ultimo:
        rent = (ultimo["cartera"] / estado["capital_inicial"] - 1) * 100
        rent_ref = (ultimo["referencia"] / estado["capital_inicial"] - 1) * 100
        lineas.append(f"Valor: {ultimo['cartera']:,.2f} $ ({rent:+.2f} %)  |  "
                      f"{estado['referencia']}: {ultimo['referencia']:,.2f} $ ({rent_ref:+.2f} %)")
    lineas.append(f"Efectivo: {c['efectivo']:,.2f} $  |  Posiciones: {len(c['posiciones'])}")
    for t, p in sorted(c["posiciones"].items()):
        r = (p["ultimo_precio"] / p["precio_compra"] - 1) * 100
        lineas.append(f"  {t:<6} {p['acciones']:>8g} acc. compradas {p['fecha_compra']} a {p['precio_compra']:.2f}  →  "
                      f"{p['ultimo_precio']:.2f} ({r:+.1f} %)")
    if operaciones:
        lineas.append("Operaciones de hoy:")
        for op in operaciones:
            extra = f" ({op['resultado_pct']:+.1f} %)" if op.get("resultado_pct") is not None else ""
            lineas.append(f"  {op['tipo']:<8} {op['ticker']:<6} a {op['precio']:.2f}{extra} – {op['motivo']}")
    if es_diaria(estado):
        lineas.append("Revisión: cada día de mercado")
    elif proxima_revision(estado) is not None:
        lineas.append(f"Próxima revisión: {proxima_revision(estado).date()}")
    return "\n".join(lineas)


def grafico_cartera(estado):
    if len(estado["historial"]) < 2:
        return None
    curva = pd.DataFrame(estado["historial"]).set_index("fecha")
    curva.index = pd.to_datetime(curva.index)
    RESULTADOS.mkdir(exist_ok=True)
    ruta = RESULTADOS / f"cartera_{estado['nombre']}.png"
    grafico(curva, ruta, f"Cartera simulada «{estado['nombre']}»", estado["referencia"])
    return ruta


# ================================================================ HACIA ATRÁS
def fecha_inicio_sugerida(tablas: dict, necesita_ano_previo: bool):
    """Primera fecha en la que al menos el 60 % de las empresas tienen datos suficientes."""
    fechas = []
    for tabla in tablas.values():
        pubs = tabla["pub_ebit"].dropna().sort_values()
        posicion = 1 if necesita_ano_previo else 0
        if len(pubs) > posicion:
            fechas.append(pubs.iloc[posicion])
    if not fechas:
        return None
    return pd.Series(fechas).quantile(0.6).normalize()


def ejecutar_backtest(universo, tablas, acciones, cierres, ajustados, splits, ref, inicio, fin, capital, cfg):
    """Núcleo de la simulación del pasado. En cada fecha solo usa lo ya publicado."""
    reglas = cfg["cartera"]
    cierres, ajustados = cierres.ffill(), ajustados.ffill()
    fechas = ajustados.index[(ajustados.index >= inicio) & (ajustados.index <= fin)]
    fechas = fechas[ajustados.loc[fechas, ref].notna()]
    if len(fechas) == 0:
        raise SystemExit("No hay precios en ese rango de fechas.")

    cartera = Cartera(capital, reglas)
    proxima_revision = fechas[0]
    precio_ref_inicial = ajustados.loc[fechas[0], ref]
    curva, cobertura = [], []
    for f in fechas:
        precios = ajustados.loc[f].dropna().to_dict()
        if f >= proxima_revision:
            fila = cierres.loc[f]
            caps = {t: acciones[t].capitalizacion(fila.get(t), splits.get(t), f) for t in tablas if t in fila.index}
            ranking = ordenar(evaluar(universo, tablas, caps, f), cfg["capitalizacion_minima"])
            candidatos = elegibles(ranking, cfg["fscore_minimo"])
            cobertura.append({"fecha": f.date(), "empresas_con_datos": int(ranking["base_ok"].sum()),
                              "empresas_universo": len(universo), "aptas": len(candidatos)})
            cartera.rebalancear(f, candidatos, precios)
            proxima_revision = f + pd.DateOffset(months=reglas["frecuencia_meses"])
        cartera.actualizar_precios(precios)
        curva.append({"fecha": f, "cartera": cartera.valor(precios),
                      "referencia": capital * ajustados.loc[f, ref] / precio_ref_inicial})

    curva = pd.DataFrame(curva).set_index("fecha")
    return curva, pd.DataFrame(cartera.operaciones), pd.DataFrame(cobertura), cartera


AVISO_BACKTEST = """
Cómo leer este resultado:
  • Las cuentas vienen de la SEC con su fecha real de publicación: la simulación
    no "mira al futuro".
  • Sesgo de supervivencia: se usan las empresas que están HOY en el S&P 1500.
    Las que quebraron o salieron del índice no aparecen, y las que entraron
    porque les fue bien sí. Eso infla el resultado: tómalo como el escenario
    optimista, no como lo que habrías ganado seguro.
"""


def backtest(cfg, inicio=None, fin=None, capital=10_000):
    print(AVISO_BACKTEST)
    universo, tablas, acciones = preparar_empresas(cfg)
    sugerida = fecha_inicio_sugerida(tablas, cfg["fscore_minimo"] > 0)
    inicio = pd.Timestamp(inicio) if inicio else sugerida
    fin = pd.Timestamp(fin) if fin else pd.Timestamp.today().normalize()
    if sugerida is not None and inicio < sugerida:
        print(f"Aviso: antes de {sugerida.date()} la mayoría de empresas no tienen cuentas digitales en la SEC; "
              f"las primeras revisiones encontrarán pocas candidatas.")
    print(f"Simulando del {inicio.date()} al {fin.date()} con {capital:,.0f} $ ficticios...")

    ref = cfg["referencia"]
    cierres, ajustados, splits = descargar_precios(list(tablas) + [ref], inicio=inicio - pd.Timedelta(days=10), fin=fin)
    curva, operaciones, cobertura, _ = ejecutar_backtest(
        universo, tablas, acciones, cierres, ajustados, splits, ref, inicio, fin, capital, cfg)
    return guardar_backtest(curva, operaciones, cobertura, inicio, fin, capital, cfg)


def guardar_backtest(curva, operaciones, cobertura, inicio, fin, capital, cfg):
    ref = cfg["referencia"]
    RESULTADOS.mkdir(exist_ok=True)
    sufijo = f"{pd.Timestamp(inicio).date()}_{pd.Timestamp(fin).date()}"
    curva.to_csv(RESULTADOS / f"pasado_curva_{sufijo}.csv")
    operaciones.to_csv(RESULTADOS / f"pasado_operaciones_{sufijo}.csv", index=False)
    ruta_png = RESULTADOS / f"pasado_{sufijo}.png"
    grafico(curva, ruta_png, f"Simulación del pasado {pd.Timestamp(inicio).date()} → {pd.Timestamp(fin).date()}", ref)

    print("\nCobertura de datos en cada revisión:")
    print(cobertura.to_string(index=False))
    m_est, m_ref = metricas_serie(curva["cartera"]), metricas_serie(curva["referencia"])
    print(f"\n{'':<24}{'Estrategia':>12}{ref:>12}")
    for clave in m_est:
        v1, v2 = m_est[clave], m_ref.get(clave)
        print(f"{clave:<24}{'-' if v1 is None else v1:>12}{'-' if v2 is None else v2:>12}")
    ventas = operaciones[operaciones["tipo"] == "VENTA"] if not operaciones.empty else operaciones
    pct_ganadoras = round(float((ventas["resultado_pct"] > 0).mean()) * 100) if not ventas.empty else None
    if pct_ganadoras is not None:
        print(f"\nVentas: {len(ventas)}, con ganancia: {pct_ganadoras} %")
    print(f"\nGráfico: {ruta_png}\nOperaciones: {RESULTADOS / f'pasado_operaciones_{sufijo}.csv'}")

    # Resumen para el panel del móvil (una muestra semanal de la curva basta)
    semanal = curva.resample("W-FRI").last().dropna()
    resumen = {
        "generado": str(pd.Timestamp.today().date()),
        "inicio": str(curva.index[0].date()), "fin": str(curva.index[-1].date()),
        "capital": capital, "referencia": ref, "fscore_minimo": cfg["fscore_minimo"],
        "final": {"estrategia": round(float(curva["cartera"].iloc[-1]), 2),
                  "referencia": round(float(curva["referencia"].iloc[-1]), 2)},
        "metricas": {"estrategia": m_est, "referencia": m_ref},
        "ventas": len(ventas), "pct_ganadoras": pct_ganadoras,
        "empresas_con_datos_media": int(cobertura["empresas_con_datos"].mean()) if not cobertura.empty else 0,
        "curva": [[str(i.date()), round(float(r.cartera), 2), round(float(r.referencia), 2)] for i, r in semanal.iterrows()],
    }
    HISTORICO.mkdir(exist_ok=True)
    with open(HISTORICO / "ultimo_pasado.json", "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False)
    return resumen
