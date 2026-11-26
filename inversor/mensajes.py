"""Mensajes para Telegram en lenguaje sencillo (formato HTML de Telegram).

La idea: que alguien sin conocimientos de bolsa entienda qué ha pasado y por qué.
"""
from __future__ import annotations

import re
from html import escape as _escape

import pandas as pd


def escape(texto):
    """Escapa &, < y > para el HTML de Telegram (las comillas no hace falta escaparlas)."""
    return _escape(str(texto), quote=False)


ESTILOS = {
    "trimestral": ("Trimestral", "revisa cada 3 meses y mantiene cada empresa un año"),
    "semanal": ("Semanal", "revisa cada semana según el ranking"),
    "diaria": ("Diaria", "revisa cada día según el ranking"),
    "reactiva": ("Reactiva", "vigila el mercado y las noticias varias veces al día y se protege de las caídas"),
}
NOMBRES_REFERENCIA = {"SPY": "el S&P 500", "VOO": "el S&P 500", "IVV": "el S&P 500", "QQQ": "el Nasdaq 100"}


# ---------------------------------------------------------------- formato
def num(x, decimales=0):
    texto = f"{x:,.{decimales}f}"
    return texto.replace(",", "·").replace(".", ",").replace("·", ".")


def dinero(x):
    return f"{num(x)} $"


def pct(x):
    r = round(x, 1)
    signo = "+" if r > 0 else "−" if r < 0 else ""
    return f"{signo}{num(abs(r), 1)} %"


def fecha_corta(texto):
    f = pd.Timestamp(texto)
    return f"{f.day}/{f.month}"


def fecha_larga(texto):
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
             "septiembre", "octubre", "noviembre", "diciembre"]
    f = pd.Timestamp(texto)
    return f"{f.day} de {meses[f.month - 1]} de {f.year}"


def estilo(estado):
    return estado["reglas"].get("estilo", "trimestral")


def titulo_cartera(estado):
    nombre_estilo = ESTILOS[estilo(estado)][0]
    nombre = estado["nombre"].capitalize()
    return nombre if nombre.lower() == nombre_estilo.lower() else f"{nombre} ({nombre_estilo.lower()})"


def nombre_referencia(cfg_o_ticker):
    ref = cfg_o_ticker["referencia"] if isinstance(cfg_o_ticker, dict) else cfg_o_ticker
    return NOMBRES_REFERENCIA.get(ref, ref)


# ---------------------------------------------------------------- empresas
def info_empresas(ranking: pd.DataFrame | None, extra=(), top=50) -> dict:
    """Datos de las mejores empresas (y de las indicadas en `extra`) para explicarlas.
    `puesto` es la posición entre las aptas, la misma que usan las carteras."""
    if ranking is None or ranking.empty:
        return {}
    aptos = ranking[ranking["apto"].fillna(False).astype(bool)] if "apto" in ranking else ranking.iloc[0:0]
    puesto = {t: i for i, t in enumerate(aptos.index, 1)}
    quiero = set(list(aptos.index[:top])) | set(extra)
    info = {}
    for t in quiero:
        if t not in ranking.index:
            continue
        f = ranking.loc[t]
        valor = lambda col: None if col not in f or pd.isna(f[col]) else float(f[col])  # noqa: E731
        info[t] = {
            "nombre": f["nombre"] if isinstance(f.get("nombre"), str) else "",
            "puesto": puesto.get(t),
            "barata": None if valor("rend_beneficios") is None else round(valor("rend_beneficios") * 100, 1),
            "rentable": None if valor("rend_capital") is None else round(valor("rend_capital") * 100),
            "fscore": None if valor("fscore") is None else int(valor("fscore")),
        }
    return info


def explicar_empresa(e: dict | None, fscore_minimo=5) -> str:
    """Por qué el método la considera buena, en una frase."""
    if not e:
        return ""
    partes = []
    if e.get("barata") is not None:
        partes.append(f"genera {num(e['barata'])} $ de beneficio al año por cada 100 $ que vale la empresa")
    if e.get("rentable") is not None:
        if e["rentable"] >= 300:
            partes.append("necesita muy poco capital para ganar ese dinero")
        else:
            partes.append(f"gana {num(e['rentable'])} $ al año por cada 100 $ de capital del negocio")
    f = e.get("fscore")
    if f is not None:
        calidad = "buena" if f >= 7 else "aceptable" if f >= fscore_minimo else "débil"
        partes.append(f"su salud financiera es {calidad} ({f}/9)")
    if not partes:
        return ""
    frase = ", ".join(partes[:-1]) + (" y " if len(partes) > 1 else "") + partes[-1]
    return frase[0].upper() + frase[1:] + "."


def razon_operacion(op: dict, e: dict | None, fscore_minimo=5) -> str:
    """Explica una compra, venta o renovación en lenguaje sencillo."""
    motivo = op.get("motivo") or ""
    if op["tipo"] == "COMPRA":
        m = re.search(r"puesto (\d+)", motivo, re.IGNORECASE)
        inicio = f"Es la n.º {m.group(1)} del ranking." if m else "Está entre las mejores del ranking."
        return f"{inicio} {explicar_empresa(e, fscore_minimo)}".strip()
    if op["tipo"] == "MANTENER":
        return "Cumple un año en la cartera, pero sigue entre las mejores, así que se queda otro año."
    m = re.search(r"puesto (\d+).*?(\d+) mejores", motivo)
    stop = re.match(r"Stop móvil: cae un (\d+) % desde su máximo de ([\d.]+)", motivo)
    grave = re.match(r"Noticia grave y caída del (\d+) % en 5 sesiones: «(.*)»", motivo)
    if stop:
        texto = (f"Ha caído un {stop.group(1)} % desde el máximo que alcanzó en la cartera "
                 f"({num(float(stop.group(2)), 2)} $), y salta la protección (stop móvil): se vende para limitar pérdidas.")
    elif grave:
        texto = (f"Ha salido una noticia grave («{grave.group(2)}») y la acción ya cae un {grave.group(1)} % "
                 "en 5 sesiones: se vende por precaución.")
    elif m:
        texto = (f"Ha bajado al puesto {m.group(1)} del ranking: ya no está entre las {m.group(2)} mejores, "
                 "así que deja su sitio a otras más atractivas.")
    elif motivo.startswith("Ya no pasa el filtro"):
        texto = "Su salud financiera ha empeorado o faltan cuentas recientes, así que se vende por precaución."
    elif motivo.startswith("Cumplido el periodo"):
        texto = "Ha cumplido el año que marca el método y ya no está entre las mejores."
    else:
        texto = motivo
    if op.get("resultado_pct") is not None:
        resultado = op["resultado_pct"]
        texto += f" {'Gana' if resultado >= 0 else 'Pierde'} un {num(abs(resultado), 1)} % desde que se compró."
    return texto


def nota_posicion(pos: dict, estado: dict, e: dict | None) -> str:
    """Qué tiene que pasar para que se venda."""
    reglas = estado["reglas"]
    puesto = (e or {}).get("puesto")
    ahora = f"Ahora es la n.º {puesto} del ranking. " if puesto else ""
    if estilo(estado) == "trimestral":
        hasta = pd.Timestamp(pos.get("inicio_periodo", pos["fecha_compra"])) + pd.Timedelta(days=reglas["mantener_dias"])
        return f"{ahora}Se mantiene al menos hasta el {fecha_larga(hasta)}."
    limite = max(reglas.get("vender_fuera_del_top", 50), reglas["num_posiciones"])
    if estilo(estado) == "reactiva":
        stop = pos.get("maximo", pos["precio_compra"]) * (1 - reglas.get("stop_movil_pct", 15) / 100)
        extra = f"si cae por debajo de {num(stop, 2)} $ (stop móvil) o ante una noticia grave"
        return f"{ahora}Se vendería si baja del puesto {limite}, {extra}." if puesto else \
            f"Ha salido del ranking: se venderá en la próxima revisión, o antes {extra}."
    if puesto:
        return f"{ahora}Se vendería si baja del puesto {limite}."
    return "Ha salido del ranking: se venderá en la próxima revisión."


# ---------------------------------------------------------------- resúmenes
def _valor_actual(estado):
    ultimo = estado["historial"][-1] if estado["historial"] else None
    if not ultimo:
        return estado["capital_inicial"], estado["capital_inicial"]
    return ultimo["cartera"], ultimo["referencia"]


def linea_resultado(estado, ref_nombre):
    valor, valor_ref = _valor_actual(estado)
    r = (valor / estado["capital_inicial"] - 1) * 100
    rr = (valor_ref / estado["capital_inicial"] - 1) * 100
    return r, rr, f"vale {dinero(valor)} ({pct(r)}); {ref_nombre}, {pct(rr)}"


def mensaje_novedades(items, info: dict, cfg: dict, max_ops=8) -> str:
    """Aviso de compras y ventas del día. `items`: lista de (estado, operaciones)."""
    ref = escape(nombre_referencia(cfg))
    hoy = fecha_corta(pd.Timestamp.today())
    partes = [f"🔔 <b>Movimientos del {hoy}</b>"]
    iconos = {"COMPRA": "🟢 <b>Compra</b>", "VENTA": "🔴 <b>Vende</b>", "MANTENER": "🔵 <b>Mantiene</b>"}
    for estado, ops in items:
        partes += ["", f"💼 <b>{escape(titulo_cartera(estado))}</b> · {ESTILOS[estilo(estado)][1]}"]
        for op in ops[:max_ops]:
            e = info.get(op["ticker"])
            nombre = f" · {escape(e['nombre'])}" if e and e.get("nombre") else ""
            razon = op.get("explicacion") or razon_operacion(op, e, cfg["fscore_minimo"])
            partes.append(f"{iconos.get(op['tipo'], op['tipo'])} {escape(op['ticker'])}{nombre}")
            partes.append(f"<i>{escape(razon)}</i>")
        if len(ops) > max_ops:
            partes.append(f"…y {len(ops) - max_ops} movimientos más (míralos en el menú del bot).")
        partes.append(f"Ahora la cartera {linea_resultado(estado, ref)[2]}.")
    return "\n".join(partes)


def _cambio_del_dia(estado):
    h = estado["historial"]
    if len(h) < 2:
        return None
    return (h[-1]["cartera"] / h[-2]["cartera"] - 1) * 100


def linea_noticia(t, h):
    from .noticias import TONOS
    fuente = f" ({escape(h['fuente'])})" if h.get("fuente") else ""
    return f"{TONOS[h['tono']]} <b>{escape(t)}</b>: {escape(h['titulo'])}{fuente}"


def mensaje_parte_diario(items, ctx: dict, cfg: dict, info: dict, max_ops=6, max_noticias=6) -> str:
    """Parte de cada día de mercado: índice, carteras, movimientos, noticias de tus empresas y geopolítica.
    `items`: lista de (estado, operaciones de hoy)."""
    ref = escape(nombre_referencia(cfg))
    fecha = ctx.get("fecha_precios") or pd.Timestamp.today()
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    partes = [f"📅 <b>Parte del {dias[pd.Timestamp(fecha).weekday()]} {fecha_corta(fecha)}</b>"]

    indice = ctx.get("indice") or {}
    if indice.get("cambio_dia") is not None:
        tendencia = ("por encima de su media de 200 sesiones: tendencia de fondo alcista" if indice.get("sobre_media")
                     else "por debajo de su media de 200 sesiones: tendencia bajista, la cartera reactiva no compra")
        partes += ["", f"📈 <b>Mercado</b>: {ref} {pct(indice['cambio_dia'])} hoy, {tendencia}."]

    partes += ["", "💼 <b>Tus carteras</b> (dinero ficticio)"]
    for estado, _ in items:
        r, _, _ = linea_resultado(estado, ref)
        dia = _cambio_del_dia(estado)
        hoy = f"{pct(dia)} hoy, " if dia is not None else ""
        partes.append(f"• <b>{escape(titulo_cartera(estado))}</b>: {dinero(_valor_actual(estado)[0])} ({hoy}{pct(r)} desde el inicio)")

    con_ops = [(e, ops) for e, ops in items if ops]
    if con_ops:
        iconos = {"COMPRA": "🟢 <b>Compra</b>", "VENTA": "🔴 <b>Vende</b>", "MANTENER": "🔵 <b>Mantiene</b>"}
        partes += ["", "🔔 <b>Movimientos de hoy</b>"]
        for estado, ops in con_ops:
            partes.append(f"<i>{escape(titulo_cartera(estado))}</i>")
            for op in ops[:max_ops]:
                e = info.get(op["ticker"])
                nombre = f" · {escape(e['nombre'])}" if e and e.get("nombre") else ""
                razon = op.get("explicacion") or razon_operacion(op, e, cfg["fscore_minimo"])
                partes += [f"{iconos.get(op['tipo'], op['tipo'])} {escape(op['ticker'])}{nombre}", f"<i>{escape(razon)}</i>"]
            if len(ops) > max_ops:
                partes.append(f"…y {len(ops) - max_ops} más (míralos en el menú del bot).")
    else:
        partes += ["", "🔔 Hoy ninguna cartera ha comprado ni vendido."]

    # Noticias de las empresas que tienes: primero las graves y negativas
    tenidas = {t for e, _ in items for t in e["cartera"]["posiciones"]}
    orden = {"grave": 0, "negativa": 1, "positiva": 2, "neutra": 3}
    destacadas = sorted(((t, h) for t, r in (ctx.get("noticias") or {}).items() if t in tenidas
                         for h in r["destacados"][:1] if h["tono"] != "neutra"), key=lambda th: orden[th[1]["tono"]])
    if destacadas:
        partes += ["", "📰 <b>Noticias de tus empresas</b>"]
        partes += [linea_noticia(t, h) for t, h in destacadas[:max_noticias]]
        partes.append("<i>🔴 grave · 🟠 negativa · 🟢 positiva (clasificación automática por palabras clave)</i>")

    if ctx.get("macro"):
        partes += ["", "🌍 <b>Economía y geopolítica</b>"]
        for h in ctx["macro"][:8]:
            fuente = f" ({escape(h['fuente'])})" if h.get("fuente") else ""
            partes.append(f"• {escape(h['titulo'])}{fuente}")
    partes += ["", "Abre el menú del bot (/menu) para ver el detalle de cada cartera y sus noticias."]
    return "\n".join(partes)


def mensaje_semanal(estados, ranking, cfg: dict, cambios=None, avisos=(), top=5) -> str:
    """Resumen de los lunes: cómo va cada cartera, las mejores empresas y avisos."""
    ref = escape(nombre_referencia(cfg))
    partes = [f"📊 <b>Resumen semanal</b> · {fecha_larga(pd.Timestamp.today())}", "",
              "<b>Cómo van tus carteras</b> (dinero ficticio)"]
    for estado in estados:
        r, rr, texto = linea_resultado(estado, ref)
        icono = "✅" if r >= rr else "🔸"
        partes.append(f"{icono} <b>{escape(titulo_cartera(estado))}</b> {texto}")
    if estados:
        partes.append("<i>✅ = va por delante del índice; 🔸 = va por detrás.</i>")

    info = info_empresas(ranking, top=top)
    mejores = sorted(((t, e) for t, e in info.items() if e["puesto"]), key=lambda te: te[1]["puesto"])[:top]
    if mejores:
        partes += ["", f"🏆 <b>Las {len(mejores)} mejores empresas ahora</b>"]
        for t, e in mejores:
            partes.append(f"{e['puesto']}. <b>{escape(t)}</b> · {escape(e['nombre'])}")
            partes.append(f"<i>{escape(explicar_empresa(e, cfg['fscore_minimo']))}</i>")
    if cambios and (cambios[0] or cambios[1]):
        entran, salen = cambios
        partes += ["", f"🆕 Nuevas entre las {cfg['alertas']['top_informe']} mejores: {escape(', '.join(entran)) or 'ninguna'}",
                   f"↩️ Dejan de estarlo: {escape(', '.join(salen)) or 'ninguna'}"]
    if avisos:
        partes += ["", "⚠️ <b>Atención</b>"] + [f"• {escape(a)}" for a in avisos]
    partes += ["", "Abre el menú del bot (/menu) para ver cada cartera y el porqué de cada empresa."]
    return "\n".join(partes)
