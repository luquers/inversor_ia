"""Comprueba toda la lógica con datos inventados en el formato de la SEC (no necesita internet).
Ejecutar desde la carpeta del proyecto:  python tests/prueba_sintetica.py
"""
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from inversor import analisis, mensajes, simulacion as sim, web  # noqa: E402
from inversor.puntuacion import elegibles, evaluar, metricas_empresa, ordenar  # noqa: E402
from inversor.sec import HistorialAcciones, compactar, tabla_anual, vista  # noqa: E402

rng = np.random.default_rng(7)
cfg = yaml.safe_load(open(RAIZ / "config.yaml", encoding="utf-8"))
ANIOS = range(2009, 2026)


def hecho(fin, val, filed, form="10-K", inicio=None, accn=None):
    h = {"end": fin, "val": val, "filed": filed, "form": form, "accn": accn or f"acc-{filed}"}
    if inicio:
        h["start"] = inicio
    return h


def empresa_sec(calidad, split_en=None, sin_balance=False):
    """JSON con la estructura real de data.sec.gov/api/xbrl/companyfacts."""
    gaap = {}

    def añadir(concepto, unidad, h):
        gaap.setdefault(concepto, {"units": {unidad: []}})["units"][unidad].append(h)

    for k, anio in enumerate(ANIOS):
        ing = 1e9 * (1 + 0.07 * calidad) ** k * (1 + rng.normal(0, 0.03))
        act = ing * 1.1
        margen = 0.04 + 0.16 * calidad + rng.normal(0, 0.01)
        fin, inicio = f"{anio}-12-31", f"{anio}-01-01"
        filed = f"{anio + 1}-02-{10 + k % 15:02d}"
        acciones = 1e8 * (1 - 0.01 * calidad) ** k
        if split_en and anio >= split_en:
            acciones *= 4   # split 4 por 1
        valores_periodo = {"Revenues": ing, "GrossProfit": ing * (0.3 + 0.1 * calidad),
                           "OperatingIncomeLoss": ing * margen, "NetIncomeLoss": ing * margen * 0.75,
                           "NetCashProvidedByUsedInOperatingActivities": ing * margen * 0.95}
        for c, v in valores_periodo.items():
            añadir(c, "USD", hecho(fin, v, filed, inicio=inicio))
            # El 10-K del año siguiente repite la cifra como comparativa, a veces corregida
            añadir(c, "USD", hecho(fin, v * 1.5, f"{anio + 2}-02-20", inicio=inicio))
        añadir("WeightedAverageNumberOfDilutedSharesOutstanding", "shares", hecho(fin, acciones, filed, inicio=inicio))
        if not sin_balance:
            for c, v in {"Assets": act, "AssetsCurrent": act * 0.4, "LiabilitiesCurrent": act * 0.25,
                         "LongTermDebtNoncurrent": act * (0.35 - 0.2 * calidad) * (1 - 0.03 * k),
                         "CashAndCashEquivalentsAtCarryingValue": act * 0.08,
                         "PropertyPlantAndEquipmentNet": act * 0.3}.items():
                añadir(c, "USD", hecho(fin, v, filed))
        # Un trimestre (10-Q) que debe ignorarse para las cifras anuales
        añadir("OperatingIncomeLoss", "USD", hecho(f"{anio}-03-31", 1.0, f"{anio}-05-01", "10-Q", f"{anio}-01-01"))

    portada = []
    for anio in range(2010, 2027):
        for mes in (2, 5, 8, 11):
            n = 1e8 * (4 if split_en and (anio, mes) > (split_en, 6) else 1)
            portada.append({"end": f"{anio}-{mes:02d}-01", "val": n, "filed": f"{anio}-{mes:02d}-10",
                            "form": "10-Q", "accn": f"q-{anio}-{mes}"})
    return {"entityName": "Empresa inventada", "facts": {"us-gaap": gaap, "dei": {
        "EntityCommonStockSharesOutstanding": {"units": {"shares": portada}}}}}


tickers = [f"T{i:02d}" for i in range(50)]
calidades = dict(zip(tickers, rng.uniform(0, 1, len(tickers))))
universo = pd.DataFrame({"ticker": tickers, "nombre": [f"Empresa {t}" for t in tickers], "sector": "Industrials"})
compactos = {t: compactar(empresa_sec(calidades[t], split_en=2020 if t == "T07" else None,
                                      sin_balance=(t == "T05"))) for t in tickers}
tablas = {t: tabla_anual(c) for t, c in compactos.items()}
acciones = {t: HistorialAcciones(c["acciones_hist"]) for t, c in compactos.items()}

# --- 1. Lectura de la SEC
tb = tablas["T10"]
assert len(tb) == len(ANIOS), "Una fila por ejercicio; los trimestres se ignoran"
original = compactos["T10"]["campos"]["ingresos"]["2015-12-31"]
assert original[0] == "2016-02-16", f"Debe quedarse con la primera publicación, no la corrección: {original}"
v = vista(tb, pd.Timestamp("2016-01-15"))
assert v.index.max() == pd.Timestamp("2014-12-31"), "En enero de 2016 aún no se conocían las cuentas de 2015"
v = vista(tb, pd.Timestamp("2016-03-01"))
assert v.index.max() == pd.Timestamp("2015-12-31")
print("[OK] Cuentas de la SEC: solo se usa lo ya publicado y la cifra original")

# --- 2. Capitalización con split (precios de Yahoo ya ajustados por el split)
splits_t07 = pd.Series([4.0], index=[pd.Timestamp("2020-07-01")])
precio_ajustado_2019 = 25.0   # equivale a 100 $ reales antes del split 4x1
cap_2019 = acciones["T07"].capitalizacion(precio_ajustado_2019, splits_t07, pd.Timestamp("2019-12-01"))
cap_2021 = acciones["T07"].capitalizacion(25.0, splits_t07, pd.Timestamp("2021-12-01"))
assert abs(cap_2019 - 1e8 * 100) < 1 and abs(cap_2021 - 4e8 * 25) < 1, (cap_2019, cap_2021)
print("[OK] Tamaño de empresa correcto antes y después de un split")

# --- 3. Ranking de hoy
precios_hoy = {t: 20 + 30 * rng.uniform() for t in tickers}
caps = {t: acciones[t].capitalizacion(precios_hoy[t], splits_t07 if t == "T07" else None) for t in tickers}
ranking = ordenar(evaluar(universo, tablas, caps, pd.Timestamp("2026-11-06")), cfg["capitalizacion_minima"])
aptas = elegibles(ranking, cfg["fscore_minimo"])
ranking["apto"] = ranking.index.isin(aptas)
assert ranking["base_ok"].sum() >= 45 and "T05" not in aptas
print(f"[OK] Ranking: {int(ranking['base_ok'].sum())} puntuadas, {len(aptas)} aptas. Top 5: {aptas[:5]}")

# --- 3b. Casos reales que antes se leían mal
def cuentas(anios, periodo, balance):
    """Companyfacts mínimo: `periodo` y `balance` son {concepto: valor} repetidos cada año."""
    gaap = {}
    for anio in anios:
        filed = f"{anio + 1}-02-15"
        for c, v in periodo.items():
            gaap.setdefault(c, {"units": {"USD": []}})["units"]["USD"].append(
                hecho(f"{anio}-12-31", v, filed, inicio=f"{anio}-01-01"))
        for c, v in balance.items():
            gaap.setdefault(c, {"units": {"USD": []}})["units"]["USD"].append(hecho(f"{anio}-12-31", v, filed))
    return {"entityName": "Caso", "facts": {"us-gaap": gaap}}

base_periodo = {"Revenues": 5e9, "NetIncomeLoss": 4e8, "NetCashProvidedByUsedInOperatingActivities": 5e8}
# Constructora: balance sin corriente/no corriente, beneficio "Domestic" y deuda solo como NotesPayable
constructora = cuentas(range(2022, 2026), {**base_periodo, "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic": 5e8},
                       {"Assets": 7e9, "InventoryRealEstate": 5e9, "AccountsReceivableNet": 2e8, "AccountsPayableCurrent": 4e8,
                        "PropertyPlantAndEquipmentNet": 1e8, "NotesPayable": 1.7e9, "CashAndCashEquivalentsAtCarryingValue": 3e8})
m = metricas_empresa(tabla_anual(compactar(constructora)), 3e9, pd.Timestamp("2026-06-01"))
assert abs(m["ebit"] - 5e8) < 1, "Usa el beneficio antes de impuestos 'Domestic' si no hay otro"
assert abs(m["rend_capital"] - 5e8 / (5e9 + 2e8 - 4e8 + 1e8)) < 1e-9, m["rend_capital"]
assert abs(m["rend_beneficios"] - 5e8 / (3e9 + 1.7e9 - 3e8)) < 1e-9, "La deuda NotesPayable cuenta en el valor de empresa"
# Sin balance clasificado ni existencias: la rentabilidad queda sin calcular (no se infla)
sin_nada = cuentas(range(2022, 2026), {**base_periodo, "OperatingIncomeLoss": 5e8}, {"Assets": 7e9})
assert pd.isna(metricas_empresa(tabla_anual(compactar(sin_nada)), 3e9, pd.Timestamp("2026-06-01"))["rend_capital"])

# Petrolera: los yacimientos van aparte del resto del inmovilizado
petrolera = cuentas(range(2022, 2026), {**base_periodo, "OperatingIncomeLoss": 3e9},
                    {"Assets": 1.8e10, "AssetsCurrent": 2e9, "LiabilitiesCurrent": 2.5e9,
                     "CashAndCashEquivalentsAtCarryingValue": 5e8,
                     "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization": 1.5e8,
                     "CapitalizedCostsOilAndGasProducingActivitiesNet": 1.25e10, "LongTermDebtNoncurrent": 4e9})
m = metricas_empresa(tabla_anual(compactar(petrolera)), 1.5e10, pd.Timestamp("2026-06-01"))
assert abs(m["rend_capital"] - 3e9 / (1.25e10 + 1.5e8)) < 1e-9, m["rend_capital"]
# Si el inmovilizado ya incluye los yacimientos, no se suman dos veces
incluido = cuentas(range(2022, 2026), {**base_periodo, "OperatingIncomeLoss": 3e9},
                   {"Assets": 1.8e10, "AssetsCurrent": 2e9, "LiabilitiesCurrent": 2.5e9,
                    "PropertyPlantAndEquipmentNet": 1.3e10, "CapitalizedCostsOilAndGasProducingActivitiesNet": 1.25e10})
m = metricas_empresa(tabla_anual(compactar(incluido)), 1.5e10, pd.Timestamp("2026-06-01"))
assert abs(m["rend_capital"] - 3e9 / 1.3e10) < 1e-9

# Deuda publicada por partes (convertible + préstamo) y un año sin inmovilizado publicado
partes = cuentas(range(2022, 2026), {**base_periodo, "OperatingIncomeLoss": 2e8},
                 {"Assets": 2e9, "AssetsCurrent": 7e8, "LiabilitiesCurrent": 4e8, "CashAndCashEquivalentsAtCarryingValue": 4e8,
                  "ConvertibleLongTermNotesPayable": 2.4e8, "LongTermLoansPayable": 5.4e8, "LoansPayableCurrent": 3e7})
inmov = partes["facts"]["us-gaap"].setdefault("PropertyPlantAndEquipmentNet", {"units": {"USD": []}})["units"]["USD"]
inmov += [hecho(f"{a}-12-31", 1.2e8, f"{a + 1}-02-15") for a in (2022, 2023, 2024)]   # falta 2025
t_partes = tabla_anual(compactar(partes))
m = metricas_empresa(t_partes, 8e8, pd.Timestamp("2026-06-01"))
assert abs(m["rend_beneficios"] - 2e8 / (8e8 + 2.4e8 + 5.4e8 + 3e7 - 4e8)) < 1e-9, "Suma las partes de la deuda"
assert abs(m["rend_capital"] - 2e8 / 1.2e8) < 1e-9, "Si falta el inmovilizado un año, usa el del año anterior"

# Cuentas viejas: se quedan fuera del ranking
assert metricas_empresa(t_partes, 8e8, pd.Timestamp("2026-06-01"))["cuentas_al_dia"]
assert not metricas_empresa(t_partes, 8e8, pd.Timestamp("2027-09-01"))["cuentas_al_dia"]
u2 = pd.DataFrame({"ticker": ["NUEVA", "VIEJA"], "nombre": ["", ""], "sector": "Industrials"})
viejas = tabla_anual(compactar(cuentas(range(2014, 2019), {**base_periodo, "OperatingIncomeLoss": 2e8},
                                       {"AssetsCurrent": 7e8, "LiabilitiesCurrent": 4e8, "PropertyPlantAndEquipmentNet": 1e8})))
r2 = ordenar(evaluar(u2, {"NUEVA": t_partes, "VIEJA": viejas}, {"NUEVA": 8e8, "VIEJA": 8e8}, pd.Timestamp("2026-06-01")), 3e8)
assert r2.loc["NUEVA", "base_ok"] and not r2.loc["VIEJA", "base_ok"], "Descarta cuentas de hace más de 18 meses"
aviso = analisis.avisos_vigilancia(r2, cfg, ["VIEJA"])
assert aviso and "2018" in aviso[0], aviso
print("[OK] Constructoras, petroleras, deuda por partes, inmovilizado que falta y cuentas viejas")

# --- 4. Simulación del pasado (2010-2026)
dias = pd.bdate_range("2010-01-04", "2026-11-06")
cierres = pd.DataFrame({t: 30 * np.exp(np.cumsum(rng.normal(0.0001 + 0.0005 * calidades[t], 0.016, len(dias))))
                        for t in tickers}, index=dias)
cierres["SPY"] = 110 * np.exp(np.cumsum(rng.normal(0.0004, 0.011, len(dias))))
cierres.iloc[:900, 3] = np.nan   # una empresa que sale a bolsa más tarde
inicio = sim.fecha_inicio_sugerida(tablas, True)
print(f"Inicio sugerido: {inicio.date()}")
curva, ops, cobertura, cartera = sim.ejecutar_backtest(
    universo, tablas, acciones, cierres, cierres, {"T07": splits_t07}, "SPY", inicio, dias[-1], 10_000, cfg)
assert curva.index[0].year == 2011, "Con un año previo de datos, debe empezar en 2011"
assert len(cartera.posiciones) <= cfg["cartera"]["num_posiciones"] and cartera.efectivo >= -1e-6
assert ops[ops["tipo"] == "COMPRA"].groupby("fecha").size().max() <= cfg["cartera"]["compras_por_tanda"]
print(ops.groupby("tipo").size().to_dict())

# --- 5. Cartera ficticia hacia delante, informe y panel (descargas sustituidas)
tmp = Path(tempfile.mkdtemp())
sim.CARPETA_CARTERAS = tmp / "carteras"
analisis.RESULTADOS = sim.RESULTADOS = tmp / "resultados"
analisis.HISTORICO = sim.HISTORICO = web.HISTORICO = tmp / "historico"
web.DOCS = tmp / "docs"
sim.descargar_precios = lambda tks, **kw: (cierres[[t for t in tks if t in cierres]].tail(10),) * 2 + ({},)
sim.ranking_actual = lambda cfg: ranking

resumen = sim.guardar_backtest(curva, ops, cobertura, inicio, dias[-1], 10_000, cfg)
assert resumen["curva"] and resumen["final"]["estrategia"] > 0

sim.crear_cartera("principal", 10_000, cfg)
estado, ops_hoy = sim.actualizar_cartera("principal", cfg)
assert len(ops_hoy) == cfg["cartera"]["compras_por_tanda"]
assert sim.actualizar_cartera("principal", cfg)[1] == [], "El mismo día no debe volver a operar"
assert sim.cargar("principal")["historial"][-1]["fecha"] == str(dias[-1].date()), \
    "El historial se fecha con el día de cierre de los precios, no con el de la ejecución"
assert "estilo" not in sim.cargar("principal")["reglas"], "La cartera trimestral no cambia de reglas"

# --- 6. Cartera diaria
from inversor.cartera import Cartera  # noqa: E402

reglas_d = sim.reglas_para(cfg, "diaria")
assert reglas_d["estilo"] == "diaria" and reglas_d["num_posiciones"] == cfg["cartera"]["num_posiciones"]
lista = [f"X{i:02d}" for i in range(80)]
px = {t: 50.0 for t in lista}
c = Cartera(10_000, reglas_d)
ops_d = c._rebalancear_por_ranking(pd.Timestamp("2026-01-05"), lista, px)
assert set(c.posiciones) == set(lista[:20]) and all(o["tipo"] == "COMPRA" for o in ops_d), "Llena el top 20 el primer día"
# Al día siguiente X03 baja al puesto 30 (se queda: dentro del top 50), X05 al 60 (se vende) y X07 deja de ser apta
nueva = [t for t in lista if t not in ("X03", "X05", "X07")]
nueva.insert(29, "X03")
nueva.insert(59, "X05")
ops_d = c._rebalancear_por_ranking(pd.Timestamp("2026-01-06"), nueva, px)
vendidas = {o["ticker"] for o in ops_d if o["tipo"] == "VENTA"}
compradas = [o["ticker"] for o in ops_d if o["tipo"] == "COMPRA"]
assert vendidas == {"X05", "X07"}, vendidas
assert "X03" in c.posiciones and len(c.posiciones) == 20
assert all(nueva.index(t) < 20 for t in compradas) and len(compradas) == 2, compradas
assert c._rebalancear_por_ranking(pd.Timestamp("2026-01-07"), [], px) == [] and len(c.posiciones) == 20, \
    "Sin ranking (fallo de datos) no debe vender nada"
assert c.efectivo >= -1e-6

sim.crear_cartera("diaria", 10_000, cfg, "diaria")
estado_d, ops_d = sim.actualizar_cartera("diaria", cfg)
assert 0 < len(ops_d) <= 20 and sim.actualizar_cartera("diaria", cfg)[1] == []
e = sim.cargar("diaria")
assert sim.proxima_revision(e) is None and not sim.toca_rebalancear(e)
assert sim.toca_rebalancear(e, pd.Timestamp(e["ultimo_rebalanceo"]) + pd.Timedelta(days=1)), "Al día siguiente vuelve a revisar"
assert "cada día de mercado" in sim.describir_cartera(e)
print(f"[OK] Cartera diaria: compra el top 20, vende fuera del top 50 y revisa cada día ({len(ops_d)} compras)")

# --- 7. Cartera semanal: mismas reglas que la diaria, revisión cada 7 días
reglas_s = sim.reglas_para(cfg, "semanal")
assert reglas_s["estilo"] == "semanal" and reglas_s["vender_fuera_del_top"] == cfg["cartera_semanal"]["vender_fuera_del_top"]
c = Cartera(10_000, reglas_s)
assert len(c.rebalancear(pd.Timestamp("2026-01-05"), lista, px)) == 20, "Usa las reglas por ranking"
sim.crear_cartera("semanal", 10_000, cfg, "semanal")
_, ops_s = sim.actualizar_cartera("semanal", cfg)
e = sim.cargar("semanal")
ultimo = pd.Timestamp(e["ultimo_rebalanceo"])
assert 0 < len(ops_s) <= 20 and sim.proxima_revision(e) == ultimo + pd.Timedelta(days=7)
assert not sim.toca_rebalancear(e, ultimo + pd.Timedelta(days=6))
assert sim.toca_rebalancear(e, ultimo + pd.Timedelta(days=7))
assert "Próxima revisión" in sim.describir_cartera(e)
assert sorted(sim.listar_carteras()) == ["diaria", "principal", "semanal"], "Las tres conviven"
print("[OK] Cartera semanal: reglas por ranking y revisión cada 7 días; conviven las tres")
# Simula unas semanas de historial para el gráfico del panel
e = sim.cargar("principal")
base = pd.Timestamp(e["fecha_inicio"])
e["fecha_inicio"] = str((base - pd.Timedelta(days=60)).date())
e["historial"] = [{"fecha": str((base - pd.Timedelta(days=60 - i)).date()),
                   "cartera": round(10_000 * (1 + 0.0009 * i + 0.006 * np.sin(i / 5)), 2),
                   "referencia": round(10_000 * (1 + 0.0006 * i + 0.009 * np.sin(i / 4)), 2)} for i in range(61)]
sim.guardar(e)

(tmp / "historico").mkdir(exist_ok=True)
ranking.to_csv(tmp / "historico" / "ranking_panel.csv")
cfg["alertas"]["mis_acciones"] = ["T05"]
texto = analisis.informe_semanal(ranking, cfg, ["T05"])
assert "F-Score" in texto
ruta = web.generar_panel(cfg)
html = ruta.read_text(encoding="utf-8")
assert "__DATOS__" not in html and '"carteras"' in html and '"filas"' in html
print(f"[OK] Panel generado en {ruta}")

# --- 8. Mensajes de Telegram y datos del bot
import json as _json  # noqa: E402
import re as _re  # noqa: E402


def html_telegram_valido(texto):
    sin = _re.sub(r"</?(b|i)>", "", texto)
    assert "<" not in sin and ">" not in sin, texto[:300]
    assert not _re.search(r"&(?!amp;|lt;|gt;|quot;|#x27;)", sin), "Hay un & sin escapar"
    for t in ("b", "i"):
        assert texto.count(f"<{t}>") == texto.count(f"</{t}>")


estado_d = sim.cargar("diaria")
ops_guardadas = estado_d["cartera"]["operaciones"]
assert all(o.get("explicacion") for o in ops_guardadas), "Cada operación guarda su porqué"
assert all(o["explicacion"].startswith(f"Es la n.º {o['motivo'].split()[-3]} del ranking") for o in ops_guardadas)
ranking_h = ranking.copy()
ranking_h.loc[ranking_h.index[0], "nombre"] = "H&R <Block>"   # caracteres que hay que escapar
info = mensajes.info_empresas(ranking_h, extra=["T05"])
assert info[aptas[0]]["puesto"] == 1 and info["T05"]["puesto"] is None
venta = {"tipo": "VENTA", "ticker": aptas[0], "motivo": "Cae al puesto 64 del ranking (fuera de las 50 mejores)",
         "resultado_pct": -2.5}
assert "puesto 64" in mensajes.razon_operacion(venta, info[aptas[0]]) and "Pierde un 2,5 %" in mensajes.razon_operacion(venta, None)
nov = mensajes.mensaje_novedades([(estado_d, ops_guardadas[:2] + [venta])], info, cfg)
html_telegram_valido(nov)
assert "H&amp;R &lt;Block&gt;" in nov and "🔴" in nov and "Ahora la cartera vale" in nov
estados = [sim.cargar(n) for n in sim.listar_carteras()]
sem = mensajes.mensaje_semanal(estados, ranking_h, cfg, ([aptas[0]], ["T05"]), ["T05: aviso de prueba"])
html_telegram_valido(sem)
assert all(mensajes.titulo_cartera(e) in sem.replace("&amp;", "&") for e in estados) and "⚠️" in sem
assert mensajes.titulo_cartera(sim.cargar("principal")) == "Principal (trimestral)"
assert mensajes.pct(-0.01) == "0,0 %" and mensajes.pct(1234.56) == "+1.234,6 %"

bot = _json.loads((tmp / "docs" / "bot.json").read_text(encoding="utf-8"))
assert {c["nombre"] for c in bot["carteras"]} == {"principal", "diaria", "semanal"}
assert bot["top"][0]["puesto"] == 1 and bot["top"][0]["porque"]
c0 = next(c for c in bot["carteras"] if c["nombre"] == "diaria")
assert c0["posiciones"][0]["porque"] and "Se vendería si baja del puesto 50" in c0["posiciones"][0]["nota"]
assert c0["operaciones"][0]["explicacion"]
p0 = next(c for c in bot["carteras"] if c["nombre"] == "principal")["posiciones"][0]
assert "Se mantiene al menos hasta" in p0["nota"]

# Envío: primero al bot de Cloudflare; si falla, directo a Telegram (y se registra si Telegram lo rechaza)
import os as _os  # noqa: E402


class _Resp:
    def __init__(self, ok, codigo=200, texto=""):
        self.ok, self.status_code, self.text = ok, codigo, texto


enviados = []
analisis.requests.post = lambda url, **kw: enviados.append((url, kw)) or _Resp(True)
_os.environ.update({"BOT_URL": "https://bot.test/", "BOT_SECRET": "clave", "TELEGRAM_TOKEN": "T", "TELEGRAM_CHAT_ID": "1"})
analisis.enviar_alerta(nov)
assert len(enviados) == 1 and enviados[0][0] == "https://bot.test/notificar"
assert enviados[0][1]["headers"]["Authorization"] == "Bearer clave" and enviados[0][1]["json"]["texto"] == nov
enviados.clear()
analisis.requests.post = lambda url, **kw: enviados.append((url, kw)) or _Resp("notificar" not in url, 500, "caído")
analisis.enviar_alerta("\n".join(["línea <b>larga</b>"] * 400))
directos = [e for e in enviados if "api.telegram.org" in e[0]]
assert len(directos) >= 2 and all(e[1]["data"]["parse_mode"] == "HTML" for e in directos), "Si el bot falla, va directo"
assert all(len(e[1]["data"]["text"]) <= 3900 for e in directos)
assert all(e[1]["data"]["text"].count("<b>") == e[1]["data"]["text"].count("</b>") for e in directos)
for k in ("BOT_URL", "BOT_SECRET", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"):
    _os.environ.pop(k)
print("[OK] Mensajes de Telegram claros y válidos, datos del bot y envío con respaldo")

# --- 9. Retrasos de GitHub: el día de mercado y el informe semanal no dependen de la hora de ejecución
T = pd.Timestamp
assert analisis.dia_de_mercado(T("2026-11-23 22:30")) == T("2026-11-23"), "A su hora: lunes"
assert analisis.dia_de_mercado(T("2026-11-24 06:12")) == T("2026-11-23"), "Retrasada al martes de madrugada: sigue siendo lunes"
assert analisis.dia_de_mercado(T("2026-11-21 03:19")) == T("2026-11-20"), "Sábado de madrugada: viernes"
assert analisis.dia_de_mercado(T("2026-11-22 12:00")) == T("2026-11-20"), "Domingo: viernes"
(analisis.HISTORICO / "ultimo_informe.txt").unlink(missing_ok=True)
assert analisis.toca_informe_semanal(0, T("2026-11-21 03:19")), "Si esa semana aún no salió, sale aunque sea viernes"
analisis.marcar_informe_enviado(T("2026-11-21 03:19"))
assert not analisis.toca_informe_semanal(0, T("2026-11-22 12:00")), "El fin de semana cuenta como el viernes ya informado"
assert analisis.toca_informe_semanal(0, T("2026-11-24 06:12")), "El lunes retrasado al martes sí envía el informe"
analisis.marcar_informe_enviado(T("2026-11-24 06:12"))
assert not analisis.toca_informe_semanal(0, T("2026-11-24 23:00")), "Una vez por semana"
assert not analisis.toca_informe_semanal(0, T("2026-11-28 04:00"))
assert analisis.toca_informe_semanal(0, T("2026-12-02 05:00")), "Si el lunes no hubo ejecución, sale el martes"
assert not analisis.toca_informe_semanal(2, T("2026-12-01 05:00")), "Respeta el día elegido (miércoles)"
print("[OK] Retrasos de GitHub: fechas de cierre e informe semanal una vez por semana")

# --- 10. Noticias gratuitas (Google News RSS) y su clasificación
from inversor import noticias as nt  # noqa: E402

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Acme Corp files for Chapter 11 bankruptcy - Reuters</title><source>Reuters</source>
<pubDate>Wed, 25 Nov 2026 10:00:00 GMT</pubDate><link>https://x/1</link></item>
<item><title>Acme cuts full-year guidance as demand slows - Bloomberg</title><source>Bloomberg</source>
<pubDate>Tue, 24 Nov 2026 10:00:00 GMT</pubDate><link>https://x/2</link></item>
<item><title>Halper Sadeh LLC Investigates Acme Corp - PR Newswire</title><source>PR Newswire</source>
<pubDate>Tue, 24 Nov 2026 09:00:00 GMT</pubDate><link>https://x/3</link></item>
<item><title>Other company beats estimates - CNBC</title><source>CNBC</source>
<pubDate>Tue, 24 Nov 2026 09:00:00 GMT</pubDate><link>https://x/4</link></item>
<item><title>ACME stock old news - Old</title><source>Old</source>
<pubDate>Mon, 02 Nov 2026 09:00:00 GMT</pubDate><link>https://x/5</link></item>
</channel></rss>"""
items = nt.leer_rss(RSS)
assert items[0]["titulo"] == "Acme Corp files for Chapter 11 bankruptcy" and items[0]["fuente"] == "Reuters"
assert nt.leer_rss("no es xml") == []
r = nt.resumir(items, "ACME", "Acme Corp, Inc.", ahora="2026-11-26 12:00")
assert r["total"] == 3, "Solo titulares recientes que nombran a la empresa"
assert r["cuenta"]["grave"] == 1 and r["cuenta"]["negativa"] == 1 and r["cuenta"]["neutra"] == 1
assert r["grave_reciente"]["titulo"].startswith("Acme Corp files") and r["destacados"][0]["tono"] == "grave"
assert nt.resumir(items, "ACME", "Acme Corp", ahora="2026-11-30 12:00")["grave_reciente"] is None, "Grave solo si es de 3 días"
for titulo, tono in [("XYZ shares plunge after earnings", "negativa"), ("XYZ beats estimates and raises outlook", "positiva"),
                     ("SEC probe into XYZ accounting", "grave"), ("XYZ hits 52-week low", "negativa"),
                     ("Shareholder alert: law firm investigates XYZ", "neutra"), ("XYZ announces new product", "neutra")]:
    assert nt.clasificar(titulo) == tono, (titulo, nt.clasificar(titulo))
assert nt.nombre_corto("PTC Therapeutics, Inc.") == "PTC Therapeutics" and nt.nombre_corto("H&R Block") == "H&R Block"
print("[OK] Noticias: lectura del RSS, filtro por empresa y clasificación grave / negativa / positiva / ruido")

# --- 11. Cartera reactiva: protecciones, filtros de compra y modo prudente
reglas_r = sim.reglas_para(cfg, "reactiva")
assert reglas_r["estilo"] == "reactiva" and reglas_r["stop_movil_pct"] == cfg["cartera_reactiva"]["stop_movil_pct"]
ctx_ok = {"indice": {"sobre_media": True}, "cambio_dia": {"X01": -9.0}, "cambio_5d": {},
          "noticias": {"X02": {"cuenta": {"grave": 1}, "grave_reciente": {"titulo": "X02 fraud"}},
                       "X03": {"cuenta": {"negativa": 2, "positiva": 0}}}}
c = Cartera(10_000, reglas_r)
ops_r = c.rebalancear(pd.Timestamp("2026-01-05"), lista, px, ctx_ok)
compradas = {o["ticker"] for o in ops_r if o["tipo"] == "COMPRA"}
assert not compradas & {"X01", "X02", "X03"}, "No compra lo que se desploma hoy ni lo que tiene malas noticias"
assert len(compradas) == 17, f"Compra el resto del top 20 ({len(compradas)})"
# Stop móvil: X00 sube a 60 (nuevo máximo) y luego cae a 50 → −16,7 % desde el máximo
c.actualizar_precios({**px, "X00": 60.0})
ops_v = c.vigilar(pd.Timestamp("2026-01-06"), {**px, "X00": 50.0}, {})
assert [o["ticker"] for o in ops_v] == ["X00"] and "Stop móvil" in ops_v[0]["motivo"]
assert c.vetadas["X00"] == "2026-02-05", "No se recompra en 30 días"
assert "stop móvil" in mensajes.razon_operacion(ops_v[0], None)
# Noticia grave: solo vende si el mercado ya la castiga (−5 % en 5 sesiones)
grave = {"noticias": {"X04": {"grave_reciente": {"titulo": "X04 under SEC investigation"}}}}
assert c.vigilar(pd.Timestamp("2026-01-06"), px, {**grave, "cambio_5d": {"X04": -2.0}}) == []
ops_g = c.vigilar(pd.Timestamp("2026-01-06"), px, {**grave, "cambio_5d": {"X04": -6.0}})
assert [o["ticker"] for o in ops_g] == ["X04"] and "noticia grave" in mensajes.razon_operacion(ops_g[0], None)
# Vetada: aunque vuelva al top 20, no se recompra hasta que pase el plazo
ops_r = c.rebalancear(pd.Timestamp("2026-01-07"), lista, px, {"indice": {"sobre_media": True}})
assert "X00" not in {o["ticker"] for o in ops_r if o["tipo"] == "COMPRA"}
assert c.a_dict()["vetadas"]["X00"] and Cartera.desde_dict(c.a_dict(), reglas_r).vetadas == c.vetadas
c.rebalancear(pd.Timestamp("2026-03-01"), lista, px, {"indice": {"sobre_media": True}})
assert "X00" not in c.vetadas, "Los vetos caducan"
# Modo prudente: con el índice bajo su media de 200 sesiones no compra, pero sí vende
c2 = Cartera(10_000, reglas_r)
assert c2.rebalancear(pd.Timestamp("2026-01-05"), lista, px, {"indice": {"sobre_media": False}}) == []
c.posiciones["X79"] = {"acciones": 1, "precio_compra": 50.0, "fecha_compra": "2026-01-05", "inicio_periodo": "2026-01-05",
                       "ultimo_precio": 50.0, "maximo": 50.0}
ventas = [o for o in c.rebalancear(pd.Timestamp("2026-03-02"), lista, px, {"indice": {"sobre_media": False}}) if o["tipo"] == "VENTA"]
assert [o["ticker"] for o in ventas] == ["X79"], "En modo prudente sigue vendiendo lo que cae del top 50"
assert c.efectivo >= -1e-6

# Integración: cartera reactiva hacia delante y vigilancia que solo guarda si vende
sim.crear_cartera("reactiva", 10_000, cfg, "reactiva")
ctx_vacio = {"indice": {"sobre_media": True}, "cambio_dia": {}, "cambio_5d": {}, "noticias": {}}
_, ops_ra = sim.actualizar_cartera("reactiva", cfg, None, ctx_vacio)
e = sim.cargar("reactiva")
assert 0 < len(ops_ra) <= 20 and sim.es_reactiva(e) and sim.es_diaria(e) and sim.proxima_revision(e) is None
antes = (sim.CARPETA_CARTERAS / "reactiva.json").read_text(encoding="utf-8")
precios_e = {t: p["ultimo_precio"] for t, p in e["cartera"]["posiciones"].items()}
assert sim.vigilar_cartera("reactiva", {"precios": precios_e, "cambio_5d": {}, "noticias": {}}) == []
assert (sim.CARPETA_CARTERAS / "reactiva.json").read_text(encoding="utf-8") == antes, "Sin ventas no se guarda nada"
victima = next(iter(precios_e))
ops_vc = sim.vigilar_cartera("reactiva", {"precios": {**precios_e, victima: precios_e[victima] * 0.5}, "cambio_5d": {}, "noticias": {}})
assert [o["ticker"] for o in ops_vc] == [victima] and victima not in sim.cargar("reactiva")["cartera"]["posiciones"]
assert sim.cargar("reactiva")["cartera"]["operaciones"][-1]["explicacion"]
assert sim.vigilar_cartera("principal", {"precios": {}, "cambio_5d": {}, "noticias": {}}) == [], "Solo vigila la reactiva"
nota = mensajes.nota_posicion(next(iter(e["cartera"]["posiciones"].values())), e, {"puesto": 3})
assert "stop móvil" in nota and "noticia grave" in nota
# Splits: tras un 8 por 1 las acciones se multiplican y los precios se dividen, sin falsas caídas ni ventas
c3 = Cartera(10_000, reglas_r)
c3.posiciones["SPL"] = {"acciones": 6, "precio_compra": 640.0, "fecha_compra": "2026-11-10", "inicio_periodo": "2026-11-10",
                        "ultimo_precio": 700.0, "maximo": 720.0}
valor_antes = c3.valor({"SPL": 700.0})
serie = pd.Series([8.0, 2.0], index=[pd.Timestamp("2026-11-10"), pd.Timestamp("2026-11-20")])  # el del día de compra no cuenta
assert c3.aplicar_splits({"SPL": serie}) == ["SPL: split 2 por 1 el 2026-11-20"]
pos = c3.posiciones["SPL"]
assert pos["acciones"] == 12 and pos["precio_compra"] == 320.0 and pos["maximo"] == 360.0
assert abs(c3.valor({"SPL": 350.0}) - valor_antes) < 1e-6, "El valor no cambia por el split"
assert c3.aplicar_splits({"SPL": serie}) == [], "Cada split se aplica una sola vez"
assert c3.vigilar(pd.Timestamp("2026-11-21"), {"SPL": 350.0}, {}) == [], "Sin falsa caída tras el split"
ctx_split = {"precios": {}, "cambio_5d": {}, "noticias": {}, "splits": {}}
e_r = sim.cargar("reactiva")
t_r = next(iter(e_r["cartera"]["posiciones"]))
e_r["cartera"]["posiciones"][t_r]["fecha_compra"] = "2026-01-01"
sim.guardar(e_r)
precio_r = e_r["cartera"]["posiciones"][t_r]["ultimo_precio"]
ctx_split = {"precios": {t: p["ultimo_precio"] for t, p in e_r["cartera"]["posiciones"].items()} | {t_r: precio_r / 4},
             "cambio_5d": {}, "noticias": {}, "splits": {t_r: pd.Series([4.0], index=[pd.Timestamp("2026-02-01")])}}
assert sim.vigilar_cartera("reactiva", ctx_split) == [], "Un split no dispara el stop móvil"
assert sim.cargar("reactiva")["cartera"]["posiciones"][t_r]["splits"] == ["2026-02-01"], "Y se guarda el ajuste"
# Precio atrasado (Yahoo dio SNDK hasta el 19/11 y el resto hasta el 25/11): no cuenta como precio actual
tabla = pd.DataFrame({"BIEN": [10.0, 11.0, 12.0], "VIEJO": [94.0, None, None]},
                     index=pd.to_datetime(["2026-11-19", "2026-11-24", "2026-11-25"]))
assert sim.precios_al_dia(tabla) == {"BIEN": 12.0}, "Un precio atrasado no se usa"
print("[OK] Cartera reactiva: stop móvil, noticias graves, filtros de compra, vetos, modo prudente, vigilancia y splits")

# --- 12. Parte diario
estados_p = [sim.cargar(n) for n in sim.listar_carteras()]
ctx_p = {"fecha_precios": pd.Timestamp("2026-11-25"), "indice": {"cambio_dia": 0.42, "sobre_media": True},
         "noticias": {t: nt.resumir(items, t, "Acme Corp", ahora="2026-11-26 12:00")
                      for t in list(sim.cargar("reactiva")["cartera"]["posiciones"])[:2]},
         "macro": [{"titulo": "La Fed & los tipos <hoy>", "fuente": "El País", "tema": "Tipos"}]}
parte = mensajes.mensaje_parte_diario([(e, ops_vc if e["nombre"] == "reactiva" else []) for e in estados_p], ctx_p, cfg,
                                      mensajes.info_empresas(ranking))
html_telegram_valido(parte)
assert "Parte del miércoles 25/11" in parte and "+0,4 % hoy" in parte and "tendencia de fondo alcista" in parte
assert "Reactiva" in parte and "🔴 <b>Vende</b>" in parte and "Noticias de tus empresas" in parte
assert "La Fed &amp; los tipos &lt;hoy&gt;" in parte
sin_nada = mensajes.mensaje_parte_diario([(e, []) for e in estados_p], {"fecha_precios": T("2026-11-25")}, cfg, {})
html_telegram_valido(sin_nada)
assert "ninguna cartera ha comprado ni vendido" in sin_nada
(analisis.HISTORICO / "ultimo_parte.txt").unlink(missing_ok=True)
assert not analisis.parte_ya_enviado(T("2026-11-25"))
analisis.marcar_parte_enviado(T("2026-11-25"))
assert analisis.parte_ya_enviado(T("2026-11-25")) and not analisis.parte_ya_enviado(T("2026-11-27")), "Un parte por sesión"
analisis.guardar_contexto(ctx_p)
web.generar_panel(cfg)
bot = _json.loads((tmp / "docs" / "bot.json").read_text(encoding="utf-8"))
assert bot["mercado"]["sobre_media"] is True and bot["macro"][0]["titulo"].startswith("La Fed")
reac = next(c for c in bot["carteras"] if c["nombre"] == "reactiva")
assert reac["titulo"] == "Reactiva" and any(p["noticias"] for p in reac["posiciones"])
print("[OK] Parte diario: mercado, carteras, movimientos, noticias y geopolítica; una vez por sesión")
print("\nTODAS LAS PRUEBAS PASAN ✅")
print(f"CARPETA_PANEL={ruta.parent}")
