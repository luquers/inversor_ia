"""Descarga y caché de datos: lista de empresas (Wikipedia), cuentas oficiales (SEC) y precios (Yahoo Finance)."""
from __future__ import annotations

import io
import json
import os
import pickle
import time
from pathlib import Path

import pandas as pd
import requests

from .sec import compactar

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"
CABECERAS = {"User-Agent": "Mozilla/5.0 (asistente-inversion-personal)"}

PAGINAS_WIKIPEDIA = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "sp400": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
    "sp600": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
}
INDICES = {"sp500": ["sp500"], "sp1500": ["sp500", "sp400", "sp600"]}


def _edad_dias(ruta: Path) -> float:
    return (time.time() - ruta.stat().st_mtime) / 86400


# ---------------------------------------------------------------- universo
def _leer_tabla_wikipedia(url: str) -> pd.DataFrame:
    respuesta = requests.get(url, headers=CABECERAS, timeout=30)
    respuesta.raise_for_status()
    for tabla in pd.read_html(io.StringIO(respuesta.text)):
        columnas = {str(c).lower(): c for c in tabla.columns}
        c_ticker = next((v for k, v in columnas.items() if "symbol" in k or "ticker" in k), None)
        c_sector = next((v for k, v in columnas.items() if "sector" in k), None)
        c_nombre = next((v for k, v in columnas.items() if "security" in k or "company" in k), None)
        if c_ticker is None or c_sector is None:
            continue
        return pd.DataFrame({
            # Yahoo escribe BRK-B donde otros escriben BRK.B
            "ticker": tabla[c_ticker].astype(str).str.strip().str.replace(".", "-", regex=False),
            "sector": tabla[c_sector].astype(str).str.strip(),
            "nombre": tabla[c_nombre].astype(str).str.strip() if c_nombre is not None else "",
        })
    raise RuntimeError(f"No encontré la tabla de empresas en {url}")


def obtener_universo(cfg: dict) -> pd.DataFrame:
    """Devuelve las empresas a analizar (ticker, nombre, sector), ya sin los sectores excluidos."""
    CACHE.mkdir(exist_ok=True)
    tipo = cfg["universo"]
    if tipo == "archivo":
        df = pd.read_csv(RAIZ / "tickers.csv")
        for col in ("sector", "nombre"):
            if col not in df.columns:
                df[col] = ""
    else:
        ruta = CACHE / f"universo_{tipo}.csv"
        if ruta.exists() and _edad_dias(ruta) < 7:
            df = pd.read_csv(ruta)
        else:
            partes = [_leer_tabla_wikipedia(PAGINAS_WIKIPEDIA[i]) for i in INDICES[tipo]]
            df = pd.concat(partes).drop_duplicates("ticker")
            df.to_csv(ruta, index=False)
    excluidos = set(cfg.get("sectores_excluidos") or [])
    df = df[~df["sector"].isin(excluidos)]
    return df.fillna("").reset_index(drop=True)


# ---------------------------------------------------------------- SEC
URL_MAPA_SEC = "https://www.sec.gov/files/company_tickers.json"
URL_HECHOS_SEC = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


def _cabeceras_sec(cfg):
    contacto = os.environ.get("SEC_CONTACTO") or cfg.get("sec_contacto") or ""
    if "@" not in contacto:
        raise SystemExit(
            "La SEC exige identificarse con un email. Pon el tuyo en config.yaml (sec_contacto) "
            "o en la variable de entorno SEC_CONTACTO. Solo se usa para eso.")
    return {"User-Agent": f"AsistenteInversionPersonal {contacto}", "Accept-Encoding": "gzip, deflate"}


def _pedir(url, cabeceras, intentos=5):
    respuesta = None
    for i in range(intentos):
        try:
            respuesta = requests.get(url, headers=cabeceras, timeout=60)
        except requests.RequestException:
            time.sleep(2 * (i + 1))
            continue
        if respuesta.status_code in (403, 429, 500, 502, 503, 504):
            time.sleep(5 * (i + 1))   # la SEC pide frenar si se va demasiado rápido
            continue
        return respuesta
    return respuesta


def mapa_cik(cfg) -> dict:
    """Relación ticker -> número de registro de la empresa en la SEC (CIK)."""
    ruta = CACHE / "sec" / "mapa_tickers.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.exists() and _edad_dias(ruta) < 7:
        return json.loads(ruta.read_text())
    r = _pedir(URL_MAPA_SEC, _cabeceras_sec(cfg))
    if r is None or r.status_code != 200:
        raise SystemExit("No pude descargar la lista de empresas de la SEC. Revisa la conexión y el email de contacto.")
    mapa = {v["ticker"].upper(): int(v["cik_str"]) for v in r.json().values()}
    ruta.write_text(json.dumps(mapa))
    return mapa


def _buscar_cik(ticker, mapa):
    for variante in (ticker, ticker.replace("-", "."), ticker.replace("-", ""), ticker.split("-")[0]):
        if variante.upper() in mapa:
            return mapa[variante.upper()]
    return None


def datos_sec(ticker, cik, cfg):
    """Estados financieros de una empresa (ya resumidos), guardados en caché unos días."""
    ruta = CACHE / "sec" / f"{ticker}.pkl"
    if ruta.exists() and _edad_dias(ruta) < cfg["datos"]["cache_dias"]:
        try:
            with open(ruta, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass
    r = _pedir(URL_HECHOS_SEC.format(cik=cik), _cabeceras_sec(cfg))
    time.sleep(cfg["datos"]["pausa_segundos"])
    if r is None or r.status_code not in (200, 404):
        return None   # fallo temporal: no se guarda, se reintentará la próxima vez
    compacto = compactar(r.json()) if r.status_code == 200 else None
    with open(ruta, "wb") as f:
        pickle.dump(compacto, f)
    return compacto


def cargar_sec(tickers, cfg) -> dict:
    tickers = list(tickers)
    mapa = mapa_cik(cfg)
    resultado, sin_registro = {}, []
    print(f"Cargando cuentas oficiales (SEC) de {len(tickers)} empresas. La primera vez tarda un rato...")
    for i, ticker in enumerate(tickers, 1):
        cik = _buscar_cik(ticker, mapa)
        if cik is None:
            sin_registro.append(ticker)
            continue
        try:
            datos = datos_sec(ticker, cik, cfg)
            if datos:
                resultado[ticker] = datos
        except Exception as e:
            print(f"  aviso: no pude leer {ticker}: {e}")
        if i % 100 == 0:
            print(f"  {i}/{len(tickers)}")
    if sin_registro:
        print(f"  {len(sin_registro)} empresas sin registro en la SEC (se omiten): {', '.join(sin_registro[:10])}...")
    return resultado


# ---------------------------------------------------------------- precios
def _descargar_lote(yf, lote, opciones, intentos=3):
    for i in range(intentos):
        try:
            df = yf.download(lote, **opciones)
            if df is not None and not df.empty:
                return df
        except Exception as e:
            print(f"  aviso descargando precios: {e}")
        time.sleep(20 * (i + 1))   # Yahoo a veces limita las peticiones; se espera y se reintenta
    return None


def descargar_precios(tickers, inicio=None, fin=None, periodo: str = "10d"):
    """Devuelve (cierres, cierres_ajustados, splits).

    - cierres: precio de cierre (ya corregido por splits, como lo da Yahoo)
    - cierres_ajustados: además incluye los dividendos reinvertidos
    - splits: {ticker: serie con la proporción de cada split}
    """
    import yfinance as yf

    tickers = sorted(set(tickers))
    opciones = dict(auto_adjust=False, actions=True, progress=False, threads=True)
    if inicio is not None:
        opciones["start"] = pd.Timestamp(inicio).strftime("%Y-%m-%d")
        if fin is not None:
            opciones["end"] = (pd.Timestamp(fin) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        opciones["period"] = periodo

    cierres, ajustados, splits = [], [], {}
    for i in range(0, len(tickers), 100):
        lote = tickers[i:i + 100]
        df = _descargar_lote(yf, lote, opciones)
        if df is None:
            continue
        niveles = df.columns.get_level_values(0)
        c = df["Close"]
        a = df["Adj Close"] if "Adj Close" in niveles else c
        s = df["Stock Splits"] if "Stock Splits" in niveles else None
        if isinstance(c, pd.Series):
            c, a = c.to_frame(lote[0]), a.to_frame(lote[0])
            s = s.to_frame(lote[0]) if s is not None else None
        cierres.append(c)
        ajustados.append(a)
        if s is not None:
            for t in s.columns:
                serie = s[t].dropna()
                serie = serie[serie > 0]
                if len(serie):
                    splits[t] = serie
    if not cierres:
        raise RuntimeError("No se pudieron descargar precios. ¿Hay conexión a internet?")

    def unir(partes):
        df = pd.concat(partes, axis=1).sort_index()
        return df.loc[:, ~df.columns.duplicated()]

    return unir(cierres), unir(ajustados), splits
