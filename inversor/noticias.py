"""Noticias gratuitas (Google News por RSS) y su clasificación con reglas sencillas.

No usa ninguna IA ni servicio de pago: cada titular se clasifica buscando expresiones
conocidas («files for bankruptcy», «cuts guidance», «beats estimates»…). Es tosco pero
transparente, y se usa sobre todo para protegerse de noticias graves.
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import pandas as pd
import requests

URL_BUSQUEDA = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={gl}:{idioma}"
CABECERAS = {"User-Agent": "Mozilla/5.0 (inversor-ia; uso personal)"}

# Economía y geopolítica en español: búsquedas concretas (la portada de economía mezcla loterías y ofertas)
TEMAS_MACRO = {
    "Bolsa de EE. UU.": "\"Wall Street\" OR \"S&P 500\" OR Nasdaq",
    "Tipos e inflación": "\"Reserva Federal\" OR inflación OR \"tipos de interés\"",
    "Comercio y aranceles": "aranceles OR \"guerra comercial\" OR sanciones",
    "Geopolítica": "geopolítica OR conflicto OR OTAN OR petróleo OPEP",
}

# Expresiones en inglés (los titulares de empresas de EE. UU. vienen casi siempre en inglés)
GRAVES = [
    r"\bbankrupt", r"chapter 11", r"going[- ]concern", r"\bfraud", r"accounting (irregularit|problem|error|issue)",
    r"\brestat(e|es|ed|ement)\b", r"\bdelist", r"\b(sec|doj|ftc|justice department) (probe|investigat|charges|sues|subpoena)",
    r"short[- ]seller", r"\bsubpoena", r"criminal (charges|probe|investigation)", r"\bdefaults? on\b", r"\binsolven",
]
NEGATIVAS = [
    r"\b(cuts?|lowers?|slash(es)?|reduces?|withdraws?) (its |full[- ]year |annual )*(guidance|outlook|forecast)",
    r"\bdowngrade", r"profit warning", r"\bmiss(es|ed)? (on )?(estimates|expectations|forecasts)", r"\brecalls?\b",
    r"\blayoffs?\b", r"\b(ceo|cfo|chief executive) (resigns|steps down|exits|departs|ousted|fired)", r"data breach",
    r"\b(plunges?|plummets?|tumbles?|sinks?|craters?|nosedives?)\b", r"\btariffs?\b", r"\bsanctions?\b",
    r"\bfda (rejects|declines|warning)", r"complete response letter", r"(52|fifty-two)[- ]week low",
    r"\b(12|twelve)[- ]month low", r"\bnew (all-time )?low\b",
]
POSITIVAS = [
    r"\b(raises?|lifts?|boosts?|hikes?) (its |full[- ]year |annual )*(guidance|outlook|forecast)", r"\bupgrade",
    r"\bbeats? (on )?(estimates|expectations|forecasts)", r"\b(buyback|share repurchase)", r"record (revenue|sales|profit|quarter)",
    r"\b(surges?|soars?|jumps?|rallies|skyrockets?)\b", r"\bfda (approves|approval|clears)",
    r"(52|fifty-two)[- ]week high", r"\ball-time high\b",
]
# Anuncios de bufetes que «investigan» a una empresa tras cualquier caída: ruido, no noticia
RUIDO = [r"(law firm|llc|llp|\bp\.?c\.?\b|attorneys?).{0,60}investigat", r"(shareholder|investor) alert",
         r"reminds (shareholders|investors)", r"class action (lawsuit )?(filed|deadline)", r"\bstock alert\b"]

# Titulares de economía que son publicidad o reclamo, no noticia
RECLAMO = [r"posici[oó]nate", r"\bahora\b.*(batir|ganar)", r"gana(r)? al m[aá]ximo", r"c[oó]mo invertir", r"\bcurso\b",
           r"\bgratis\b", r"loter[ií]a|bonoloto|cup[oó]n|sorteo"]

TONOS = {"grave": "🔴", "negativa": "🟠", "positiva": "🟢", "neutra": "⚪"}
SUFIJOS = re.compile(r",?\s+(inc\.?|corp\.?|corporation|company|co\.?|ltd\.?|plc|holdings?|group|n\.v\.|s\.a\.|l\.p\.|the)$", re.I)


def clasificar(titulo: str) -> str:
    t = titulo.lower()
    if any(re.search(p, t) for p in RUIDO):
        return "neutra"
    if any(re.search(p, t) for p in GRAVES):
        return "grave"
    negativa = any(re.search(p, t) for p in NEGATIVAS)
    positiva = any(re.search(p, t) for p in POSITIVAS)
    if negativa and not positiva:
        return "negativa"
    if positiva and not negativa:
        return "positiva"
    return "neutra"


def nombre_corto(nombre: str) -> str:
    """«PTC Therapeutics, Inc.» -> «PTC Therapeutics» (para buscar y para reconocerla en el titular)."""
    n = (nombre or "").strip()
    for _ in range(3):
        n = SUFIJOS.sub("", n).strip(" ,.")
    return n


def leer_rss(xml_texto: str, max_items=20) -> list[dict]:
    """Titulares de un RSS de Google News: [{titulo, fuente, fecha, url}]."""
    try:
        raiz = ET.fromstring(xml_texto)
    except ET.ParseError:
        return []
    salida = []
    for item in raiz.findall("./channel/item")[:max_items]:
        titulo = (item.findtext("title") or "").strip()
        fuente_el = item.find("source")
        fuente = (fuente_el.text or "").strip() if fuente_el is not None else ""
        if fuente and titulo.endswith(f" - {fuente}"):
            titulo = titulo[: -len(fuente) - 3].strip()
        try:
            fecha = pd.Timestamp(parsedate_to_datetime(item.findtext("pubDate"))).tz_convert(None)
        except Exception:
            fecha = None
        if titulo:
            salida.append({"titulo": titulo, "fuente": fuente, "fecha": fecha, "url": item.findtext("link") or ""})
    return salida


def _pedir_rss(q, hl="en-US", gl="US", idioma="en", intentos=2):
    url = URL_BUSQUEDA.format(q=quote_plus(q), hl=hl, gl=gl, idioma=idioma)
    for i in range(intentos):
        try:
            r = requests.get(url, headers=CABECERAS, timeout=20)
            if r.ok:
                return r.text
        except requests.RequestException:
            pass
        time.sleep(1 + i)
    return ""


def _menciona(titulo, ticker, corto):
    t = titulo.lower()
    if re.search(rf"\b{re.escape(ticker.lower())}\b", t):
        return True
    primera = corto.split()[0].lower() if corto else ""
    return bool(corto) and (corto.lower() in t or (len(primera) >= 4 and re.search(rf"\b{re.escape(primera)}\b", t)))


def resumir(titulares: list[dict], ticker: str, nombre: str, ahora=None, dias=7) -> dict:
    """Clasifica los titulares recientes que hablan de verdad de la empresa."""
    ahora = pd.Timestamp(ahora) if ahora is not None else pd.Timestamp.now(tz="UTC").tz_localize(None)
    corto = nombre_corto(nombre)
    vistos, items = set(), []
    for h in titulares:
        if h["fecha"] is not None and (ahora - h["fecha"]).days > dias:
            continue
        clave = h["titulo"].lower()[:70]
        if clave in vistos or not _menciona(h["titulo"], ticker, corto):
            continue
        vistos.add(clave)
        items.append({**h, "tono": clasificar(h["titulo"])})
    items.sort(key=lambda h: h["fecha"] or pd.Timestamp(0), reverse=True)
    cuenta = {tono: sum(h["tono"] == tono for h in items) for tono in TONOS}
    graves_recientes = [h for h in items if h["tono"] == "grave" and h["fecha"] is not None and (ahora - h["fecha"]).days <= 3]
    # Lo más relevante primero: graves, negativas, positivas y luego el resto
    orden = {"grave": 0, "negativa": 1, "positiva": 2, "neutra": 3}
    destacados = sorted(items, key=lambda h: orden[h["tono"]])[:3]
    return {"cuenta": cuenta, "grave_reciente": graves_recientes[0] if graves_recientes else None,
            "destacados": destacados, "total": len(items)}


def noticias_empresas(nombres: dict, pausa=0.4, ahora=None) -> dict:
    """{ticker: resumen} para las empresas indicadas ({ticker: nombre})."""
    salida = {}
    for t, nombre in nombres.items():
        corto = nombre_corto(nombre) or t
        xml = _pedir_rss(f"\"{corto}\" when:7d")
        salida[t] = resumir(leer_rss(xml), t, nombre, ahora)
        time.sleep(pausa)
    return salida


def noticias_macro(por_tema=2, pausa=0.4) -> list[dict]:
    """Titulares de economía y geopolítica en español, los más recientes de cada tema."""
    salida, vistos = [], set()
    for tema, q in TEMAS_MACRO.items():
        items = leer_rss(_pedir_rss(f"{q} when:1d", hl="es", gl="ES", idioma="es"), max_items=15)
        items.sort(key=lambda h: h["fecha"] or pd.Timestamp(0), reverse=True)
        n = 0
        for h in items:
            clave = h["titulo"].lower()[:60]
            if clave in vistos or any(re.search(p, h["titulo"].lower()) for p in RECLAMO):
                continue
            vistos.add(clave)
            salida.append({**h, "tema": tema})
            n += 1
            if n >= por_tema:
                break
        time.sleep(pausa)
    return salida


def a_json(resumen_o_lista):
    """Fechas a texto para guardar en bot.json."""
    def limpiar(h):
        return {**h, "fecha": str(h["fecha"].date()) if h.get("fecha") is not None else ""}
    if isinstance(resumen_o_lista, list):
        return [limpiar(h) for h in resumen_o_lista]
    r = dict(resumen_o_lista)
    r["destacados"] = [limpiar(h) for h in r["destacados"]]
    r["grave_reciente"] = limpiar(r["grave_reciente"]) if r["grave_reciente"] else None
    return r
