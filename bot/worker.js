// Bot de Telegram del inversor (Cloudflare Worker).
//
// - Atiende a las personas que escriben al bot: bienvenida, menús con botones y explicaciones.
// - Solo pueden usarlo quienes apruebe la persona administradora (ADMIN_CHAT_ID).
// - Recibe de GitHub Actions los avisos diarios (POST /notificar) y los reparte.
// - Lee las carteras y el ranking de bot.json, que publica GitHub Pages.
//
// Variables (wrangler.toml / secretos): TELEGRAM_TOKEN, BOT_SECRET, ADMIN_CHAT_ID, DATOS_URL
// Almacén KV: USUARIOS (una entrada "u:<chat_id>" por persona)

// ------------------------------------------------------------------ textos
const BIENVENIDA = (nombre) => `👋 <b>¡Hola, ${esc(nombre)}!</b>

Este bot sigue un método de inversión en bolsa de Estados Unidos y te cuenta, en lenguaje sencillo, qué haría y por qué.

<b>La idea en una frase:</b> comprar buenas empresas cuando están baratas, y tener paciencia.

<b>Cómo elige las empresas</b>
1️⃣ <b>Que sea barata</b>: cuánto beneficio genera para lo que cuesta. Si dos empresas valen lo mismo y una gana el triple, esa es más barata.
2️⃣ <b>Que sea buen negocio</b>: cuánto gana para el dinero que necesita invertir para funcionar.
3️⃣ <b>Que esté sana</b>: una nota de 0 a 9 que mira si gana dinero, si genera caja, si debe menos que antes… Se descartan las que sacan menos de 5.

Cada día se puntúan unas 1.500 empresas y se ordenan de mejor a peor: eso es el <b>ranking</b>.

<b>Las carteras usan dinero ficticio</b> (10.000 $ cada una) para ver cómo funcionaría el método sin arriesgar nada. Hay tres estilos que se comparan entre sí y con el S&amp;P 500, el índice de las 500 mayores empresas de EE. UU.

⚠️ <b>Importante:</b> es una herramienta casera para aprender y apoyarse, <b>no una recomendación de inversión</b>. Los datos pueden tener errores. Antes de poner dinero real, revisa cada empresa y decide tú.

Usa los botones de abajo 👇`;

const COMO_FUNCIONA = [
  `📖 <b>El método (1/4)</b>

Se basa en dos ideas muy conocidas:

<b>La «Fórmula Mágica» de Joel Greenblatt</b> (del libro <i>El pequeño libro que bate al mercado</i>). Da a cada empresa dos notas:
• <b>Barata</b>: beneficio operativo ÷ lo que cuesta comprar la empresa entera (incluida su deuda).
• <b>Rentable</b>: beneficio operativo ÷ el dinero que necesita el negocio para funcionar (fábricas, existencias…).
Se ordenan las empresas por cada nota, se suman los dos puestos y las de menor suma son las «buenas y baratas».

<b>El F-Score de Joseph Piotroski</b>: 9 preguntas de sí o no sobre la salud de la empresa (¿gana dinero? ¿genera caja? ¿debe menos que el año pasado? ¿mejora su margen?…). Cada «sí» es un punto. Si saca menos de 5, se descarta aunque parezca barata: a veces algo está barato por una buena razón.

Quedan fuera bancos, aseguradoras, eléctricas, inmobiliarias y empresas muy pequeñas, porque sus cuentas no encajan en la fórmula.

Los datos son las cuentas oficiales que las empresas entregan al regulador de EE. UU. (la SEC) y los precios de cada día.`,

  `🧭 <b>Cómo se decide qué comprar y vender (2/4)</b>

<b>1. El ranking.</b> Cada día se ordenan unas 800 empresas que pasan los filtros, de la más «buena y barata» (n.º 1) a la menos. Ese puesto es la base de todas las decisiones:
• Si una empresa está entre las <b>20 primeras</b> y hay hueco, se compra.
• Si cae por debajo del <b>puesto 50</b>, se vende para dejar sitio a otras mejores.
El margen entre 20 y 50 evita comprar y vender por pequeños vaivenes.

<b>2. Las noticias de la empresa</b> (solo en la cartera reactiva). Cada noticia positiva (mejora previsiones, supera estimaciones…) la sube 5 puestos, y cada negativa (rebaja previsiones, mínimos del año…) la baja 5, hasta 10 como mucho. Una noticia grave (fraude, quiebra, investigación oficial) la baja mucho más y, si además la acción ya está cayendo, se vende enseguida.

<b>3. La economía y la geopolítica</b> (solo en la reactiva). Cada día se leen titulares en español sobre aranceles, petróleo, tipos de interés, guerras o recesión. Cuando un tema se intensifica (sale bastante más de lo habitual), se aplica su efecto conocido sobre los negocios a los que afecta de verdad: por ejemplo, los aranceles perjudican a quien fabrica o importa coches, ropa o electrónica, pero no a una empresa de software; el petróleo caro favorece a las petroleras y perjudica a las aerolíneas. Cada efecto sube o baja 5 puestos, hasta 10.

<b>4. Protecciones.</b> La reactiva vende si una acción cae un 15 % desde su máximo, y deja de comprar si el S&amp;P 500 entra en tendencia bajista.

Así, el puesto final de cada empresa en la reactiva = fórmula ± noticias ± geopolítica. La semanal usa solo la fórmula, y compararlas nos dirá si las noticias ayudan.`,

  `🗂️ <b>Los tres estilos de cartera (3/4)</b>

Las tres eligen empresas del mismo ranking. Cambia <b>cada cuánto</b> miran y <b>cuándo</b> venden:

🐢 <b>Trimestral</b> (la original de Greenblatt)
Cada 3 meses compra como mucho 5 empresas de las mejores y mantiene cada una un año. Si al año sigue entre las mejores, se queda. Tarda unos 9 meses en tener sus 20 empresas. Pocas operaciones y pocas comisiones.

🐇 <b>Semanal</b>
Una vez por semana: compra las que entran entre las 20 mejores si tiene hueco y vende las que caen fuera de las 50 mejores o dejan de estar sanas.

⚡ <b>Reactiva</b>
Las reglas de la semanal, pero revisa el ranking cada día y además <b>reacciona al mercado</b>:
• Cada hora de la sesión vigila sus empresas y vende si una cae un 15 % desde su máximo (<i>stop móvil</i>) o si sale una noticia grave que el mercado ya castiga.
• No compra empresas con noticias graves o muy negativas, ni el día que se desploman.
• Si el S&amp;P 500 está por debajo de su media de 200 sesiones (tendencia bajista), deja de comprar y espera.
Reacciona antes, pero opera más y paga más comisiones.

¿Cuál funciona mejor? Eso es justo lo que queremos averiguar comparándolas durante meses.`,

  `⚠️ <b>Antes de invertir de verdad (4/4)</b>

• <b>No es una recomendación.</b> Es una herramienta para aplicar un método con disciplina. Las decisiones son tuyas.
• <b>Paciencia.</b> Este método ha tenido rachas de varios años peores que el índice. Solo funciona si se sigue también cuando va mal.
• <b>Diversifica.</b> La idea es tener unas 20 empresas, no apostar por una o dos.
• <b>Revisa cada empresa.</b> Los datos vienen de fuentes públicas y pueden tener errores o cifras puntuales (una venta extraordinaria, por ejemplo).
• <b>Desde España:</b> hay riesgo de cambio euro/dólar, conviene firmar el formulario W-8BEN con tu bróker (retención del 15 % en dividendos de EE. UU.) y las ganancias tributan en la renta.
• <b>Invierte solo dinero que no vayas a necesitar</b> en varios años.`,
];

const GLOSARIO = `❓ <b>Qué significa cada cosa</b>

<b>Ranking / puesto</b>: la posición de una empresa entre todas las que pasan los filtros. La n.º 1 es la más «buena y barata».

<b>Barata</b> (rendimiento de beneficios): cuántos dólares de beneficio operativo genera al año por cada 100 $ que costaría comprarla entera. Más es mejor.

<b>Rentable</b> (rentabilidad sobre el capital): cuánto gana al año por cada 100 $ invertidos en el negocio. Las empresas de software o farmacéuticas, con pocas fábricas, salen muy altas.

<b>Salud financiera</b> (F-Score): nota de 0 a 9. 7 o más es buena; 5 o 6, aceptable; menos de 5 se descarta.

<b>Cartera ficticia</b>: dinero inventado que sigue las reglas al pie de la letra con precios reales, para ver qué habría pasado.

<b>S&amp;P 500</b>: índice de las 500 mayores empresas de EE. UU. Es la referencia: si una cartera no le gana, sería más sencillo comprar un fondo indexado.

<b>Comisión</b>: lo que cobra el bróker por cada compra o venta. Las carteras ficticias pagan un 0,1 % (mínimo 1 $).

<b>Stop móvil</b>: protección que vende una acción si cae un porcentaje fijo (aquí, 15 %) desde el precio más alto que ha alcanzado desde que se compró. Limita pérdidas sin vender por pequeños vaivenes.

<b>Media de 200 sesiones</b>: el precio medio del índice en los últimos 200 días de bolsa (unos 10 meses). Si el índice está por encima, la tendencia de fondo se considera alcista.

<b>Noticias</b>: titulares de Google News clasificados automáticamente por palabras clave: 🔴 grave (fraude, quiebra, investigación oficial…), 🟠 negativa, 🟢 positiva. Es una clasificación sencilla y puede equivocarse.`;

const SIN_DATOS = "😕 Ahora mismo no puedo leer los datos de las carteras. Prueba de nuevo en unos minutos.";

// ------------------------------------------------------------------ utilidades
const esc = (t) => String(t ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const num = (x, dec = 0) => Number(x).toLocaleString("es-ES", { minimumFractionDigits: dec, maximumFractionDigits: dec, useGrouping: "always" });
const dinero = (x) => `${num(x)} $`;
const pct = (x) => { const r = Math.round(x * 10) / 10; return `${r > 0 ? "+" : r < 0 ? "−" : ""}${num(Math.abs(r), 1)} %`; };
const mayus = (t) => (t ? t[0].toUpperCase() + t.slice(1) : t);
const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
const fecha = (iso) => { const [a, m, d] = String(iso).slice(0, 10).split("-").map(Number); return `${d} de ${MESES[m - 1]} de ${a}`; };
const recortar = (t, max = 4000) => (t.length <= max ? t : t.slice(0, t.lastIndexOf("\n", max - 30)) + "\n…");
const boton = (text, callback_data) => ({ text, callback_data });

async function tg(env, metodo, datos) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/${metodo}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(datos),
  });
  const j = await r.json().catch(() => ({ ok: false }));
  if (!j.ok && !String(j.description || "").includes("message is not modified")) {
    console.log(`Telegram ${metodo}:`, j.description);
  }
  return j;
}

const enviar = (env, chat_id, { texto, botones }) => tg(env, "sendMessage", {
  chat_id, text: recortar(texto), parse_mode: "HTML", disable_web_page_preview: true,
  ...(botones ? { reply_markup: { inline_keyboard: botones } } : {}),
});

const editar = (env, chat_id, message_id, { texto, botones }) => tg(env, "editMessageText", {
  chat_id, message_id, text: recortar(texto), parse_mode: "HTML", disable_web_page_preview: true,
  ...(botones ? { reply_markup: { inline_keyboard: botones } } : {}),
});

async function datos(env) {
  try {
    const r = await fetch(env.DATOS_URL, { cf: { cacheTtl: 300 } });
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

// ------------------------------------------------------------------ personas
const esAdmin = (env, id) => String(id) === String(env.ADMIN_CHAT_ID);
const clave = (id) => `u:${id}`;
async function leerUsuario(env, id) {
  const v = await env.USUARIOS.get(clave(id));
  return v ? JSON.parse(v) : null;
}
const guardarUsuario = (env, u) => env.USUARIOS.put(clave(u.id), JSON.stringify(u));
async function listarUsuarios(env) {
  const lista = await env.USUARIOS.list({ prefix: "u:" });
  const usuarios = await Promise.all(lista.keys.map((k) => env.USUARIOS.get(k.name)));
  return usuarios.filter(Boolean).map((v) => JSON.parse(v));
}
const nombreDe = (de) => [de.first_name, de.last_name].filter(Boolean).join(" ") || de.username || String(de.id);

// ------------------------------------------------------------------ pantallas
function menu(d, u, env) {
  const filas = [
    [boton("💼 Carteras", "carteras"), boton("🏆 Mejores empresas", "top:0")],
    [boton("📰 Noticias", "noticias"), boton("📖 Cómo funciona", "como:0")],
    [boton("❓ Glosario", "glosario")],
    [boton(u?.avisos === false ? "🔕 Avisos: desactivados" : "🔔 Avisos: activados", "avisos")],
  ];
  if (d?.panel) filas[3].push({ text: "🌐 Panel web", url: d.panel });
  if (esAdmin(env, u?.id)) filas.push([boton("👥 Personas con acceso", "usuarios")]);
  const actualizado = d?.actualizado ? `\n<i>Datos del ${fecha(d.actualizado)}.</i>` : "";
  return { texto: `📋 <b>Menú</b>\n¿Qué quieres ver?${actualizado}`, botones: filas };
}

const volver = (a = "menu", texto = "⬅️ Volver") => [boton(texto, a), ...(a === "menu" ? [] : [boton("🏠 Menú", "menu")])];

function resultado(c, d) {
  const r = (c.valor / c.capital_inicial - 1) * 100;
  const rr = (c.valor_ref / c.capital_inicial - 1) * 100;
  return { r, rr, delante: r >= rr };
}

function listaCarteras(d) {
  if (!d.carteras.length) return { texto: "Todavía no hay carteras.", botones: [volver()] };
  const lineas = d.carteras.map((c) => {
    const { r, delante } = resultado(c, d);
    return `${delante ? "✅" : "🔸"} <b>${esc(c.titulo)}</b>: ${dinero(c.valor)} (${pct(r)})`;
  });
  return {
    texto: `💼 <b>Carteras</b> (dinero ficticio)\n\n${lineas.join("\n")}\n\n<i>✅ va por delante de ${esc(d.nombre_referencia)}; 🔸 va por detrás.</i>\n¿Cuál quieres ver?`,
    botones: [
      ...d.carteras.map((c) => [boton(`💼 ${c.titulo}`, `c:${c.nombre}`)]),
      [boton("📊 Todas a la vez", "todas")],
      volver(),
    ],
  };
}

function cartera(d, nombre) {
  const c = d.carteras.find((x) => x.nombre === nombre);
  if (!c) return listaCarteras(d);
  const { r, rr, delante } = resultado(c, d);
  const veredicto = delante ? "✅ Va por delante." : "🔸 Va por detrás.";
  const posiciones = c.posiciones.map((p) => `• <b>${esc(p.ticker)}</b> ${esc(p.nombre)}: ${dinero(p.valor)} (${pct(p.rent)})`);
  const revision = c.estilo === "reactiva" ? "Vigila sus empresas cada hora durante la sesión y revisa el ranking al cierre de cada día."
    : c.estilo === "diaria" ? "Revisa la cartera cada día de mercado."
    : c.proxima_revision ? `Próxima revisión: ${fecha(c.proxima_revision)}.` : "";
  return {
    texto: [
      `💼 <b>${esc(c.titulo)}</b>`, `<i>${esc(mayus(c.como_funciona))}.</i>`, "",
      `Empezó el ${fecha(c.fecha_inicio)} con ${dinero(c.capital_inicial)}. Hoy vale <b>${dinero(c.valor)}</b> (${pct(r)}).`,
      `En el mismo tiempo, ${esc(d.nombre_referencia)} ha hecho ${pct(rr)}. ${veredicto}`, "",
      `<b>Lo que tiene</b>: ${c.posiciones.length} empresas y ${dinero(c.efectivo)} sin invertir`,
      ...posiciones, "", revision,
    ].join("\n"),
    botones: [
      [boton("🤔 ¿Por qué estas empresas?", `por:${c.nombre}:0`)],
      [boton("🧾 Últimos movimientos", `mov:${c.nombre}`)],
      volver("carteras"),
    ],
  };
}

function porQue(d, nombre, pagina) {
  const c = d.carteras.find((x) => x.nombre === nombre);
  if (!c) return listaCarteras(d);
  const porPagina = 4;
  const total = Math.max(1, Math.ceil(c.posiciones.length / porPagina));
  const p = Math.min(Math.max(0, pagina), total - 1);
  const trozo = c.posiciones.slice(p * porPagina, (p + 1) * porPagina);
  const bloques = trozo.map((x) => {
    const n = (x.noticias || []).find((h) => h.tono !== "neutra") || (x.noticias || [])[0];
    const noticia = n ? `\n📰 ${TONOS[n.tono] || "⚪"} ${esc(n.titulo)}${n.fuente ? ` (${esc(n.fuente)})` : ""}` +
      (n.significa ? `\n   <i>→ ${esc(n.significa)}</i>` : "") : "";
    const ajuste = x.ajuste ? `\n🧭 ${esc(x.ajuste)}` : "";
    return `<b>${esc(x.ticker)}</b> · ${esc(x.nombre)}\n💡 ${esc(x.porque)}${ajuste}\n📍 <i>${esc(x.nota)}</i>${noticia}`;
  });
  const intro = p === 0 ? `<i>Cada día se ordenan ${d.n_aptas ? num(d.n_aptas) + " " : ""}empresas de mejor a peor (el ranking). ` +
    `Se compran las 20 primeras y se venden las que caen por debajo del puesto 50.` +
    (c.estilo === "reactiva" ? " Esta cartera además sube o baja empresas en el ranking según sus noticias y la geopolítica." : "") +
    `</i>\n\n` : "";
  const nav = [];
  if (p > 0) nav.push(boton("◀️ Anteriores", `por:${nombre}:${p - 1}`));
  if (p < total - 1) nav.push(boton("Siguientes ▶️", `por:${nombre}:${p + 1}`));
  return {
    texto: `🤔 <b>Por qué tiene estas empresas</b> · ${esc(c.titulo)}${total > 1 ? ` (${p + 1}/${total})` : ""}\n\n${intro}${bloques.join("\n\n") || "Todavía no tiene empresas."}`,
    botones: [...(nav.length ? [nav] : []), volver(`c:${nombre}`)],
  };
}

function movimientos(d, nombre) {
  const c = d.carteras.find((x) => x.nombre === nombre);
  if (!c) return listaCarteras(d);
  const iconos = { COMPRA: "🟢 Compra", VENTA: "🔴 Venta", MANTENER: "🔵 Se mantiene" };
  const bloques = c.operaciones.map((o) =>
    `${iconos[o.tipo] || o.tipo} <b>${esc(o.ticker)}</b> ${esc(o.nombre)} · ${fecha(o.fecha)}\n<i>${esc(o.explicacion)}</i>`);
  return {
    texto: `🧾 <b>Últimos movimientos</b> · ${esc(c.titulo)}\n\n${bloques.join("\n\n") || "Todavía no hay movimientos."}`,
    botones: [volver(`c:${nombre}`)],
  };
}

const TONOS = { grave: "🔴", negativa: "🟠", positiva: "🟢", neutra: "⚪" };

function noticiasPantalla(d) {
  const m = d.mercado || {};
  const lineas = [];
  if (m.cambio_dia !== undefined && m.cambio_dia !== null) {
    const tendencia = m.sobre_media ? "por encima de su media de 200 sesiones (tendencia alcista)"
      : "por debajo de su media de 200 sesiones (tendencia bajista: la cartera reactiva no compra)";
    lineas.push(`📈 <b>Mercado</b> (${fecha(m.fecha)}): ${esc(d.nombre_referencia)} ${pct(m.cambio_dia)}, ${tendencia}.`);
  }
  // Noticias de las empresas que tienen las carteras (sin repetir), primero las graves y negativas
  const orden = { grave: 0, negativa: 1, positiva: 2, neutra: 3 };
  const vistas = new Map();
  for (const c of d.carteras) for (const p of c.posiciones) {
    const n = (p.noticias || []).find((h) => h.tono !== "neutra") || (p.noticias || [])[0];
    if (!vistas.has(p.ticker) && n) vistas.set(p.ticker, n);
  }
  const empresas = [...vistas.entries()].filter(([, n]) => n.tono !== "neutra")
    .sort((a, b) => orden[a[1].tono] - orden[b[1].tono]).slice(0, 8)
    .map(([t, n]) => `${TONOS[n.tono]} <b>${esc(t)}</b>: ${esc(n.titulo)}${n.fuente ? ` (${esc(n.fuente)})` : ""}` +
      (n.significa ? `\n   <i>→ ${esc(n.significa)}</i>` : ""));
  if ((d.temas || []).length) {
    lineas.push("", "🧭 <b>Lo que está moviendo a los sectores</b>");
    for (const t of d.temas) {
      const efecto = [t.favorece.length ? `favorece a ${t.favorece.join(", ")}` : "", t.perjudica.length ? `perjudica a ${t.perjudica.join(", ")}` : ""]
        .filter(Boolean).join("; ");
      const habitual = t.habitual !== null && t.habitual !== undefined ? `; lo habitual, ${num(t.habitual, 1)}` : "";
      lineas.push(`• <b>${esc(t.tema)}</b> (${t.titulares} titulares hoy${habitual}): ${esc(t.porque)}; ${esc(efecto)}.` +
        (t.afectadas.length ? ` Tus empresas afectadas: ${esc(t.afectadas.join(", "))}.` : ""));
    }
    lineas.push("<i>La cartera reactiva sube o baja en su ranking a las empresas de esos sectores.</i>");
  }
  if (empresas.length) lineas.push("", "📰 <b>Tus empresas</b>", ...empresas);
  else if (vistas.size) lineas.push("", "📰 <b>Tus empresas</b>: sin noticias destacables estos días.");
  if ((d.macro || []).length) {
    lineas.push("", "🌍 <b>Economía y geopolítica</b>",
      ...d.macro.slice(0, 8).map((h) => `• ${esc(h.titulo)}${h.fuente ? ` (${esc(h.fuente)})` : ""}`));
  }
  if (!lineas.length) lineas.push("Todavía no hay noticias. Aparecerán tras el próximo parte diario.");
  lineas.push("", "<i>🔴 grave · 🟠 negativa · 🟢 positiva. Clasificación automática por palabras clave: puede equivocarse.</i>");
  return { texto: `📰 <b>Noticias</b>\n\n${lineas.join("\n")}`, botones: [volver()] };
}

function todas(d) {
  const orden = [...d.carteras].sort((a, b) => resultado(b, d).r - resultado(a, d).r);
  const lineas = orden.map((c, i) => {
    const { r, rr } = resultado(c, d);
    return `${["🥇", "🥈", "🥉"][i] || "•"} <b>${esc(c.titulo)}</b>: ${dinero(c.valor)} (${pct(r)}) · ${c.posiciones.length} empresas\n` +
      `<i>${esc(mayus(c.como_funciona))}. En el mismo periodo, ${esc(d.nombre_referencia)}: ${pct(rr)}.</i>`;
  });
  return {
    texto: `📊 <b>Todas las carteras</b>\n\n${lineas.join("\n\n")}\n\n<i>Las diferencias de pocos días no significan nada: hace falta comparar durante meses.</i>`,
    botones: [volver("carteras")],
  };
}

function mejores(d, pagina) {
  const porPagina = 10;
  const trozo = d.top.slice(pagina * porPagina, (pagina + 1) * porPagina);
  const bloques = trozo.map((e) => `<b>${e.puesto}. ${esc(e.ticker)}</b> · ${esc(e.nombre)}\n<i>${esc(e.porque)}</i>` +
    (e.ajuste ? `\n🧭 Reactiva: ${esc(e.ajuste.replace(/^Además, /, ""))}` : ""));
  const nav = [];
  if (pagina > 0) nav.push(boton("◀️ 1 a 10", "top:0"));
  if ((pagina + 1) * porPagina < d.top.length) nav.push(boton(`${(pagina + 1) * porPagina + 1} a ${Math.min(d.top.length, (pagina + 2) * porPagina)} ▶️`, `top:${pagina + 1}`));
  const fechaRanking = d.fecha_ranking ? ` (${fecha(d.fecha_ranking)})` : "";
  return {
    texto: `🏆 <b>Las mejores empresas ahora</b>${fechaRanking}\nSegún el método: buenas, baratas y sanas.\n\n${bloques.join("\n\n") || "No hay ranking disponible."}`,
    botones: [...(nav.length ? [nav] : []), volver()],
  };
}

function comoFunciona(pagina) {
  const p = Math.min(Math.max(0, pagina), COMO_FUNCIONA.length - 1);
  const nav = [];
  if (p > 0) nav.push(boton("◀️ Anterior", `como:${p - 1}`));
  if (p < COMO_FUNCIONA.length - 1) nav.push(boton("Siguiente ▶️", `como:${p + 1}`));
  return { texto: COMO_FUNCIONA[p], botones: [nav, volver()] };
}

async function pantallaUsuarios(env) {
  const usuarios = (await listarUsuarios(env)).filter((u) => !esAdmin(env, u.id));
  const etiqueta = { aprobado: "✅ con acceso", pendiente: "⏳ pendiente", rechazado: "🚫 sin acceso" };
  const lineas = usuarios.map((u) => `• ${esc(u.nombre)}${u.usuario ? ` (@${esc(u.usuario)})` : ""}: ${etiqueta[u.estado] || u.estado}`);
  const botones = usuarios.map((u) => (u.estado === "aprobado"
    ? [boton(`❌ Quitar acceso a ${u.nombre}`, `no:${u.id}`)]
    : [boton(`✅ Dar acceso a ${u.nombre}`, `ok:${u.id}`)]));
  return {
    texto: `👥 <b>Personas</b>\n\n${lineas.join("\n") || "Todavía no ha escrito nadie más al bot."}\n\n<i>Para invitar a alguien, pásale el enlace del bot. Cuando escriba, te llegará un aviso para aprobarlo.</i>`,
    botones: [...botones, volver()],
  };
}

// ------------------------------------------------------------------ lógica
async function pantalla(accion, env, u) {
  const [tipo, a, b] = accion.split(":");
  if (tipo === "como") return comoFunciona(Number(a) || 0);
  if (tipo === "glosario") return { texto: GLOSARIO, botones: [volver()] };
  if (tipo === "usuarios" && esAdmin(env, u.id)) return pantallaUsuarios(env);
  const d = await datos(env);
  if (tipo === "menu") return menu(d, u, env);
  if (!d) return { texto: SIN_DATOS, botones: [volver()] };
  if (tipo === "carteras") return listaCarteras(d);
  if (tipo === "c") return cartera(d, a);
  if (tipo === "por") return porQue(d, a, Number(b) || 0);
  if (tipo === "mov") return movimientos(d, a);
  if (tipo === "todas") return todas(d);
  if (tipo === "noticias") return noticiasPantalla(d);
  if (tipo === "top") return mejores(d, Number(a) || 0);
  return menu(d, u, env);
}

async function registrar(env, de) {
  let u = await leerUsuario(env, de.id);
  if (!u) {
    u = { id: de.id, nombre: nombreDe(de), usuario: de.username || "", estado: "pendiente", avisos: true,
          alta: new Date().toISOString().slice(0, 10) };
  }
  if (esAdmin(env, de.id)) u.estado = "aprobado";
  return u;
}

async function cambiarAcceso(env, id, aprobar) {
  const u = await leerUsuario(env, id);
  if (!u) return null;
  const antes = u.estado;
  u.estado = aprobar ? "aprobado" : "rechazado";
  await guardarUsuario(env, u);
  if (aprobar && antes !== "aprobado") {
    await enviar(env, id, { texto: BIENVENIDA(u.nombre.split(" ")[0]) });
    await enviar(env, id, menu(await datos(env), u, env));
  } else if (!aprobar && antes !== "rechazado") {
    await enviar(env, id, { texto: "Lo siento, ahora mismo no tienes acceso a este bot." });
  }
  return u;
}

async function atenderMensaje(env, msg) {
  if (msg.chat?.type !== "private" || !msg.from) return;
  const id = msg.chat.id;
  const nueva = !(await leerUsuario(env, msg.from.id));
  const u = await registrar(env, msg.from);
  await guardarUsuario(env, u);

  if (u.estado === "pendiente") {
    if (nueva) {
      await enviar(env, id, { texto: `👋 Hola, ${esc(u.nombre)}. Este bot es privado.\n\nHe avisado a la persona que lo gestiona; te escribiré por aquí en cuanto te dé acceso.` });
      await enviar(env, env.ADMIN_CHAT_ID, {
        texto: `🙋 <b>${esc(u.nombre)}</b>${u.usuario ? ` (@${esc(u.usuario)})` : ""} quiere usar el bot.\n¿Le das acceso?`,
        botones: [[boton("✅ Dar acceso", `ok:${u.id}`), boton("🚫 Rechazar", `no:${u.id}`)]],
      });
    } else {
      await enviar(env, id, { texto: "⏳ Tu solicitud sigue pendiente. Te escribiré en cuanto te den acceso." });
    }
    return;
  }
  if (u.estado !== "aprobado") {
    await enviar(env, id, { texto: "Lo siento, no tienes acceso a este bot." });
    return;
  }

  const texto = (msg.text || "").trim().split(/[\s@]/)[0].toLowerCase();
  if (texto === "/start") {
    await enviar(env, id, { texto: BIENVENIDA(u.nombre.split(" ")[0]) });
    await enviar(env, id, await pantalla("menu", env, u));
  } else if (texto === "/carteras") {
    await enviar(env, id, await pantalla("carteras", env, u));
  } else if (texto === "/ranking") {
    await enviar(env, id, await pantalla("top:0", env, u));
  } else if (texto === "/ayuda") {
    await enviar(env, id, comoFunciona(0));
  } else {
    await enviar(env, id, await pantalla("menu", env, u));
  }
}

async function atenderBoton(env, cq) {
  const id = cq.from.id;
  const chat = cq.message?.chat?.id ?? id;
  const mensaje = cq.message?.message_id;
  const accion = cq.data || "menu";
  let u = await leerUsuario(env, id);
  if (esAdmin(env, id) && (!u || u.estado !== "aprobado")) {
    // El administrador siempre tiene acceso, aunque pulse un botón antes de haber escrito al bot
    u = await registrar(env, cq.from);
    await guardarUsuario(env, u);
  }
  const [tipo, objetivo] = accion.split(":");

  if ((tipo === "ok" || tipo === "no") && esAdmin(env, id)) {
    const otro = await cambiarAcceso(env, objetivo, tipo === "ok");
    await tg(env, "answerCallbackQuery", { callback_query_id: cq.id, text: otro ? "Hecho" : "No encuentro a esa persona" });
    if (cq.message?.text?.startsWith("🙋")) {
      const texto = otro ? `${tipo === "ok" ? "✅ Has dado acceso a" : "🚫 Has rechazado a"} <b>${esc(otro.nombre)}</b>.` : "No encuentro a esa persona.";
      await editar(env, chat, mensaje, { texto });
    } else {
      await editar(env, chat, mensaje, await pantallaUsuarios(env));
    }
    return;
  }
  if (!u || u.estado !== "aprobado") {
    await tg(env, "answerCallbackQuery", { callback_query_id: cq.id, text: "No tienes acceso a este bot.", show_alert: true });
    return;
  }
  if (tipo === "avisos") {
    u.avisos = u.avisos === false;
    await guardarUsuario(env, u);
    await tg(env, "answerCallbackQuery", { callback_query_id: cq.id, text: u.avisos ? "Avisos activados" : "Avisos desactivados" });
    await editar(env, chat, mensaje, await pantalla("menu", env, u));
    return;
  }
  await tg(env, "answerCallbackQuery", { callback_query_id: cq.id });
  if (tipo === "abrir") {
    // Desde un aviso: el menú se abre en un mensaje nuevo para no borrar el aviso
    await enviar(env, chat, await pantalla("menu", env, u));
  } else {
    await editar(env, chat, mensaje, await pantalla(accion, env, u));
  }
}

function trozos(texto, limite = 3900) {
  const salida = [];
  let actual = "";
  for (const linea of texto.split("\n")) {
    if (actual && actual.length + linea.length + 1 > limite) {
      salida.push(actual);
      actual = "";
    }
    actual = actual ? `${actual}\n${linea}` : linea;
  }
  return actual ? [...salida, actual] : salida;
}

async function notificar(env, texto) {
  const usuarios = await listarUsuarios(env);
  const destinos = usuarios.filter((u) => u.estado === "aprobado" && u.avisos !== false).map((u) => String(u.id));
  const admin = usuarios.find((u) => esAdmin(env, u.id));
  if (!admin && !destinos.includes(String(env.ADMIN_CHAT_ID))) destinos.push(String(env.ADMIN_CHAT_ID));
  const partes = trozos(texto);
  let enviados = 0;
  for (const chat_id of destinos) {
    for (let i = 0; i < partes.length; i++) {
      const ultimo = i === partes.length - 1;
      const r = await enviar(env, chat_id, { texto: partes[i], botones: ultimo ? [[boton("📋 Abrir menú", "abrir")]] : null });
      if (r.ok && ultimo) enviados++;
    }
  }
  return enviados;
}

const COMANDOS = [
  { command: "start", description: "Bienvenida y explicación del método" },
  { command: "menu", description: "Menú principal" },
  { command: "carteras", description: "Cómo van las carteras" },
  { command: "ranking", description: "Las mejores empresas ahora" },
  { command: "ayuda", description: "Cómo funciona" },
];

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === "/telegram") {
      if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.BOT_SECRET) {
        return new Response("Prohibido", { status: 403 });
      }
      const update = await request.json();
      try {
        if (update.message) await atenderMensaje(env, update.message);
        else if (update.callback_query) await atenderBoton(env, update.callback_query);
      } catch (e) {
        console.log("Error atendiendo a Telegram:", e?.stack || e);
      }
      return new Response("ok");
    }
    if (request.method === "POST" && url.pathname === "/notificar") {
      if (request.headers.get("Authorization") !== `Bearer ${env.BOT_SECRET}`) {
        return new Response("Prohibido", { status: 403 });
      }
      const { texto } = await request.json();
      if (!texto) return new Response("Falta el texto", { status: 400 });
      return Response.json({ enviados: await notificar(env, texto) });
    }
    if (url.pathname === "/configurar") {
      // Solo apunta el webhook de Telegram a este mismo Worker: es seguro dejarlo abierto
      const webhook = await tg(env, "setWebhook", {
        url: `${url.origin}/telegram`, secret_token: env.BOT_SECRET,
        allowed_updates: ["message", "callback_query"],
      });
      const comandos = await tg(env, "setMyCommands", { commands: COMANDOS });
      await tg(env, "setMyDescription", {
        description: "Sigue un método de inversión (Fórmula Mágica + F-Score) con carteras de dinero ficticio y te explica cada decisión. Bot privado.",
      });
      return Response.json({ webhook, comandos });
    }
    return new Response("Bot del inversor funcionando.");
  },
};

// Para las pruebas
export const _interno = { pantalla, notificar, trozos, menu, BIENVENIDA, COMO_FUNCIONA, GLOSARIO };
