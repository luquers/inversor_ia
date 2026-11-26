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


def contexto(tickers, referencia: str, nombres: dict | None = None, con_noticias=True, macro=False) -> dict:
    """Precios del último año de `tickers` + índice, variaciones y (si se pide) noticias.

    - cambio_dia / cambio_5d: variación en % de la última sesión y de las 5 últimas
    - indice.sobre_media: si el índice está por encima de su media de 200 sesiones (tendencia alcista)
    """
    tickers = sorted(set(tickers) | {referencia})
    cierres, _, splits = descargar_precios(tickers, periodo="1y")
    cierres = cierres.dropna(how="all")
    ultimos = cierres.ffill().iloc[-1]
    ref = cierres[referencia].dropna() if referencia in cierres else pd.Series(dtype=float)
    media200 = float(ref.tail(200).mean()) if len(ref) >= 150 else None
    ctx = {
        "fecha_precios": pd.Timestamp(cierres.index[-1]).normalize(),
        "precios": {t: float(v) for t, v in ultimos.items() if pd.notna(v)},
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
    }
    if con_noticias and nombres:
        try:
            ctx["noticias"] = nt.noticias_empresas(nombres)
        except Exception as e:   # sin noticias se sigue funcionando: solo se pierde ese filtro
            print(f"No se pudieron leer las noticias de empresas: {e}")
    if macro:
        try:
            ctx["macro"] = nt.noticias_macro()
        except Exception as e:
            print(f"No se pudieron leer las noticias de economía: {e}")
    return ctx
