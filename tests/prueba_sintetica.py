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

from inversor import analisis, simulacion as sim, web  # noqa: E402
from inversor.puntuacion import elegibles, evaluar, ordenar  # noqa: E402
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
ranking = ordenar(evaluar(universo, tablas, caps), cfg["capitalizacion_minima"])
aptas = elegibles(ranking, cfg["fscore_minimo"])
ranking["apto"] = ranking.index.isin(aptas)
assert ranking["base_ok"].sum() >= 45 and "T05" not in aptas
print(f"[OK] Ranking: {int(ranking['base_ok'].sum())} puntuadas, {len(aptas)} aptas. Top 5: {aptas[:5]}")

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
assert "estilo" not in sim.cargar("principal")["reglas"], "La cartera trimestral no cambia de reglas"

# --- 6. Cartera diaria
from inversor.cartera import Cartera  # noqa: E402

reglas_d = sim.reglas_para(cfg, "diaria")
assert reglas_d["estilo"] == "diaria" and reglas_d["num_posiciones"] == cfg["cartera"]["num_posiciones"]
lista = [f"X{i:02d}" for i in range(80)]
px = {t: 50.0 for t in lista}
c = Cartera(10_000, reglas_d)
ops_d = c._rebalancear_diario(pd.Timestamp("2026-01-05"), lista, px)
assert set(c.posiciones) == set(lista[:20]) and all(o["tipo"] == "COMPRA" for o in ops_d), "Llena el top 20 el primer día"
# Al día siguiente X03 baja al puesto 30 (se queda: dentro del top 50), X05 al 60 (se vende) y X07 deja de ser apta
nueva = [t for t in lista if t not in ("X03", "X05", "X07")]
nueva.insert(29, "X03")
nueva.insert(59, "X05")
ops_d = c._rebalancear_diario(pd.Timestamp("2026-01-06"), nueva, px)
vendidas = {o["ticker"] for o in ops_d if o["tipo"] == "VENTA"}
compradas = [o["ticker"] for o in ops_d if o["tipo"] == "COMPRA"]
assert vendidas == {"X05", "X07"}, vendidas
assert "X03" in c.posiciones and len(c.posiciones) == 20
assert all(nueva.index(t) < 20 for t in compradas) and len(compradas) == 2, compradas
assert c._rebalancear_diario(pd.Timestamp("2026-01-07"), [], px) == [] and len(c.posiciones) == 20, \
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
print("\nTODAS LAS PRUEBAS PASAN ✅")
print(f"CARPETA_PANEL={ruta.parent}")
