"""Fórmula Mágica de Greenblatt y F-Score de Piotroski (con datos de la SEC)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .sec import vista

# Si las últimas cuentas anuales tienen más de ~18 meses, algo falla (la empresa ha dejado
# de publicar o ha cambiado cómo etiqueta sus cifras): mejor no puntuarla con datos viejos.
ANTIGUEDAD_MAXIMA_DIAS = 550


def _div(a, b):
    try:
        if b is None or pd.isna(a) or pd.isna(b) or b == 0:
            return np.nan
        return a / b
    except Exception:
        return np.nan


def f_score(actual: pd.Series, anterior: pd.Series | None):
    """Las 9 señales de Piotroski. Devuelve (puntos, nº de señales que se pudieron evaluar, detalle)."""
    if anterior is None:
        return np.nan, 0, {}
    c, p = actual, anterior
    roa_c, roa_p = _div(c.beneficio_neto, c.activos_totales), _div(p.beneficio_neto, p.activos_totales)
    apal_c, apal_p = _div(c.deuda_lp, c.activos_totales), _div(p.deuda_lp, p.activos_totales)
    liq_c, liq_p = _div(c.activo_corriente, c.pasivo_corriente), _div(p.activo_corriente, p.pasivo_corriente)
    marg_c, marg_p = _div(c.beneficio_bruto, c.ingresos), _div(p.beneficio_bruto, p.ingresos)
    rot_c, rot_p = _div(c.ingresos, c.activos_totales), _div(p.ingresos, p.activos_totales)

    def comparar(a, b, mayor=True):
        if pd.isna(a) or pd.isna(b):
            return None
        return bool(a > b) if mayor else bool(a < b)

    ratio_acciones = _div(c.acciones, p.acciones)
    if pd.isna(ratio_acciones):
        sin_emision = None
    elif ratio_acciones >= 1.5:   # salto enorme: casi seguro un split, no una emisión
        sin_emision = True
    else:
        sin_emision = bool(ratio_acciones <= 1.0)

    if pd.isna(apal_c) or pd.isna(apal_p):
        menos_deuda = None
    else:
        menos_deuda = bool(apal_c < apal_p or (apal_c == 0 and apal_p == 0))

    detalle = {
        "rentabilidad_positiva": comparar(roa_c, 0),
        "genera_caja": comparar(c.flujo_operativo, 0),
        "rentabilidad_mejora": comparar(roa_c, roa_p),
        "beneficio_respaldado_por_caja": comparar(_div(c.flujo_operativo, c.activos_totales), roa_c),
        "menos_deuda": menos_deuda,
        "liquidez_mejora": comparar(liq_c, liq_p),
        "sin_emitir_acciones": sin_emision,
        "margen_mejora": comparar(marg_c, marg_p),
        "rotacion_mejora": comparar(rot_c, rot_p),
    }
    evaluables = sum(v is not None for v in detalle.values())
    puntos = sum(bool(v) for v in detalle.values())
    return puntos, evaluables, detalle


def metricas_empresa(tabla, capitalizacion, fecha_corte=None):
    """Métricas de una empresa con lo que se sabía en `fecha_corte` (o con todo, si es None)."""
    if tabla is None or tabla.empty or capitalizacion is None or pd.isna(capitalizacion) or capitalizacion <= 0:
        return None
    t = vista(tabla, fecha_corte)
    con_ebit = t[t["ebit"].notna()]
    if con_ebit.empty:
        return None
    cierre = con_ebit.index[-1]
    actual = con_ebit.iloc[-1]
    previas = t[t.index < cierre]
    anterior = previas.iloc[-1] if not previas.empty else None

    valor_empresa = capitalizacion + actual.deuda_total - actual.caja
    # Greenblatt: circulante operativo (si es negativo, cuenta como cero) + inmovilizado neto.
    # Si no se conoce el circulante, la rentabilidad queda sin calcular en vez de inflarse.
    capital_empleado = max(actual.capital_circulante, 0.0) + actual.inmovilizado_neto \
        if not pd.isna(actual.capital_circulante) else np.nan
    corte = pd.Timestamp(fecha_corte) if fecha_corte is not None else pd.Timestamp.today().normalize()
    cuentas_al_dia = (corte - cierre).days <= ANTIGUEDAD_MAXIMA_DIAS

    puntos, evaluables, _ = f_score(actual, anterior)
    return {
        "capitalizacion": capitalizacion,
        "ebit": actual.ebit,
        "rend_beneficios": _div(actual.ebit, valor_empresa) if valor_empresa > 0 else np.nan,
        "rend_capital": _div(actual.ebit, capital_empleado) if capital_empleado > 0 else np.nan,
        "cuentas_al_dia": cuentas_al_dia,
        "fscore": puntos,
        "fscore_evaluables": evaluables,
        "cierre_ejercicio": cierre.date(),
        "publicado": tabla.loc[cierre, "pub_ebit"].date(),
    }


def evaluar(universo: pd.DataFrame, tablas: dict, capitalizaciones: dict, fecha_corte=None) -> pd.DataFrame:
    filas = []
    for _, emp in universo.iterrows():
        t = emp["ticker"]
        m = metricas_empresa(tablas.get(t), capitalizaciones.get(t), fecha_corte)
        if m:
            filas.append({"ticker": t, "nombre": emp.get("nombre", ""), "sector": emp.get("sector", ""), **m})
    if not filas:
        return pd.DataFrame(columns=["ticker"]).set_index("ticker")
    return pd.DataFrame(filas).set_index("ticker")


def ordenar(df: pd.DataFrame, capitalizacion_minima: float) -> pd.DataFrame:
    """Ranking de la Fórmula Mágica: suma de puestos en rendimiento de beneficios y en rentabilidad."""
    df = df.copy()
    if df.empty:
        df["base_ok"] = pd.Series(dtype=bool)
        df["puesto"] = pd.Series(dtype=float)
        return df
    df["base_ok"] = (
        (df["capitalizacion"] >= capitalizacion_minima)
        & (df["ebit"] > 0)
        & df["rend_beneficios"].notna()
        & df["rend_capital"].notna()
    )
    if "cuentas_al_dia" in df:
        df["base_ok"] &= df["cuentas_al_dia"].fillna(False).astype(bool)
    base = df[df["base_ok"]]
    df["puesto"] = np.nan
    if not base.empty:
        rango = (base["rend_beneficios"].rank(ascending=False, method="min")
                 + base["rend_capital"].rank(ascending=False, method="min"))
        orden = rango.sort_values(kind="stable").index
        df.loc[orden, "puesto"] = range(1, len(orden) + 1)
    return df.sort_values("puesto", na_position="last")


def elegibles(ranking: pd.DataFrame, fscore_minimo: int) -> list[str]:
    """Tickers que pasan la Fórmula Mágica y el filtro de Piotroski, en orden."""
    if ranking.empty:
        return []
    r = ranking[ranking["base_ok"]]
    if fscore_minimo > 0:
        # Hace falta poder comprobar al menos 7 de las 9 señales para fiarse de la nota
        r = r[(r["fscore"] >= fscore_minimo) & (r["fscore_evaluables"] >= 7)]
    return r.index.tolist()
