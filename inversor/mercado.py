"""Lo que pasa en el mercado: precios recientes, tendencia del índice y noticias, en un solo «contexto»."""
from __future__ import annotations

import pandas as pd

from . import noticias as nt
from .datos import descargar_precios


def _variacion(serie: pd.Series, sesiones: int):
    serie = serie.dropna()
    if len(serie) <= sesiones:
        return None
    return float(serie.iloc[-1] / serie.iloc[-1 - sesiones] - 1) * 100


PUESTOS_POR_PUNTO = 5   # cada punto de noticias o geopolítica mueve a la empresa 5 puestos en el ranking
MAXIMO_PUNTOS = 2       # como mucho ±2 por noticias y ±2 por geopolítica (el ranking de la fórmula manda)


def calcular_ajustes(noticias: dict, temas: list, subsectores: dict) -> dict:
    """Cuánto suben o bajan en el ranking las empresas por sus noticias y por la economía y geopolítica.
    {ticker: {puntos, puestos, noticias, macro, frases: [...], temas: [{tema, efecto, porque, grupo}]}}"""
    ajustes = {}
    for t in set(noticias) | set(subsectores):
        r = noticias.get(t) or {}
        cuenta = r.get("cuenta") or {}
        p_noticias = cuenta.get("positiva", 0) - cuenta.get("negativa", 0) - 2 * cuenta.get("grave", 0)
        p_noticias = max(-MAXIMO_PUNTOS, min(MAXIMO_PUNTOS, p_noticias))
        tono = ("positiva",) if p_noticias > 0 else ("negativa", "grave")
        frases = []
        for h in r.get("destacados", []):
            if p_noticias and h.get("significa") and h["tono"] in tono and h["significa"] not in frases:
                frases.append(h["significa"])
        afectan = []
        for tema in temas:
            efecto = nt.afecta(tema, subsectores.get(t, ""))
            if efecto:
                afectan.append({"tema": tema["tema"], "efecto": efecto[0], "grupo": efecto[1], "porque": tema["porque"]})
        p_macro = max(-MAXIMO_PUNTOS, min(MAXIMO_PUNTOS, sum(a["efecto"] for a in afectan)))
        total = p_noticias + p_macro
        if total or afectan or frases:
            ajustes[t] = {"puntos": total, "puestos": total * PUESTOS_POR_PUNTO, "noticias": p_noticias,
                          "macro": p_macro, "frases": frases[:2], "temas": afectan}
    return ajustes


def contexto(tickers, referencia: str, nombres: dict | None = None, con_noticias=True, macro=False,
             subsectores: dict | None = None, historial_temas: dict | None = None) -> dict:
    """Precios del último año de `tickers` + índice, variaciones y (si se pide) noticias.

    - cambio_dia / cambio_5d: variación en % de la última sesión y de las 5 últimas
    - indice.sobre_media: si el índice está por encima de su media de 200 sesiones (tendencia alcista)
    """
    tickers = sorted(set(tickers) | {referencia})
    cierres, _, splits = descargar_precios(tickers, periodo="1y")
    cierres = cierres.dropna(how="all")
    ultimo_dia = cierres.index[-1]
    ref = cierres[referencia].dropna() if referencia in cierres else pd.Series(dtype=float)
    media200 = float(ref.tail(200).mean()) if len(ref) >= 150 else None
    ctx = {
        "fecha_precios": pd.Timestamp(cierres.index[-1]).normalize(),
        # Solo precios del último día: uno atrasado no debe contar como precio actual ni como máximo
        "precios": {t: float(cierres[t].iloc[-1]) for t in cierres.columns if cierres[t].last_valid_index() == ultimo_dia},
        "cambio_dia": {t: _variacion(cierres[t], 1) for t in cierres.columns},
        "cambio_5d": {t: _variacion(cierres[t], 5) for t in cierres.columns},
        "indice": {
            "ticker": referencia,
            "precio": float(ref.iloc[-1]) if len(ref) else None,
            "cambio_dia": _variacion(ref, 1) if len(ref) else None,
            "media200": media200,
            "sobre_media": bool(media200 is None or (len(ref) and float(ref.iloc[-1]) >= media200)),
        },
        "splits": splits,
        "noticias": {},
        "macro": [],
        "temas": [],
        "ajustes": {},
    }
    if con_noticias and nombres:
        try:
            ctx["noticias"] = nt.noticias_empresas(nombres)
        except Exception as e:   # sin noticias se sigue funcionando: solo se pierde ese filtro
            print(f"No se pudieron leer las noticias de empresas: {e}")
    if macro:
        try:
            ctx["macro"], todos = nt.noticias_macro()
            ctx["temas"], ctx["conteos_temas"] = nt.detectar_temas(todos, historial_temas)
        except Exception as e:
            print(f"No se pudieron leer las noticias de economía: {e}")
    # Titulares de empresas al español (si la traducción falla, queda el original y su significado)
    destacados = [h for r in ctx["noticias"].values() for h in r["destacados"]]
    for h, traducido in zip(destacados, nt.traducir([h["titulo"] for h in destacados])):
        h["titulo_es"] = traducido
    ctx["ajustes"] = calcular_ajustes(ctx["noticias"], ctx["temas"], subsectores or {})
    return ctx
