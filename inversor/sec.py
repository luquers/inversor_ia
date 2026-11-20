"""Estados financieros oficiales de la SEC (EDGAR, formato XBRL).

Cada cifra viene con la fecha exacta en que se publicó. Así, al simular el pasado,
solo se usa lo que realmente se sabía en cada momento.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date

import numpy as np
import pandas as pd

FORMULARIOS_ANUALES = {"10-K", "10-K/A", "10-KT", "10-KT/A"}

# Súbelo cuando cambien CONCEPTOS: obliga a volver a leer las cuentas guardadas en caché
VERSION_COMPACTO = 2

# Para cada dato, los nombres que usan las empresas (en orden de preferencia)
CONCEPTOS = {
    # --- cuenta de resultados y flujos (periodos de un año)
    "ebit": ["OperatingIncomeLoss",
             "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
             "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
             # Algunas empresas solo con negocio en EE. UU. (p. ej. constructoras) usan esta
             "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic"],
    "ingresos": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                 "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet", "SalesRevenueGoodsNet"],
    "beneficio_bruto": ["GrossProfit"],
    "coste_ventas": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
    "beneficio_neto": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "flujo_operativo": ["NetCashProvidedByUsedInOperatingActivities",
                        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "acciones": ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic"],
    # --- balance (foto al cierre del ejercicio)
    "activos_totales": ["Assets"],
    "activo_corriente": ["AssetsCurrent"],
    "pasivo_corriente": ["LiabilitiesCurrent"],
    "deuda_lp": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "LongTermDebt"],
    # Partes de la deuda que algunas empresas publican por separado en lugar del total anterior.
    # Solo se suman si falta deuda_lp, para no contar dos veces lo mismo.
    "deuda_convertible": ["ConvertibleLongTermNotesPayable", "ConvertibleNotesPayable"],
    "prestamos_lp": ["LongTermLoansPayable", "SeniorLongTermNotes", "SeniorNotes"],
    "pagares": ["NotesAndLoansPayable", "NotesPayable"],   # típico de constructoras: el total sin dividir
    "deuda_cp_total": ["DebtCurrent"],
    "deuda_lp_corriente": ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent",
                           "LoansPayableCurrent", "ConvertibleNotesPayableCurrent"],
    "prestamos_cp": ["ShortTermBorrowings", "CommercialPaper"],
    "efectivo": ["CashAndCashEquivalentsAtCarryingValue",
                 "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash"],
    "inversiones_cp": ["ShortTermInvestments", "MarketableSecuritiesCurrent",
                       "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "inmovilizado_neto": ["PropertyPlantAndEquipmentNet",
                          "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization"],
    # Petroleras: los pozos y yacimientos se publican aparte del resto del inmovilizado
    "inmovilizado_petroleo": ["CapitalizedCostsOilAndGasProducingActivitiesNet",
                              "OilAndGasPropertySuccessfulEffortMethodNet", "OilAndGasPropertyFullCostMethodNet"],
    # Para estimar el circulante cuando el balance no separa corriente y no corriente (constructoras)
    "existencias": ["InventoryNet", "InventoryRealEstate", "InventoryOperativeBuilders"],
    "clientes": ["AccountsReceivableNetCurrent", "AccountsAndNotesReceivableNet", "AccountsReceivableNet",
                 "ReceivablesNetCurrent"],
    "proveedores": ["AccountsPayableCurrent", "AccountsPayableCurrentAndNoncurrent",
                    "AccountsPayableAndAccruedLiabilitiesCurrent"],
}
DE_PERIODO = {"ebit", "ingresos", "beneficio_bruto", "coste_ventas", "beneficio_neto", "flujo_operativo", "acciones"}
CAMPOS_BRUTOS = list(CONCEPTOS)


def _dias(inicio, fin):
    return (date.fromisoformat(fin) - date.fromisoformat(inicio)).days


def compactar(companyfacts: dict) -> dict:
    """Reduce el JSON de la SEC (varios MB) a lo que necesitamos (unos KB).

    Para cada dato y cada cierre de ejercicio se guarda la PRIMERA vez que se publicó
    (valor original, sin las correcciones posteriores que no se conocían entonces).
    """
    gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    campos = {}
    for campo, conceptos in CONCEPTOS.items():
        unidad = "shares" if campo == "acciones" else "USD"
        mejor = {}  # fin de periodo -> ((fecha_publicacion, prioridad), valor)
        for prioridad, concepto in enumerate(conceptos):
            for r in gaap.get(concepto, {}).get("units", {}).get(unidad, []):
                if r.get("form") not in FORMULARIOS_ANUALES or "end" not in r or "filed" not in r:
                    continue
                es_periodo = "start" in r
                if es_periodo != (campo in DE_PERIODO):
                    continue
                if es_periodo and not 350 <= _dias(r["start"], r["end"]) <= 380:
                    continue
                clave = (r["filed"], prioridad)
                if r["end"] not in mejor or clave < mejor[r["end"]][0]:
                    mejor[r["end"]] = (clave, r["val"])
        campos[campo] = {fin: (clave[0], valor) for fin, (clave, valor) in mejor.items()}

    # Acciones en circulación a lo largo del tiempo (portada de cada 10-K y 10-Q)
    historial = {}
    portada = (companyfacts.get("facts", {}).get("dei", {})
               .get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares", []))
    for r in portada:
        previo = historial.get(r["accn"])
        if previo is None or r["end"] > previo[1]:
            historial[r["accn"]] = (r["filed"], r["end"], float(r["val"]))
    if len(historial) < 2:
        # Empresas con varias clases de acciones no siempre lo publican en la portada;
        # se usa entonces el promedio diluido de cada trimestre/año
        historial = {}
        for concepto in CONCEPTOS["acciones"]:
            for r in gaap.get(concepto, {}).get("units", {}).get("shares", []):
                previo = historial.get(r["end"])
                if previo is None or r["filed"] < previo[0]:
                    historial[r["end"]] = (r["filed"], r["end"], float(r["val"]))
            if historial:
                break
    return {
        "version": VERSION_COMPACTO,
        "nombre": companyfacts.get("entityName", ""),
        "campos": campos,
        "acciones_hist": sorted(historial.values()),
    }


def tabla_anual(compacto: dict) -> pd.DataFrame:
    """Una fila por ejercicio. Columnas: cada dato y su fecha de publicación (pub_<dato>)."""
    campos = compacto.get("campos", {})
    cierres = set()
    for campo in ("ebit", "ingresos", "beneficio_neto", "flujo_operativo"):
        cierres |= set(campos.get(campo, {}))
    if not cierres:
        return pd.DataFrame()
    filas = []
    for fin in sorted(cierres):
        fila = {"cierre": pd.Timestamp(fin)}
        for campo in CAMPOS_BRUTOS:
            dato = campos.get(campo, {}).get(fin)
            fila[campo] = float(dato[1]) if dato else np.nan
            fila[f"pub_{campo}"] = pd.Timestamp(dato[0]) if dato else pd.NaT
        filas.append(fila)
    return pd.DataFrame(filas).set_index("cierre")


def vista(tabla: pd.DataFrame, fecha=None) -> pd.DataFrame:
    """Lo que se sabía en `fecha` (o todo, si no se indica) y los datos derivados."""
    t = tabla[CAMPOS_BRUTOS].copy()
    if fecha is not None:
        fecha = pd.Timestamp(fecha)
        for campo in CAMPOS_BRUTOS:
            pub = tabla[f"pub_{campo}"]
            t.loc[~(pub <= fecha), campo] = np.nan
    t = t.dropna(how="all")
    cero = lambda col: t[col].fillna(0.0)  # noqa: E731

    # Beneficio bruto: si no lo publican, ingresos menos coste de ventas
    t["beneficio_bruto"] = t["beneficio_bruto"].fillna(t["ingresos"] - t["coste_ventas"])
    deuda_cp = t["deuda_cp_total"].fillna(cero("deuda_lp_corriente") + cero("prestamos_cp"))
    partes_deuda = t[["deuda_convertible", "prestamos_lp", "pagares"]]
    suma_partes = partes_deuda.sum(axis=1, min_count=1)
    t["deuda_lp"] = t["deuda_lp"].fillna(suma_partes).fillna(0.0)
    t["deuda_total"] = t["deuda_lp"] + deuda_cp
    t["caja"] = cero("efectivo") + cero("inversiones_cp")

    # Inmovilizado: si un año no se publica, se usa el del año anterior (mejor que suponer cero)
    inmov = t["inmovilizado_neto"].ffill(limit=1)
    petroleo = t["inmovilizado_petroleo"].ffill(limit=1)
    # Si los yacimientos superan al inmovilizado publicado, este no los incluía: se suman
    aparte = petroleo.notna() & (petroleo > inmov.fillna(0.0))
    t["inmovilizado_neto"] = inmov.fillna(0.0) + petroleo.where(aparte, 0.0).fillna(0.0)

    # Circulante operativo. Si el balance no separa corriente/no corriente, se estima
    # con existencias + clientes - proveedores; si tampoco hay eso, queda desconocido (NaN).
    circulante = (t["activo_corriente"] - t["caja"]) - t["pasivo_corriente"]
    hay_partes = t["existencias"].notna() | t["clientes"].notna()
    estimado = (cero("existencias") + cero("clientes") - cero("proveedores")).where(hay_partes)
    t["capital_circulante"] = circulante.fillna(estimado)
    return t


def fecha_publicacion(tabla: pd.DataFrame, cierre) -> pd.Timestamp:
    return tabla.loc[cierre, "pub_ebit"]


# ---------------------------------------------------------------- capitalización
def factor_splits(splits: pd.Series | None, desde) -> float:
    """Cuánto se multiplicó el número de acciones por splits ocurridos después de `desde`."""
    if splits is None or splits.empty:
        return 1.0
    posteriores = splits[splits.index > pd.Timestamp(desde)]
    return float(np.prod(posteriores.values)) if len(posteriores) else 1.0


class HistorialAcciones:
    """Acciones en circulación conocidas en cada fecha, para calcular el tamaño de la empresa."""

    def __init__(self, registros):
        self.registros = [(pd.Timestamp(f), pd.Timestamp(e), v) for f, e, v in registros]
        self.publicados = [r[0] for r in self.registros]

    def en(self, fecha=None):
        if not self.registros:
            return None
        if fecha is None:
            return self.registros[-1]
        i = bisect_right(self.publicados, pd.Timestamp(fecha))
        return self.registros[i - 1] if i else None

    def capitalizacion(self, precio, splits=None, fecha=None):
        """Acciones × precio. Los precios de Yahoo ya vienen ajustados por splits,
        así que las acciones se ajustan igual."""
        dato = self.en(fecha)
        if dato is None or precio is None or pd.isna(precio) or precio <= 0:
            return None
        _, a_fecha_de, acciones = dato
        return acciones * factor_splits(splits, a_fecha_de) * float(precio)
