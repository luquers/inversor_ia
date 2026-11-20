"""Genera el panel web (carpeta docs/) que se abre en el móvil y se instala como una app."""
from __future__ import annotations

import json

import pandas as pd

from .analisis import HISTORICO, avisos_vigilancia
from .datos import RAIZ
from . import mensajes
from . import simulacion as sim

DOCS = RAIZ / "docs"

SECTORES = {
    "Industrials": "Industria", "Information Technology": "Tecnología", "Health Care": "Salud",
    "Consumer Discretionary": "Consumo discrecional", "Consumer Staples": "Consumo básico",
    "Energy": "Energía", "Materials": "Materiales", "Communication Services": "Comunicaciones",
    "Real Estate": "Inmobiliario", "Financials": "Finanzas", "Utilities": "Servicios públicos",
}
NOMBRES_REFERENCIA = {"SPY": "el S&P 500", "VOO": "el S&P 500", "IVV": "el S&P 500", "QQQ": "el Nasdaq 100"}


def _ranking_guardado():
    ruta = HISTORICO / "ranking_panel.csv"
    if not ruta.exists():
        return None, None
    ranking = pd.read_csv(ruta, index_col=0)
    fecha_ruta = HISTORICO / "ranking_panel_fecha.txt"
    fecha = fecha_ruta.read_text().strip() if fecha_ruta.exists() else None
    return ranking, fecha


def _datos_panel(cfg):
    ranking, fecha_ranking = _ranking_guardado()
    nombres = ranking["nombre"].fillna("").to_dict() if ranking is not None else {}

    carteras, vigiladas = [], list(cfg["alertas"].get("mis_acciones") or [])
    for nombre in sim.listar_carteras():
        e = sim.cargar(nombre)
        c = e["cartera"]
        vigiladas += list(c["posiciones"])
        ultimo = e["historial"][-1] if e["historial"] else {"cartera": e["capital_inicial"], "referencia": e["capital_inicial"]}
        posiciones = sorted(({
            "ticker": t, "nombre": nombres.get(t, ""), "acciones": p["acciones"],
            "fecha_compra": p["fecha_compra"], "precio_compra": p["precio_compra"],
            "valor": round(p["acciones"] * p["ultimo_precio"], 2),
            "rent": round((p["ultimo_precio"] / p["precio_compra"] - 1) * 100, 2),
        } for t, p in c["posiciones"].items()), key=lambda x: -x["valor"])
        siguiente = sim.proxima_revision(e)
        proxima = str(siguiente.date()) if siguiente is not None else None
        carteras.append({
            "diaria": sim.es_diaria(e),
            "nombre": nombre, "capital_inicial": e["capital_inicial"], "fecha_inicio": e["fecha_inicio"],
            "valor": ultimo["cartera"], "valor_ref": ultimo["referencia"], "efectivo": round(c["efectivo"], 2),
            "posiciones": posiciones, "proxima_revision": proxima,
            "historial": [[h["fecha"], h["cartera"], h["referencia"]] for h in e["historial"]],
            "operaciones": [o for o in reversed(c["operaciones"])][:15],
        })

    filas = []
    if ranking is not None:
        for t, f in ranking[ranking["apto"]].head(30).iterrows():
            filas.append({"ticker": t, "nombre": f["nombre"] if isinstance(f["nombre"], str) else "",
                          "sector": SECTORES.get(f["sector"], f["sector"] if isinstance(f["sector"], str) else ""),
                          "rb": round(float(f["rend_beneficios"]) * 100, 1),
                          "rc": round(float(f["rend_capital"]) * 100),
                          "f": int(f["fscore"])})

    ruta_pasado = HISTORICO / "ultimo_pasado.json"
    pasado = json.loads(ruta_pasado.read_text(encoding="utf-8")) if ruta_pasado.exists() else None
    ref = cfg["referencia"]
    return {
        "actualizado": pd.Timestamp.now().strftime("%Y-%m-%dT%H:%M"),
        "referencia": ref, "nombre_referencia": NOMBRES_REFERENCIA.get(ref, ref),
        "fscore_minimo": cfg["fscore_minimo"],
        "carteras": carteras,
        "ranking": {"fecha": fecha_ranking, "filas": filas} if filas else None,
        "avisos": avisos_vigilancia(ranking, cfg, vigiladas) if ranking is not None else [],
        "pasado": pasado,
    }


def datos_bot(cfg):
    """Lo que necesita el bot de Telegram (docs/bot.json), con las explicaciones ya redactadas."""
    ranking, fecha_ranking = _ranking_guardado()
    fmin = cfg["fscore_minimo"]
    estados = [sim.cargar(n) for n in sim.listar_carteras()]
    tenidas = [t for e in estados for t in e["cartera"]["posiciones"]]
    info = mensajes.info_empresas(ranking, extra=tenidas, top=30)
    ref = mensajes.nombre_referencia(cfg)

    carteras = []
    for e in estados:
        c = e["cartera"]
        valor, valor_ref = mensajes._valor_actual(e)
        siguiente = sim.proxima_revision(e)
        carteras.append({
            "nombre": e["nombre"], "titulo": mensajes.titulo_cartera(e), "estilo": mensajes.estilo(e),
            "como_funciona": mensajes.ESTILOS[mensajes.estilo(e)][1],
            "capital_inicial": e["capital_inicial"], "fecha_inicio": e["fecha_inicio"],
            "valor": round(valor, 2), "valor_ref": round(valor_ref, 2), "efectivo": round(c["efectivo"], 2),
            "proxima_revision": str(siguiente.date()) if siguiente is not None else None,
            "posiciones": sorted(({
                "ticker": t, "nombre": (info.get(t) or {}).get("nombre", ""), "acciones": p["acciones"],
                "fecha_compra": p["fecha_compra"], "valor": round(p["acciones"] * p["ultimo_precio"], 2),
                "rent": round((p["ultimo_precio"] / p["precio_compra"] - 1) * 100, 2),
                "porque": mensajes.explicar_empresa(info.get(t), fmin),
                "nota": mensajes.nota_posicion(p, e, info.get(t)),
            } for t, p in c["posiciones"].items()), key=lambda x: -x["valor"]),
            "operaciones": [{
                "fecha": o["fecha"], "tipo": o["tipo"], "ticker": o["ticker"],
                "nombre": (info.get(o["ticker"]) or {}).get("nombre", ""),
                "explicacion": o.get("explicacion") or mensajes.razon_operacion(o, info.get(o["ticker"]), fmin),
            } for o in reversed(c["operaciones"][-10:])],
        })

    top = []
    for t, emp in sorted(((t, x) for t, x in info.items() if x["puesto"]), key=lambda tx: tx[1]["puesto"])[:20]:
        top.append({"ticker": t, "nombre": emp["nombre"], "puesto": emp["puesto"],
                    "porque": mensajes.explicar_empresa(emp, fmin)})
    return {
        "actualizado": pd.Timestamp.now().strftime("%Y-%m-%dT%H:%M"),
        "fecha_ranking": fecha_ranking, "referencia": cfg["referencia"], "nombre_referencia": ref,
        "fscore_minimo": fmin, "panel": (cfg.get("web") or {}).get("url_panel") or "",
        "carteras": carteras, "top": top,
        "avisos": avisos_vigilancia(ranking, cfg, tenidas) if ranking is not None else [],
    }


def _iconos():
    from PIL import Image, ImageDraw

    for tam in (192, 512):
        ruta = DOCS / f"icono-{tam}.png"
        if ruta.exists():
            continue
        img = Image.new("RGB", (tam, tam), "#172238")
        d = ImageDraw.Draw(img)
        s = tam / 512
        puntos = [(120, 360), (200, 300), (260, 330), (390, 170)]
        d.line([(x * s, y * s) for x, y in puntos], fill="#F3F5F7", width=int(30 * s), joint="curve")
        r = 30 * s
        d.ellipse([390 * s - r, 170 * s - r, 390 * s + r, 170 * s + r], fill="#56C795")
        img.save(ruta)


def generar_panel(cfg):
    DOCS.mkdir(exist_ok=True)
    datos = json.dumps(_datos_panel(cfg), ensure_ascii=False).replace("</", "<\\/")
    (DOCS / "index.html").write_text(PLANTILLA.replace("__DATOS__", datos), encoding="utf-8")
    (DOCS / "bot.json").write_text(json.dumps(datos_bot(cfg), ensure_ascii=False), encoding="utf-8")
    (DOCS / "manifest.json").write_text(json.dumps({
        "name": "Mi inversor", "short_name": "Inversor", "lang": "es", "start_url": "./", "scope": "./",
        "display": "standalone", "background_color": "#F3F5F7", "theme_color": "#172238",
        "icons": [{"src": f"icono-{t}.png", "sizes": f"{t}x{t}", "type": "image/png", "purpose": "any maskable"}
                  for t in (192, 512)],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (DOCS / ".nojekyll").write_text("")
    _iconos()
    return DOCS / "index.html"


PLANTILLA = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Mi inversor</title>
<link rel="manifest" href="manifest.json">
<link rel="icon" href="icono-192.png">
<link rel="apple-touch-icon" href="icono-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Inversor">
<meta name="theme-color" content="#F3F5F7" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#101826" media="(prefers-color-scheme: dark)">
<meta name="robots" content="noindex">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500&family=Public+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --papel:#F3F5F7; --superficie:#FFFFFF; --tinta:#172238; --tinta-2:#566173; --linea:#D9DEE5;
  --estrategia:#24407A; --indice:#9AA3B2; --sube:#17734F; --baja:#B03A2A;
  --aviso:#7A4E00; --aviso-fondo:#FBF0D6;
  color-scheme:light;
}
@media (prefers-color-scheme:dark){
  :root{
    --papel:#101826; --superficie:#172133; --tinta:#E7EBF1; --tinta-2:#9AA5B6; --linea:#283449;
    --estrategia:#9DB7F5; --indice:#64718A; --sube:#56C795; --baja:#F08573;
    --aviso:#F2C46B; --aviso-fondo:#2A2414;
    color-scheme:dark;
  }
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--papel);color:var(--tinta);
  font:16px/1.5 "Public Sans",system-ui,-apple-system,sans-serif;font-variant-numeric:tabular-nums}
main{max-width:600px;margin:0 auto;
  padding:calc(18px + env(safe-area-inset-top)) 20px calc(100px + env(safe-area-inset-bottom))}
.cabecera{display:flex;justify-content:space-between;align-items:baseline;gap:12px;
  font-size:13px;color:var(--tinta-2);margin-bottom:32px}
.cabecera b{font-size:15px;font-weight:600;color:var(--tinta)}
.titular{font-family:Newsreader,Georgia,serif;font-weight:400;font-size:clamp(29px,8vw,40px);
  line-height:1.14;letter-spacing:-.012em;margin:0 0 14px;text-wrap:balance}
.entradilla{font-size:17px;line-height:1.5;color:var(--tinta-2);margin:0 0 22px;max-width:32em}
.entradilla b{font-weight:600;color:var(--tinta)}
.sube,.entradilla b.sube{color:var(--sube)} .baja,.entradilla b.baja{color:var(--baja)}
h2{font-family:Newsreader,Georgia,serif;font-weight:500;font-size:23px;line-height:1.25;margin:44px 0 6px}
.nota{font-size:14px;color:var(--tinta-2);margin:4px 0 14px;max-width:34em}
.lista{list-style:none;margin:0;padding:0}
.lista li{display:grid;grid-template-columns:1fr auto;column-gap:16px;padding:13px 0;border-bottom:1px solid var(--linea)}
.lista li:last-child{border-bottom:0}
.tk{font-weight:600}
.sub{font-size:13px;color:var(--tinta-2);line-height:1.4}
.der{text-align:right;white-space:nowrap}
.selector{display:flex;gap:8px;margin:-12px 0 26px;flex-wrap:wrap}
.selector button{font:500 14px "Public Sans",system-ui,sans-serif;color:var(--tinta-2);background:none;
  border:1px solid var(--linea);border-radius:999px;padding:6px 14px;cursor:pointer}
.selector button[aria-pressed=true]{color:var(--papel);background:var(--tinta);border-color:var(--tinta)}
.aviso{background:var(--aviso-fondo);color:var(--aviso);border-radius:10px;padding:12px 14px;font-size:14px;margin:0 0 22px}
.aviso p{margin:0}.aviso p+p{margin-top:6px}

/* gráfico */
.grafico{position:relative;margin:4px 0 8px}
.lectura{font-size:13px;color:var(--tinta-2);min-height:20px;margin-bottom:6px}
.lectura b{color:var(--tinta);font-weight:600}
.lienzo{position:relative;height:210px;touch-action:pan-y}
.lienzo svg{position:absolute;top:0;bottom:0;left:0;right:68px;width:calc(100% - 68px);height:100%;overflow:visible}
.eje{position:absolute;right:0;width:62px;text-align:right;font-size:11px;color:var(--tinta-2);transform:translateY(-50%)}
.fechas{display:flex;justify-content:space-between;font-size:12px;color:var(--tinta-2);margin-top:6px;margin-right:68px}
.leyenda{display:flex;gap:18px;font-size:13px;color:var(--tinta-2);margin-top:10px}
.leyenda span::before{content:"";display:inline-block;width:16px;height:0;vertical-align:middle;
  margin-right:6px;border-top:2.5px solid var(--estrategia)}
.leyenda span.ind::before{border-top:2px dashed var(--indice)}

/* ranking */
.rk li{grid-template-columns:30px 1fr auto}
.puesto{font-family:Newsreader,Georgia,serif;font-size:21px;line-height:1.2;color:var(--tinta-2)}
.puntos{display:flex;gap:3px;margin-top:6px}
.puntos i{width:7px;height:7px;border-radius:50%;border:1.5px solid var(--estrategia);display:block}
.puntos i.si{background:var(--estrategia)}
.cifra{font-size:14px}.cifra small{font-size:12px;color:var(--tinta-2);margin-right:4px}
.claves{display:grid;grid-template-columns:auto 1fr;gap:6px 12px;font-size:14px;color:var(--tinta-2);
  margin:14px 0 8px;max-width:34em}
.claves b{color:var(--tinta);font-weight:600}

/* tabla del pasado */
table{width:100%;border-collapse:collapse;font-size:15px;margin:8px 0 6px}
th,td{padding:10px 0 10px 12px;border-bottom:1px solid var(--linea);text-align:right;white-space:nowrap}
th:first-child,td:first-child{white-space:normal;padding-left:0}
th:first-child,td:first-child{text-align:left;color:var(--tinta-2);font-weight:400}
thead th{font-size:13px;color:var(--tinta-2);font-weight:500}
tbody tr:last-child td{border-bottom:0}

.vacio{margin-top:8vh}
.vacio ol{padding-left:20px;color:var(--tinta-2)}
.vacio li{margin:4px 0}
footer{margin-top:56px;font-size:12px;color:var(--tinta-2)}

nav{position:fixed;left:0;right:0;bottom:0;display:flex;justify-content:center;
  background:var(--superficie);border-top:1px solid var(--linea);padding-bottom:env(safe-area-inset-bottom)}
nav button{flex:1;max-width:200px;background:none;border:0;cursor:pointer;
  font:500 14px "Public Sans",system-ui,sans-serif;color:var(--tinta-2);padding:14px 0 16px;
  box-shadow:inset 0 2px 0 transparent;transition:box-shadow .2s,color .2s}
nav button[aria-selected=true]{color:var(--tinta);box-shadow:inset 0 2.5px 0 var(--estrategia)}
button:focus-visible{outline:2px solid var(--estrategia);outline-offset:2px}
nav button:focus-visible{outline-offset:-4px}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
</head>
<body>
<main id="app"></main>
<nav role="tablist" aria-label="Secciones">
  <button role="tab" data-p="cartera">Cartera</button>
  <button role="tab" data-p="ranking">Ranking</button>
  <button role="tab" data-p="pasado">Pasado</button>
</nav>
<script id="datos" type="application/json">__DATOS__</script>
<script>
const D = JSON.parse(document.getElementById("datos").textContent);
const app = document.getElementById("app");
let carteraSel = 0;

const nf0 = new Intl.NumberFormat("es-ES", {maximumFractionDigits: 0});
const nf2 = new Intl.NumberFormat("es-ES", {minimumFractionDigits: 2, maximumFractionDigits: 2});
const dinero = v => nf0.format(v) + " $";
const precio = v => nf2.format(v) + " $";
const pct = v => (v > 0 ? "+" : v < 0 ? "−" : "") + (Math.abs(v) >= 100 ? nf0 : nf2).format(Math.abs(v)).replace(/,00$/, "") + " %";
const clase = v => v > 0 ? "sube" : v < 0 ? "baja" : "";
const fecha = (s, larga) => new Date(s + "T12:00:00").toLocaleDateString("es-ES",
  larga ? {day: "numeric", month: "long", year: "numeric"} : {day: "numeric", month: "short", year: "numeric"});
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const ref = D.nombre_referencia;
const Ref = ref.charAt(0).toUpperCase() + ref.slice(1);

function cabecera() {
  const d = new Date(D.actualizado);
  return `<div class="cabecera"><b>Mi inversor</b><span>Actualizado el ${d.toLocaleDateString("es-ES",
    {day: "numeric", month: "short"})} a las ${d.toLocaleTimeString("es-ES", {hour: "2-digit", minute: "2-digit"})}</span></div>`;
}

/* ---------- gráfico de líneas sin librerías ---------- */
function grafico(serie) {
  if (!serie || serie.length < 2) return "";
  const id = "g" + Math.random().toString(36).slice(2, 8);
  setTimeout(() => montarGrafico(id, serie));
  return `<div class="grafico" id="${id}">
      <div class="lectura" aria-live="polite"></div>
      <div class="lienzo"></div>
      <div class="fechas"><span>${fecha(serie[0][0])}</span><span>${fecha(serie[serie.length - 1][0])}</span></div>
      <div class="leyenda"><span>Tu estrategia</span><span class="ind">${esc(Ref)}</span></div>
    </div>`;
}
function montarGrafico(id, serie) {
  const caja = document.getElementById(id); if (!caja) return;
  const lienzo = caja.querySelector(".lienzo"), lectura = caja.querySelector(".lectura");
  const vals = serie.flatMap(p => [p[1], p[2]]);
  let min = Math.min(...vals), max = Math.max(...vals);
  const m = (max - min) * 0.08 || max * 0.02; min -= m; max += m;
  const W = 1000, H = 1000, n = serie.length;
  const x = i => (i / (n - 1)) * W, y = v => H - ((v - min) / (max - min)) * H;
  const linea = k => serie.map((p, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(p[k]).toFixed(1)).join("");
  const marcas = [0.2, 0.5, 0.8].map(t => min + (max - min) * t);
  lienzo.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      ${marcas.map(v => `<line x1="0" x2="${W}" y1="${y(v)}" y2="${y(v)}" stroke="var(--linea)" vector-effect="non-scaling-stroke"/>`).join("")}
      <path d="${linea(2)}" fill="none" stroke="var(--indice)" stroke-width="2" stroke-dasharray="5 4" vector-effect="non-scaling-stroke"/>
      <path d="${linea(1)}" fill="none" stroke="var(--estrategia)" stroke-width="2.5" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>
      <line class="cursor" y1="0" y2="${H}" stroke="var(--tinta-2)" vector-effect="non-scaling-stroke" visibility="hidden"/>
    </svg>` + marcas.map(v => `<span class="eje" style="top:${(y(v) / H * 100).toFixed(2)}%">${dinero(v)}</span>`).join("");
  const cursor = lienzo.querySelector(".cursor");
  const base = `Toca o arrastra sobre el gráfico para ver cada fecha.`;
  lectura.textContent = base;
  const mostrar = ev => {
    const r = lienzo.querySelector("svg").getBoundingClientRect();
    const i = Math.max(0, Math.min(n - 1, Math.round(((ev.clientX - r.left) / r.width) * (n - 1))));
    cursor.setAttribute("x1", x(i)); cursor.setAttribute("x2", x(i)); cursor.setAttribute("visibility", "visible");
    lectura.innerHTML = `${fecha(serie[i][0])}: <b>${dinero(serie[i][1])}</b> con tu estrategia, ${dinero(serie[i][2])} con ${esc(ref)}`;
  };
  lienzo.addEventListener("pointermove", mostrar);
  lienzo.addEventListener("pointerdown", mostrar);
  lienzo.addEventListener("pointerleave", () => { cursor.setAttribute("visibility", "hidden"); lectura.textContent = base; });
}

/* ---------- pestaña Cartera ---------- */
function vistaCartera() {
  if (!D.carteras.length) return cabecera() + `<div class="vacio">
      <h1 class="titular">Aún no tienes ninguna cartera ficticia.</h1>
      <p class="entradilla">Crea una para empezar a probar el método con precios reales y sin arriesgar dinero.</p>
      <ol><li>Abre tu repositorio en GitHub y entra en <b>Actions</b>.</li>
      <li>Elige <b>Acciones manuales</b> y pulsa <b>Run workflow</b>.</li>
      <li>Selecciona <b>Crear cartera ficticia</b>, indica el capital y confirma.</li></ol></div>`;
  const c = D.carteras[carteraSel];
  const r = (c.valor / c.capital_inicial - 1) * 100, rr = (c.valor_ref / c.capital_inicial - 1) * 100;
  const selector = D.carteras.length > 1 ? `<div class="selector">${D.carteras.map((k, i) =>
      `<button aria-pressed="${i === carteraSel}" data-c="${i}">${esc(k.nombre)}</button>`).join("")}</div>` : "";
  const nueva = c.historial.length < 2;
  let h = cabecera() + selector +
    `<h1 class="titular">Tus ${dinero(c.capital_inicial)} ficticios valen hoy ${dinero(c.valor)}.</h1>` +
    (nueva
      ? `<p class="entradilla">La cartera empezó el ${fecha(c.fecha_inicio, true)}. El gráfico aparecerá a partir de la próxima actualización.</p>`
      : `<p class="entradilla">Eso es <b class="${clase(r)}">${pct(r)}</b> desde el ${fecha(c.fecha_inicio, true)}. ${esc(Ref)} ha hecho <b class="${clase(rr)}">${pct(rr)}</b> en el mismo tiempo.</p>`);
  if (D.avisos.length) h += `<div class="aviso" role="note">${D.avisos.map(a => `<p>${esc(a)}</p>`).join("")}</div>`;
  h += grafico(c.historial);

  h += `<h2>Lo que tienes</h2>`;
  h += c.diaria
    ? `<p class="nota">Esta cartera se revisa cada día de mercado: compra lo que entra entre las mejores y vende lo que cae del ranking.</p>`
    : c.proxima_revision ? `<p class="nota">La próxima revisión de la cartera será el ${fecha(c.proxima_revision, true)}.</p>` : "";
  h += `<ul class="lista">` + c.posiciones.map(p => `<li>
      <div><span class="tk">${esc(p.ticker)}</span><div class="sub">${esc(p.nombre) || "&nbsp;"}<br>${nf0.format(p.acciones)} acciones desde el ${fecha(p.fecha_compra)}</div></div>
      <div class="der">${dinero(p.valor)}<div class="sub ${clase(p.rent)}">${pct(p.rent)}</div></div></li>`).join("") +
    `<li><div><span class="tk">Efectivo</span><div class="sub">Sin invertir, a la espera de la próxima compra</div></div>
      <div class="der">${dinero(c.efectivo)}</div></li></ul>`;

  if (c.operaciones.length) {
    const nombres = {COMPRA: "Compra", VENTA: "Venta", MANTENER: "Se mantiene"};
    h += `<h2>Últimos movimientos</h2><ul class="lista">` + c.operaciones.map(o => `<li>
        <div><span class="tk">${nombres[o.tipo] || o.tipo} de ${esc(o.ticker)}</span><div class="sub">${fecha(o.fecha)}, ${esc(o.motivo.charAt(0).toLowerCase() + o.motivo.slice(1))}</div></div>
        <div class="der">${precio(o.precio)}${o.resultado_pct != null ? `<div class="sub ${clase(o.resultado_pct)}">${pct(o.resultado_pct)}</div>` : ""}</div></li>`).join("") + `</ul>`;
  }
  return h + pie();
}

/* ---------- pestaña Ranking ---------- */
function vistaRanking() {
  if (!D.ranking) return cabecera() + `<div class="vacio"><h1 class="titular">El ranking aparecerá tras el primer informe semanal.</h1>
      <p class="entradilla">Se calcula cada lunes y cada vez que una cartera se revisa. Si no quieres esperar, lánzalo desde GitHub: Actions, Acciones manuales, Informe ahora.</p></div>`;
  const R = D.ranking;
  let h = cabecera() + `<h1 class="titular">Las mejores empresas esta semana</h1>
    <p class="entradilla">Negocios muy rentables a buen precio, según la Fórmula Mágica. Solo aparecen los que tienen un F-Score de ${D.fscore_minimo} o más${R.fecha ? `. Calculado el ${fecha(R.fecha, true)}` : ""}.</p>
    <div class="claves"><b>Barata</b><span>Beneficio operativo frente al precio de toda la empresa. Cuanto más alto, más barata.</span>
    <b>Rentable</b><span>Beneficio operativo frente al capital que necesita el negocio.</span>
    <b>F-Score</b><span>Salud financiera: 9 comprobaciones, un punto por cada una que supera.</span></div>`;
  if (D.avisos.length) h += `<div class="aviso" role="note">${D.avisos.map(a => `<p>${esc(a)}</p>`).join("")}</div>`;
  h += `<ul class="lista rk">` + R.filas.map((f, i) => `<li>
      <div class="puesto">${i + 1}</div>
      <div><span class="tk">${esc(f.ticker)}</span><div class="sub">${esc(f.nombre)}<br>${esc(f.sector)}</div>
        <div class="puntos" role="img" aria-label="F-Score ${f.f} de 9">${Array.from({length: 9}, (_, k) => `<i class="${k < f.f ? "si" : ""}"></i>`).join("")}</div></div>
      <div class="der"><div class="cifra"><small>Barata</small>${nf2.format(f.rb).replace(/,?0+$/, "")} %</div>
        <div class="cifra"><small>Rentable</small>${nf0.format(f.rc)} %</div></div></li>`).join("") + `</ul>`;
  return h + pie();
}

/* ---------- pestaña Pasado ---------- */
function vistaPasado() {
  const P = D.pasado;
  if (!P) return cabecera() + `<div class="vacio"><h1 class="titular">Todavía no has simulado el pasado.</h1>
      <p class="entradilla">Descubre cómo te habría ido siguiendo estas reglas desde 2010 aproximadamente.</p>
      <ol><li>Abre tu repositorio en GitHub y entra en <b>Actions</b>.</li><li>Elige <b>Acciones manuales</b> y pulsa <b>Run workflow</b>.</li>
      <li>Selecciona <b>Simular el pasado</b> y confirma. Tarda entre 15 y 40 minutos.</li></ol></div>`;
  const anio = s => new Date(s + "T12:00:00").toLocaleDateString("es-ES", {month: "long", year: "numeric"});
  const me = P.metricas.estrategia, mr = P.metricas.referencia;
  const fila = (t, k, signo) => `<tr><td>${t}</td><td>${me[k] == null ? "–" : (signo ? pct(me[k]) : nf2.format(me[k]) + " %")}</td><td>${mr[k] == null ? "–" : (signo ? pct(mr[k]) : nf2.format(mr[k]) + " %")}</td></tr>`;
  let h = cabecera() + `<h1 class="titular">Con ${dinero(P.capital)} en ${anio(P.inicio)} habrías llegado a ${dinero(P.final.estrategia)}.</h1>
    <p class="entradilla">Invirtiendo lo mismo en ${esc(ref)} habrías llegado a <b>${dinero(P.final.referencia)}</b>. Simulación hasta el ${fecha(P.fin, true)}.</p>` +
    grafico(P.curva) +
    `<h2>En cifras</h2><table><thead><tr><th></th><th>Tu estrategia</th><th>${esc(Ref)}</th></tr></thead><tbody>
      ${fila("Rentabilidad al año", "rentabilidad_anual_%", true)}
      ${fila("Rentabilidad total", "rentabilidad_total_%", true)}
      ${fila("Peor caída desde un máximo", "caida_maxima_%", true)}
      ${fila("Volatilidad anual", "volatilidad_anual_%", false)}
    </tbody></table>` +
    (P.pct_ganadoras != null ? `<p class="nota">${nf0.format(P.ventas)} ventas en total; el ${P.pct_ganadoras} % se cerraron con ganancia.</p>` : "") +
    `<h2>Cómo leerlo</h2>
    <p class="nota">Las cuentas de cada empresa se usan solo a partir del día en que se publicaron en la SEC, así que la simulación no conoce el futuro.</p>
    <p class="nota">Aun así, se analizan las empresas que están hoy en el índice. Las que quebraron o salieron no aparecen, y eso mejora el resultado. Tómalo como el escenario optimista.</p>
    <p class="nota">Para probar otras fechas o reglas, cambia config.yaml y vuelve a lanzar Simular el pasado desde GitHub.</p>`;
  return h + pie();
}

const pie = () => `<footer>Dinero ficticio con precios reales. No es asesoramiento financiero.</footer>`;

/* ---------- navegación ---------- */
const vistas = {cartera: vistaCartera, ranking: vistaRanking, pasado: vistaPasado};
function ir(p, desplazar) {
  if (!vistas[p]) p = "cartera";
  document.querySelectorAll("nav button").forEach(b => b.setAttribute("aria-selected", b.dataset.p === p));
  app.innerHTML = vistas[p]();
  app.querySelectorAll(".selector button").forEach(b => b.onclick = () => { carteraSel = +b.dataset.c; ir("cartera"); });
  if (desplazar) window.scrollTo(0, 0);
}
document.querySelectorAll("nav button").forEach(b => b.onclick = () => { history.replaceState(null, "", "#" + b.dataset.p); ir(b.dataset.p, true); });
ir(location.hash.slice(1));
</script>
</body>
</html>
"""
