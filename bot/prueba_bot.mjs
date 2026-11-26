// Prueba del bot sin internet: simula Telegram, el almacén KV y bot.json.
// Uso: node bot/prueba_bot.mjs [ruta/a/un/bot.json real]   (sin ruta usa datos inventados)
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import worker, { _interno } from "./worker.js";

const ADMIN = 111, AMIGA = 222, OTRO = 333;
const posiciones = Array.from({ length: 20 }, (_, i) => ({
  ticker: `T${i}`, nombre: `Empresa ${i} & Co <S.A.>`, acciones: 10, fecha_compra: "2026-11-20",
  valor: 500 - i, rent: i % 2 ? 1.5 : -0.7,
  porque: "Genera 15 $ de beneficio al año por cada 100 $ que vale la empresa y su salud financiera es buena (7/9).",
  nota: `Ahora es la n.º ${i + 1} del ranking. Se vendería si baja del puesto 50.`,
  noticias: i % 3 ? [] : [{ titulo: `Empresa ${i} <cuts> guidance & more`, fuente: "Reuters", fecha: "2026-11-25", tono: ["grave", "negativa", "positiva", "neutra"][i % 4], significa: "rebaja sus previsiones & más" }],
  ajuste: i === 0 ? "Además, sus noticias la bajan 5 puestos (rebaja sus previsiones). Por la fórmula sola sería la n.º 1; con el ajuste queda en la 6." : "",
}));
const ruta = process.argv[2];
const DATOS = ruta ? JSON.parse(readFileSync(ruta, "utf8")) : {
  actualizado: "2026-11-20T21:14", fecha_ranking: "2026-11-20", referencia: "SPY", nombre_referencia: "el S&P 500",
  fscore_minimo: 5, panel: "https://ejemplo.github.io/inversor/",
  carteras: [
    { nombre: "principal", titulo: "Principal (trimestral)", estilo: "trimestral", como_funciona: "revisa cada 3 meses y mantiene cada empresa un año",
      capital_inicial: 10000, fecha_inicio: "2026-11-20", valor: 10100, valor_ref: 10050, efectivo: 7600,
      proxima_revision: "2027-02-20", posiciones: posiciones.slice(0, 5),
      operaciones: [{ fecha: "2026-11-20", tipo: "COMPRA", ticker: "T0", nombre: "Empresa 0", explicacion: "Es la n.º 1 del ranking." }] },
    { nombre: "diaria", titulo: "Diaria", estilo: "diaria", como_funciona: "revisa cada día según el ranking",
      capital_inicial: 10000, fecha_inicio: "2026-11-20", valor: 9950, valor_ref: 10050, efectivo: 640,
      proxima_revision: null, posiciones, operaciones: [] },
  ],
  top: Array.from({ length: 20 }, (_, i) => ({ ticker: `T${i}`, nombre: `Empresa ${i}`, puesto: i + 1, porque: "Barata y sana." })),
  avisos: [],
  mercado: { fecha: "2026-11-25", ticker: "SPY", cambio_dia: -0.4, sobre_media: false },
  macro: [{ titulo: "La Reserva Federal & los tipos <hoy>", fuente: "El País", tema: "Tipos e inflación" }],
  temas: [{ tema: "Aranceles", porque: "encarecen importaciones & componentes", titulares: 3, favorece: [], perjudica: ["Industria", "Materiales"], afectadas: ["T3"] }],
  n_aptas: 820,
};

// ---- simulación de Telegram, KV y la web de datos
const llamadas = [];
globalThis.fetch = async (url, opciones = {}) => {
  url = String(url);
  if (url.startsWith("https://api.telegram.org/")) {
    llamadas.push({ metodo: url.split("/").pop(), ...JSON.parse(opciones.body) });
    return new Response(JSON.stringify({ ok: true, result: {} }));
  }
  if (url === "https://datos.test/bot.json") return new Response(JSON.stringify(DATOS));
  throw new Error(`fetch inesperado: ${url}`);
};
const kv = new Map();
const env = {
  TELEGRAM_TOKEN: "TOKEN", BOT_SECRET: "secreto", ADMIN_CHAT_ID: String(ADMIN), DATOS_URL: "https://datos.test/bot.json",
  USUARIOS: {
    get: async (k) => kv.get(k) ?? null,
    put: async (k, v) => void kv.set(k, v),
    list: async ({ prefix }) => ({ keys: [...kv.keys()].filter((k) => k.startsWith(prefix)).map((name) => ({ name })) }),
  },
};

const telegram = (update, secreto = "secreto") => worker.fetch(new Request("https://bot.test/telegram", {
  method: "POST", headers: { "X-Telegram-Bot-Api-Secret-Token": secreto }, body: JSON.stringify(update),
}), env);
const quien = (id, nombre) => ({ id, first_name: nombre, username: nombre.toLowerCase() });
const mensaje = (id, nombre, text) => telegram({ message: { message_id: 1, chat: { id, type: "private" }, from: quien(id, nombre), text } });
const pulsa = (id, nombre, data, text = "") => telegram({ callback_query: { id: "cb", data, from: quien(id, nombre), message: { message_id: 9, chat: { id }, text } } });
const enviadosA = (id) => llamadas.filter((l) => ["sendMessage", "editMessageText"].includes(l.metodo) && String(l.chat_id) === String(id));
const botonesDe = (l) => (l.reply_markup?.inline_keyboard || []).flat();
const reiniciar = () => { llamadas.length = 0; };

function htmlValido(texto) {
  assert.ok(texto.length <= 4096, `Mensaje demasiado largo (${texto.length})`);
  const sinEtiquetas = texto.replace(/<\/?(b|i)>/g, "");
  assert.ok(!/[<>]/.test(sinEtiquetas), `HTML no permitido o sin escapar: ${texto.slice(0, 200)}`);
  assert.ok(!/&(?!amp;|lt;|gt;)/.test(sinEtiquetas), "Hay un & sin escapar");
  for (const t of ["b", "i"]) {
    assert.equal((texto.match(new RegExp(`<${t}>`, "g")) || []).length, (texto.match(new RegExp(`</${t}>`, "g")) || []).length, `Etiqueta <${t}> sin cerrar`);
  }
}

// 1. Sin la clave del webhook no se atiende nada
assert.equal((await telegram({}, "mala")).status, 403);
assert.equal((await worker.fetch(new Request("https://bot.test/notificar", { method: "POST", body: "{}" }), env)).status, 403);

// 1b. El administrador pulsa «Abrir menú» en un aviso sin haber escrito nunca al bot
await pulsa(ADMIN, "Javi", "abrir");
assert.equal(enviadosA(ADMIN)[0]?.metodo, "sendMessage", "El administrador siempre puede abrir el menú");
assert.equal(JSON.parse(kv.get(`u:${ADMIN}`)).estado, "aprobado");
kv.clear();
reiniciar();

// 2. Una desconocida escribe: queda pendiente y se avisa al administrador
await mensaje(AMIGA, "Lucia", "/start");
assert.match(enviadosA(AMIGA)[0].text, /privado/);
const solicitud = enviadosA(ADMIN)[0];
assert.match(solicitud.text, /Lucia/);
assert.deepEqual(botonesDe(solicitud).map((b) => b.callback_data), [`ok:${AMIGA}`, `no:${AMIGA}`]);
assert.equal(JSON.parse(kv.get(`u:${AMIGA}`)).estado, "pendiente");
reiniciar();
await mensaje(AMIGA, "Lucia", "hola");
assert.match(enviadosA(AMIGA)[0].text, /pendiente/);
assert.equal(enviadosA(ADMIN).length, 0, "No se vuelve a molestar al administrador");
reiniciar();
await pulsa(AMIGA, "Lucia", "carteras");
assert.ok(llamadas.some((l) => l.metodo === "answerCallbackQuery" && /acceso/.test(l.text)));
assert.equal(enviadosA(AMIGA).length, 0, "Sin acceso no ve datos");
// Alguien sin acceso no puede aprobarse a sí misma
await pulsa(AMIGA, "Lucia", `ok:${AMIGA}`);
assert.equal(JSON.parse(kv.get(`u:${AMIGA}`)).estado, "pendiente");

// 3. El administrador entra directamente
reiniciar();
await mensaje(ADMIN, "Javi", "/start");
const [bienvenida, menuAdmin] = enviadosA(ADMIN);
assert.match(bienvenida.text, /no una recomendación de inversión/);
htmlValido(bienvenida.text);
assert.ok(botonesDe(menuAdmin).some((b) => b.callback_data === "usuarios"), "El administrador ve la gestión de personas");
assert.ok(botonesDe(menuAdmin).some((b) => b.url === DATOS.panel || !DATOS.panel));

// 4. Aprueba a la desconocida desde el aviso
reiniciar();
await pulsa(ADMIN, "Javi", `ok:${AMIGA}`, solicitud.text);
assert.equal(JSON.parse(kv.get(`u:${AMIGA}`)).estado, "aprobado");
assert.match(enviadosA(AMIGA)[0].text, /Hola, Lucia/);
assert.ok(!botonesDe(enviadosA(AMIGA)[1]).some((b) => b.callback_data === "usuarios"), "Los demás no ven la gestión");
assert.match(enviadosA(ADMIN)[0].text, /Has dado acceso a/);

// 5. Navega por todas las pantallas
const nombres = DATOS.carteras.map((c) => c.nombre);
const acciones = ["menu", "carteras", "todas", "noticias", "top:0", "top:1", "como:0", "como:1", "como:2", "glosario",
  ...nombres.flatMap((n) => [`c:${n}`, `por:${n}:0`, `por:${n}:1`, `por:${n}:9`, `mov:${n}`]), "c:no-existe", "raro"];
for (const accion of acciones) {
  reiniciar();
  await pulsa(AMIGA, "Lucia", accion);
  const [pantalla] = enviadosA(AMIGA);
  assert.equal(pantalla.metodo, "editMessageText", accion);
  htmlValido(pantalla.text);
  assert.ok(botonesDe(pantalla).length > 0, `${accion} debe tener botones para volver`);
}
reiniciar();
await pulsa(AMIGA, "Lucia", `c:${nombres[0]}`);
assert.match(enviadosA(AMIGA)[0].text, /Hoy vale/);
reiniciar();
await pulsa(AMIGA, "Lucia", "usuarios");
assert.doesNotMatch(enviadosA(AMIGA)[0].text, /Personas/, "La gestión de personas es solo para el administrador");

reiniciar();
await pulsa(AMIGA, "Lucia", "noticias");
const pantallaNoticias = enviadosA(AMIGA)[0].text;
if (!ruta) {
  assert.match(pantallaNoticias, /tendencia bajista/);
  assert.match(pantallaNoticias, /Reserva Federal &amp; los tipos &lt;hoy&gt;/);
  assert.ok(pantallaNoticias.indexOf("🔴") < pantallaNoticias.indexOf("🟠"), "Las graves primero");
  reiniciar();
  assert.match(pantallaNoticias, /Lo que está moviendo a los sectores/);
  assert.match(pantallaNoticias, /Aranceles.*perjudica a Industria, Materiales.*Tus empresas afectadas: T3/);
  assert.match(pantallaNoticias, /→ rebaja sus previsiones &amp; más/);
  reiniciar();
  await pulsa(AMIGA, "Lucia", "por:diaria:0");
  const porque = enviadosA(AMIGA)[0].text;
  assert.match(porque, /🔴 Empresa 0 &lt;cuts&gt; guidance/);
  assert.match(porque, /Cada día se ordenan 820 empresas/);
  assert.match(porque, /🧭 Además, sus noticias la bajan 5 puestos/);
  assert.match(porque, /→ rebaja sus previsiones/);
}

// 6. Comandos escritos
for (const cmd of ["/carteras", "/ranking", "/ayuda", "/menu", "texto cualquiera"]) {
  reiniciar();
  await mensaje(AMIGA, "Lucia", cmd);
  assert.equal(enviadosA(AMIGA).length, 1, cmd);
  htmlValido(enviadosA(AMIGA)[0].text);
}

// 7. Avisos: se reparten a quien tiene acceso y los tiene activados
await mensaje(OTRO, "Pepe", "/start");   // pendiente: no debe recibir avisos
reiniciar();
await pulsa(AMIGA, "Lucia", "avisos");
assert.equal(JSON.parse(kv.get(`u:${AMIGA}`)).avisos, false);
const notificar = (texto) => worker.fetch(new Request("https://bot.test/notificar", {
  method: "POST", headers: { Authorization: "Bearer secreto" }, body: JSON.stringify({ texto }),
}), env);
reiniciar();
let r = await (await notificar("🔔 <b>Movimientos</b>")).json();
assert.equal(r.enviados, 1);
assert.equal(enviadosA(ADMIN).length, 1);
assert.equal(enviadosA(AMIGA).length, 0, "Con los avisos desactivados no recibe nada");
assert.equal(enviadosA(OTRO).length, 0, "Pendiente: no recibe avisos");
assert.equal(botonesDe(enviadosA(ADMIN)[0])[0].callback_data, "abrir");
await pulsa(AMIGA, "Lucia", "avisos");
reiniciar();
const largo = Array.from({ length: 400 }, (_, i) => `Línea ${i} con texto de relleno`).join("\n");
r = await (await notificar(largo)).json();
assert.equal(r.enviados, 2);
assert.ok(enviadosA(AMIGA).length >= 2, "Un aviso largo se parte en varios mensajes");
assert.ok(enviadosA(AMIGA).every((l) => l.text.length <= 4096));
// "Abrir menú" desde un aviso envía un mensaje nuevo (no edita el aviso)
reiniciar();
await pulsa(AMIGA, "Lucia", "abrir");
assert.equal(enviadosA(AMIGA)[0].metodo, "sendMessage");

// 8. El administrador quita el acceso desde su pantalla de personas
reiniciar();
await pulsa(ADMIN, "Javi", "usuarios");
const gestion = enviadosA(ADMIN)[0];
assert.ok(botonesDe(gestion).some((b) => b.callback_data === `no:${AMIGA}`));
assert.ok(botonesDe(gestion).some((b) => b.callback_data === `ok:${OTRO}`));
reiniciar();
await pulsa(ADMIN, "Javi", `no:${AMIGA}`, gestion.text);
assert.equal(JSON.parse(kv.get(`u:${AMIGA}`)).estado, "rechazado");
assert.match(enviadosA(AMIGA)[0].text, /no tienes acceso/);
reiniciar();
await mensaje(AMIGA, "Lucia", "/menu");
assert.match(enviadosA(AMIGA)[0].text, /no tienes acceso/);

// 9. Si no se pueden leer los datos, se dice claramente
const fetchBueno = globalThis.fetch;
globalThis.fetch = async (url, o) => (String(url).includes("datos.test") ? new Response("", { status: 500 }) : fetchBueno(url, o));
reiniciar();
await pulsa(ADMIN, "Javi", "carteras");
assert.match(enviadosA(ADMIN)[0].text, /no puedo leer los datos/);
globalThis.fetch = fetchBueno;

// 10. /configurar apunta el webhook al propio Worker con la clave
reiniciar();
await worker.fetch(new Request("https://bot.test/configurar"), env);
const hook = llamadas.find((l) => l.metodo === "setWebhook");
assert.equal(hook.url, "https://bot.test/telegram");
assert.equal(hook.secret_token, "secreto");

for (const t of [..._interno.COMO_FUNCIONA, _interno.GLOSARIO, _interno.BIENVENIDA("Ana")]) htmlValido(t);
console.log(`TODAS LAS PRUEBAS DEL BOT PASAN ✅ (${ruta ? "datos reales" : "datos inventados"})`);
