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
    "Geopolítica": "\"tensiones geopolíticas\" OR OTAN OR \"guerra en\" OR \"conflicto armado\" OR OPEP OR \"precio del petróleo\"",
}

# Expresiones en inglés (los titulares de empresas de EE. UU. vienen casi siempre en inglés)
# y lo que significan, para explicarlo en español aunque falle la traducción
GRAVES = [
    (r"chapter 11", "se acoge a la protección por quiebra (Chapter 11)"), (r"\bbankrupt", "posible quiebra"),
    (r"going[- ]concern", "los auditores dudan de que pueda seguir funcionando"), (r"\bfraud", "acusaciones de fraude"),
    (r"accounting (irregularit|problem|error|issue)", "problemas en su contabilidad"),
    (r"\brestat(e|es|ed|ement)\b", "tiene que rehacer cuentas de años anteriores"),
    (r"\bdelist", "riesgo de dejar de cotizar en bolsa"),
    (r"\b(sec|doj|ftc|justice department) (probe|investigat|charges|sues|subpoena)", "investigación de las autoridades de EE. UU."),
    (r"short[- ]seller", "un inversor bajista publica un informe acusándola"), (r"\bsubpoena", "requerimiento judicial"),
    (r"criminal (charges|probe|investigation)", "investigación penal"), (r"\bdefaults? on\b", "impago de deuda"),
    (r"\binsolven", "insolvencia"),
]
NEGATIVAS = [
    (r"\b(cuts?|lowers?|slash(es)?|reduces?|withdraws?) (its |full[- ]year |annual )*(guidance|outlook|forecast)",
     "rebaja sus previsiones de negocio"),
    (r"\bdowngrade", "un analista rebaja su recomendación"), (r"profit warning", "avisa de menores beneficios"),
    (r"\bmiss(es|ed)? (on )?(estimates|expectations|forecasts)", "resultados peores de lo esperado"),
    (r"\brecalls?\b", "retirada de productos"), (r"\blayoffs?\b", "despidos"),
    (r"\b(ceo|cfo|chief executive) (resigns|steps down|exits|departs|ousted|fired)", "sale un alto directivo"),
    (r"data breach", "robo o fallo de seguridad de datos"),
    (r"\b(plunges?|plummets?|tumbles?|sinks?|craters?|nosedives?)\b", "fuerte caída en bolsa"),
    (r"\btariffs?\b", "le afectan los aranceles"), (r"\bsanctions?\b", "le afectan sanciones"),
    (r"\bfda (rejects|declines|warning)", "el regulador sanitario (FDA) la rechaza o advierte"),
    (r"complete response letter", "el regulador sanitario (FDA) no aprueba su producto todavía"),
    (r"(52|fifty-two)[- ]week low", "marca su precio más bajo del último año"),
    (r"\b(12|twelve)[- ]month low", "marca su precio más bajo del último año"),
    (r"\bnew (all-time )?low\b", "marca mínimos"),
]
POSITIVAS = [
    (r"\b(raises?|lifts?|boosts?|hikes?) (its |full[- ]year |annual )*(guidance|outlook|forecast)", "mejora sus previsiones de negocio"),
    (r"\bupgrade", "un analista mejora su recomendación"),
    (r"\bbeats? (on )?(estimates|expectations|forecasts)", "resultados mejores de lo esperado"),
    (r"\b(buyback|share repurchase)", "recompra acciones propias (suele ser buena señal)"),
    (r"record (revenue|sales|profit|quarter)", "ventas o beneficios récord"),
    (r"\b(surges?|soars?|jumps?|rallies|skyrockets?)\b", "fuerte subida en bolsa"),
    (r"\bfda (approves|approval|clears)", "el regulador sanitario (FDA) aprueba su producto"),
    (r"(52|fifty-two)[- ]week high", "marca su precio más alto del último año"), (r"\ball-time high\b", "máximos históricos"),
]
# Anuncios de bufetes que «investigan» a una empresa tras cualquier caída: ruido, no noticia
RUIDO = [r"(law firm|llc|llp|\bp\.?c\.?\b|attorneys?).{0,60}investigat", r"(shareholder|investor) alert",
         r"reminds (shareholders|investors)", r"class action (lawsuit )?(filed|deadline)", r"\bstock alert\b"]

# Titulares de economía que son publicidad o reclamo, no noticia
RECLAMO = [r"posici[oó]nate", r"\bahora\b.*(batir|ganar)", r"gana(r)? al m[aá]ximo", r"c[oó]mo invertir", r"\bcurso\b",
           r"\bgratis\b", r"loter[ií]a|bonoloto|cup[oó]n|sorteo"]

TONOS = {"grave": "🔴", "negativa": "🟠", "positiva": "🟢", "neutra": "⚪"}
SUFIJOS = re.compile(r",?\s+(inc\.?|corp\.?|corporation|company|co\.?|ltd\.?|plc|holdings?|group|n\.v\.|s\.a\.|l\.p\.|the)$", re.I)


def _coincide(t, lista):
    return next((frase for patron, frase in lista if re.search(patron, t)), None)


def analizar(titulo: str) -> tuple[str, str]:
    """(tono, qué significa en español) de un titular."""
    t = titulo.lower()
    if any(re.search(p, t) for p in RUIDO):
        return "neutra", "anuncio de un bufete de abogados (habitual tras una caída; no es una noticia en sí)"
    grave = _coincide(t, GRAVES)
    if grave:
        return "grave", grave
    negativa, positiva = _coincide(t, NEGATIVAS), _coincide(t, POSITIVAS)
    if negativa and not positiva:
        return "negativa", negativa
    if positiva and not negativa:
        return "positiva", positiva
    return "neutra", ""


def clasificar(titulo: str) -> str:
    return analizar(titulo)[0]


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
        tono, significa = analizar(h["titulo"])
        items.append({**h, "tono": tono, "significa": significa})
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


def noticias_macro(por_tema=2, pausa=0.4) -> tuple[list[dict], list[dict]]:
    """Titulares de economía y geopolítica en español: (los más recientes de cada tema para mostrar,
    todos los leídos para detectar temas que afectan a sectores)."""
    salida, todos, vistos = [], [], set()
    for tema, q in TEMAS_MACRO.items():
        items = leer_rss(_pedir_rss(f"{q} when:1d", hl="es", gl="ES", idioma="es"), max_items=15)
        items = [h for h in items if not any(re.search(p, h["titulo"].lower()) for p in RECLAMO)]
        items.sort(key=lambda h: h["fecha"] or pd.Timestamp(0), reverse=True)
        n = 0
        for h in items:
            clave = h["titulo"].lower()[:60]
            if clave in vistos:
                continue
            vistos.add(clave)
            todos.append({**h, "tema": tema})
            if n < por_tema:
                salida.append({**h, "tema": tema})
                n += 1
        time.sleep(pausa)
    return salida, todos


# Temas de economía y geopolítica y a quién afectan, por subsector (GICS, en inglés como en Wikipedia).
# Cada efecto: (patrón sobre el subsector, +1 favorece / −1 perjudica, a quién afecta en lenguaje sencillo).
# Es conocimiento general de manual, no una predicción: por eso pesa poco frente a la fórmula.
BIENES = (r"automobile|auto parts|automotive|motorcycle|apparel|footwear|textile|leisure products|home furnishing|"
          r"household appliance|housewares|consumer electronics|electronic (components|equipment|manufactur)|"
          r"technology hardware|semiconductor|industrial machinery|construction machinery|agricultural.*machinery|"
          r"heavy trucks|electrical components|building products|toys")
CICLICOS = (r"automobile|apparel|footwear|leisure|hotels|casinos|restaurants|homebuild|building products|"
            r"home furnishing|home improvement|industrial machinery|trucking|advertising|human resource|"
            r"semiconductor|cruise|airline|consumer electronics")
DEFENSIVOS = (r"food|beverage|household products|personal care|health care|pharmaceutic|biotechnology|"
              r"managed health|drug retail|consumer staples merchandise|tobacco")
TRANSPORTE = r"airline|passenger|trucking|cargo|logistics|marine|cruise|ground transportation"
TEMAS_IMPACTO = [
    {"tema": "Aranceles", "patron": r"arancel|guerra comercial",
     "porque": "encarecen los bienes importados y las piezas, y frenan el comercio",
     "efectos": [(BIENES, -1, "fabricantes e importadores de bienes (coches, ropa, electrónica, maquinaria…)"),
                 (r"^steel$|aluminum", 1, "acero y aluminio de EE. UU., protegidos por los aranceles")]},
    {"tema": "Petróleo al alza",
     "patron": r"(petr[oó]leo|crudo|brent)\b.{0,50}(sube|subida|dispara|alza|encarece|m[aá]ximos)|opep\+?.{0,40}(recort|reduc)",
     "porque": "beneficia a las petroleras y encarece el combustible",
     "efectos": [(r"oil|gas|coal|energy equipment", 1, "petroleras y empresas de energía"),
                 (TRANSPORTE, -1, "aerolíneas, cruceros y transporte, que gastan mucho combustible")]},
    {"tema": "Petróleo a la baja", "patron": r"(petr[oó]leo|crudo|brent)\b.{0,50}(cae|caída|baja|abarata|desplom|m[ií]nimos)",
     "porque": "perjudica a las petroleras y abarata el combustible",
     "efectos": [(r"oil|gas|coal|energy equipment", -1, "petroleras y empresas de energía"),
                 (TRANSPORTE, 1, "aerolíneas, cruceros y transporte")]},
    {"tema": "Tipos de interés al alza",
     "patron": r"(sube|subida|eleva|endurec)\w*.{0,30}tipos|inflaci[oó]n.{0,30}(sube|repunta|dispara|acelera)",
     "porque": "el dinero caro frena las compras a plazos: casas, coches y grandes compras",
     "efectos": [(r"homebuild|building products|home improvement|automobile|home furnishing|leisure products|"
                  r"recreational vehicle", -1, "constructoras, coches y grandes compras a plazos")]},
    {"tema": "Bajada de tipos de interés", "patron": r"(baja|bajada|recorte|recorta|rebaja)\w*.{0,30}tipos",
     "porque": "el dinero barato anima a comprar casas, coches y bienes duraderos",
     "efectos": [(r"homebuild|building products|home improvement|automobile|home furnishing|leisure products|"
                  r"recreational vehicle", 1, "constructoras, coches y grandes compras a plazos")]},
    {"tema": "Conflictos y guerra",
     "patron": r"\bguerra\b(?! comercial)|invasi[oó]n|bombarde|misil|escalada militar|ataque (militar|a[eé]reo|con drones)",
     "porque": "suelen subir el gasto militar y la energía, y frenar los viajes",
     "efectos": [(r"aerospace|defense", 1, "defensa"), (r"oil|gas", 1, "energía"),
                 (r"airline|cruise|hotels|casinos", -1, "viajes y ocio")]},
    {"tema": "Riesgo de recesión", "patron": r"recesi[oó]n|desaceleraci[oó]n|frenazo econ|despidos masivos",
     "porque": "en las recesiones se gasta menos en caprichos y aguantan mejor la alimentación y la salud",
     "efectos": [(CICLICOS, -1, "negocios que dependen de que la economía vaya bien (ocio, coches, industria…)"),
                 (DEFENSIVOS, 1, "alimentación, salud e higiene, que se consumen igual")]},
    {"tema": "Tensión tecnológica con China",
     "patron": r"china.{0,50}(restric|sanci|veto|chips|semiconductor)|(chips|semiconductor).{0,50}(restric|veto|china)",
     "porque": "las restricciones afectan a la venta y fabricación de chips y aparatos",
     "efectos": [(r"semiconductor|technology hardware|electronic components|communications equipment", -1,
                  "chips y hardware")]},
]


def detectar_temas(titulares: list[dict], historial: dict | None = None, minimo=3, factor=1.5, dias=10):
    """Temas que hoy son noticia de verdad: al menos `minimo` titulares y bastante más de lo habitual
    (`factor` veces la media de los últimos `dias` partes). Algunos temas, como los aranceles, salen casi
    a diario: solo cuentan cuando se intensifican. Sin historial suficiente se exige más (minimo + 2).
    Devuelve (temas activos, recuento de hoy por tema)."""
    historial = historial or {}
    pasados = [historial[f] for f in sorted(historial)[-dias:]]
    conteos, activos = {}, []
    for tema in TEMAS_IMPACTO:
        coincidencias = [h for h in titulares if re.search(tema["patron"], h["titulo"].lower())]
        n = len(coincidencias)
        conteos[tema["tema"]] = n
        if len(pasados) >= 3:
            habitual = sum(p.get(tema["tema"], 0) for p in pasados) / len(pasados)
            activo = n >= minimo and n >= factor * habitual
        else:
            habitual = None
            activo = n >= minimo + 2
        if activo:
            activos.append({"tema": tema["tema"], "porque": tema["porque"], "efectos": tema["efectos"],
                            "titulares": n, "habitual": None if habitual is None else round(habitual, 1),
                            "ejemplo": coincidencias[0]["titulo"]})
    return activos, conteos


def afecta(tema: dict, subsector: str):
    """(efecto, a quién) si el tema afecta a ese subsector; si no, None."""
    sub = (subsector or "").lower()
    for patron, efecto, grupo in tema["efectos"]:
        if sub and re.search(patron, sub):
            return efecto, grupo
    return None


URL_TRADUCIR = "https://translate.googleapis.com/translate_a/single"


def traducir(textos: list[str], destino="es") -> list[str]:
    """Traduce titulares al español con el traductor web gratuito de Google (no oficial).
    Si falla, devuelve los textos originales: el «qué significa» ya va en español."""
    salida = list(textos)
    lote, indices = [], []

    def enviar(lote, indices):
        try:
            r = requests.get(URL_TRADUCIR, params={"client": "gtx", "sl": "en", "tl": destino, "dt": "t",
                                                   "q": "\n".join(lote)}, headers=CABECERAS, timeout=20)
            if not r.ok:
                return
            texto = "".join(parte[0] for parte in r.json()[0] if parte and parte[0])
            lineas = [x.strip() for x in texto.split("\n")]
            if len(lineas) == len(lote):
                for i, linea in zip(indices, lineas):
                    if linea:
                        salida[i] = linea
        except Exception:
            pass

    for i, t in enumerate(textos):
        t = t.replace("\n", " ")
        if lote and sum(len(x) for x in lote) + len(t) > 1800:
            enviar(lote, indices)
            lote, indices = [], []
            time.sleep(0.3)
        lote.append(t)
        indices.append(i)
    if lote:
        enviar(lote, indices)
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
