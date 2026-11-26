"""Ranking de hoy, informes de texto, gráficos y envío de alertas."""
from __future__ import annotations

import math
import os
import re

import pandas as pd
import requests

from .datos import RAIZ, cargar_sec, descargar_precios, obtener_universo
from .puntuacion import elegibles, evaluar, ordenar
from .sec import HistorialAcciones, tabla_anual

RESULTADOS = RAIZ / "resultados"   # archivos para ti (no se suben a GitHub)
HISTORICO = RAIZ / "historico"     # estado que se guarda entre ejecuciones (sí se sube)


# ---------------------------------------------------------------- ranking
def preparar_empresas(cfg: dict):
    """Universo + cuentas de la SEC listas para puntuar."""
    universo = obtener_universo(cfg)
    sec = cargar_sec(universo["ticker"], cfg)
    tablas = {t: tabla_anual(d) for t, d in sec.items()}
    tablas = {t: tb for t, tb in tablas.items() if not tb.empty}
    acciones = {t: HistorialAcciones(sec[t]["acciones_hist"]) for t in tablas}
    for t, d in sec.items():   # completa nombres que falten con el registro oficial
        universo.loc[(universo["ticker"] == t) & (universo["nombre"] == ""), "nombre"] = d.get("nombre", "")
    return universo, tablas, acciones


def ranking_actual(cfg: dict) -> pd.DataFrame:
    universo, tablas, acciones = preparar_empresas(cfg)
    print("Descargando precios actuales...")
    cierres, _, splits = descargar_precios(list(tablas), periodo="1y")
    ultimo = cierres.ffill().iloc[-1]
    caps = {t: acciones[t].capitalizacion(ultimo.get(t), splits.get(t)) for t in tablas}
    ranking = ordenar(evaluar(universo, tablas, caps), cfg["capitalizacion_minima"])
    ranking["apto"] = ranking.index.isin(elegibles(ranking, cfg["fscore_minimo"]))
    # Se guarda para el panel del móvil
    HISTORICO.mkdir(exist_ok=True)
    ranking.to_csv(HISTORICO / "ranking_panel.csv")
    (HISTORICO / "ranking_panel_fecha.txt").write_text(str(pd.Timestamp.today().date()))
    return ranking


def guardar_ranking(ranking: pd.DataFrame):
    RESULTADOS.mkdir(exist_ok=True)
    hoy = pd.Timestamp.today().strftime("%Y-%m-%d")
    ranking.to_csv(RESULTADOS / f"ranking_{hoy}.csv")
    return RESULTADOS / f"ranking_{hoy}.csv"


def tabla_texto(ranking: pd.DataFrame, n: int) -> str:
    aptos = ranking[ranking["apto"]].head(n)
    lineas = [f"{'#':>3} {'Ticker':<7} {'Empresa':<28} {'R.Benef':>8} {'R.Capital':>9} {'F':>3}"]
    for i, (t, f) in enumerate(aptos.iterrows(), 1):
        lineas.append(f"{i:>3} {t:<7} {str(f['nombre'])[:28]:<28} {f['rend_beneficios']*100:>7.1f}% "
                      f"{f['rend_capital']*100:>8.0f}% {int(f['fscore']) if not pd.isna(f['fscore']) else '-':>3}")
    return "\n".join(lineas)


def avisos_vigilancia(ranking: pd.DataFrame, cfg: dict, vigiladas) -> list[str]:
    """Avisos sobre acciones que tienes (reales o en carteras ficticias)."""
    avisos = []
    for t in sorted(set(vigiladas)):
        if t not in ranking.index:
            avisos.append(f"{t}: no está entre las empresas analizadas o le faltan datos")
            continue
        f = ranking.loc[t]
        puesto = f"puesto {int(f['puesto'])}" if not pd.isna(f["puesto"]) else "fuera del ranking"
        al_dia = f.get("cuentas_al_dia", True)
        if not pd.isna(al_dia) and not bool(al_dia):
            avisos.append(f"{t}: sus últimas cuentas son del ejercicio {f['cierre_ejercicio']}; "
                          "se deja fuera del ranking hasta que haya datos recientes")
        elif pd.isna(f["fscore"]) or f["fscore_evaluables"] < 7:
            avisos.append(f"{t}: no hay datos suficientes para calcular su F-Score ({puesto})")
        elif f["fscore"] < cfg["fscore_minimo"]:
            avisos.append(f"{t}: su F-Score ha bajado a {int(f['fscore'])}/9, por debajo de tu mínimo ({puesto})")
    return avisos


def dia_de_mercado(ahora=None) -> pd.Timestamp:
    """Día de bolsa (EE. UU.) al que corresponde una ejecución. Wall Street cierra hacia las 21:00 UTC:
    una tarea del lunes que GitHub retrasa al martes de madrugada sigue contando como lunes."""
    ahora = pd.Timestamp(ahora) if ahora is not None else pd.Timestamp.now(tz="UTC").tz_localize(None)
    dia = (ahora - pd.Timedelta(hours=21)).normalize()
    while dia.weekday() >= 5:   # fin de semana: cuenta como el viernes
        dia -= pd.Timedelta(days=1)
    return dia


def toca_informe_semanal(dia_informe: int, ahora=None) -> bool:
    """El informe sale en la primera ejecución de la semana a partir de `dia_informe`, aunque llegue tarde."""
    dia = dia_de_mercado(ahora)
    ruta = HISTORICO / "ultimo_informe.txt"
    ultimo = ruta.read_text().strip() if ruta.exists() else ""
    return dia.weekday() >= dia_informe and ultimo != _semana(dia)


def marcar_informe_enviado(ahora=None):
    HISTORICO.mkdir(exist_ok=True)
    (HISTORICO / "ultimo_informe.txt").write_text(_semana(dia_de_mercado(ahora)))


def parte_ya_enviado(fecha_mercado) -> bool:
    """El parte diario sale una vez por cada sesión de bolsa (no en festivos ni repetido)."""
    ruta = HISTORICO / "ultimo_parte.txt"
    return ruta.exists() and ruta.read_text().strip() == str(pd.Timestamp(fecha_mercado).date())


def marcar_parte_enviado(fecha_mercado):
    HISTORICO.mkdir(exist_ok=True)
    (HISTORICO / "ultimo_parte.txt").write_text(str(pd.Timestamp(fecha_mercado).date()))


def guardar_contexto(ctx):
    """Noticias, mercado y geopolítica del último parte, para el panel y el bot."""
    if not ctx:
        return
    from .noticias import a_json
    import json
    datos = {
        "fecha": str(pd.Timestamp(ctx["fecha_precios"]).date()),
        "indice": ctx.get("indice") or {},
        "noticias": {t: a_json(r) for t, r in (ctx.get("noticias") or {}).items()},
        "macro": a_json(ctx.get("macro") or []),
    }
    HISTORICO.mkdir(exist_ok=True)
    (HISTORICO / "contexto.json").write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")


def _semana(dia):
    anio, semana, _ = dia.isocalendar()
    return f"{anio}-S{semana:02d}"


def cambios_top(ranking: pd.DataFrame, n: int):
    """Qué empresas entran y salen del top n respecto al último informe (y guarda el actual)."""
    HISTORICO.mkdir(exist_ok=True)
    ruta_previo = HISTORICO / "ultimo_ranking.csv"
    top_actual = ranking[ranking["apto"]].head(n).index.tolist()
    entran, salen = [], []
    if ruta_previo.exists():
        previo = pd.read_csv(ruta_previo, index_col=0)
        top_previo = previo[previo["apto"]].head(n).index.tolist()
        entran = [t for t in top_actual if t not in top_previo]
        salen = [t for t in top_previo if t not in top_actual]
    ranking.to_csv(ruta_previo)
    return entran, salen


def informe_semanal(ranking: pd.DataFrame, cfg: dict, vigiladas: list[str]) -> str:
    n = cfg["alertas"]["top_informe"]
    partes = [f"📊 Informe semanal – Fórmula Mágica + F-Score (mínimo {cfg['fscore_minimo']})",
              "R.Benef = rendimiento de beneficios (cuánto de barata); R.Capital = rentabilidad del negocio",
              "", tabla_texto(ranking, n)]

    entran, salen = cambios_top(ranking, n)
    if entran or salen:
        partes += ["", f"🆕 Entran en el top: {', '.join(entran) or '—'}", f"↩️ Salen del top: {', '.join(salen) or '—'}"]

    avisos = avisos_vigilancia(ranking, cfg, vigiladas)
    if avisos:
        partes += ["", "👀 Vigilancia de tus acciones:"] + [f"⚠️ {a}" for a in avisos]
    url = (cfg.get("web") or {}).get("url_panel")
    if url:
        partes += ["", f"Panel completo: {url}"]
    return "\n".join(partes)


# ---------------------------------------------------------------- métricas y gráficos
def metricas_serie(serie: pd.Series) -> dict:
    serie = serie.dropna()
    if len(serie) < 2:
        return {}
    total = serie.iloc[-1] / serie.iloc[0] - 1
    anos = (serie.index[-1] - serie.index[0]).days / 365.25
    return {
        "rentabilidad_total_%": round(float(total) * 100, 2),
        "rentabilidad_anual_%": round(float((1 + total) ** (1 / anos) - 1) * 100, 2) if anos >= 0.5 else None,
        "caida_maxima_%": round(float(((serie / serie.cummax()) - 1).min()) * 100, 2),
        "volatilidad_anual_%": round(float(serie.pct_change().std()) * math.sqrt(252) * 100, 2),
    }


def grafico(curva: pd.DataFrame, ruta, titulo: str, nombre_ref: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(curva.index, curva["cartera"], label="Tu estrategia", linewidth=2)
    ax.plot(curva.index, curva["referencia"], label=f"{nombre_ref} (referencia)", linewidth=1.5, alpha=0.8)
    ax.set_title(titulo)
    ax.set_ylabel("Valor de la cartera ($)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(ruta, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------- alertas
def _trozos(texto: str, limite=3900):
    """Parte un mensaje largo por líneas (sin romper etiquetas HTML) para respetar el límite de Telegram."""
    trozos, actual = [], ""
    for linea in texto.split("\n"):
        if actual and len(actual) + len(linea) + 1 > limite:
            trozos.append(actual)
            actual = ""
        actual = f"{actual}\n{linea}" if actual else linea
    return trozos + ([actual] if actual else [])


def enviar_alerta(mensaje: str):
    """Muestra el mensaje y lo envía por Telegram (formato HTML).

    Si está configurado el bot de Cloudflare (BOT_URL y BOT_SECRET), se le pasa a él, que lo
    reparte entre todas las personas autorizadas con sus botones. Si no, se envía directamente
    a TELEGRAM_CHAT_ID."""
    print(re.sub(r"<[^>]+>", "", mensaje))
    url, clave = os.environ.get("BOT_URL"), os.environ.get("BOT_SECRET")
    if url and clave:
        try:
            r = requests.post(url.rstrip("/") + "/notificar", json={"texto": mensaje},
                              headers={"Authorization": f"Bearer {clave}"}, timeout=30)
            if r.ok:
                return
            print(f"El bot respondió con un error ({r.status_code}): {r.text[:200]}. Se envía directamente.")
        except Exception as e:
            print(f"No se pudo contactar con el bot ({e}). Se envía directamente.")

    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    for trozo in _trozos(mensaje):
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              data={"chat_id": chat, "text": trozo, "parse_mode": "HTML",
                                    "disable_web_page_preview": "true"}, timeout=20)
            if not r.ok:
                print(f"Telegram rechazó el mensaje ({r.status_code}): {r.text[:200]}")
        except Exception as e:
            print(f"No se pudo enviar a Telegram: {e}")
