# Mi inversor: Fórmula Mágica + F-Score

Analiza unas 1.500 empresas de EE. UU. con el método de **Joel Greenblatt** (negocios rentables a buen precio), descarta las que tienen la salud financiera deteriorada con el **F-Score de Piotroski** y lo prueba con **dinero ficticio**. Funciona solo en la nube cada día, lo consultas en el móvil como una app y te avisa por Telegram.

> No es asesoramiento financiero. Es una herramienta para aplicar un método con disciplina; las decisiones son tuyas.

## De dónde salen los datos

- **Cuentas de las empresas:** de la **SEC**, el regulador de la bolsa de EE. UU. Son oficiales, gratuitas y llegan hasta 2009. Cada cifra lleva la fecha exacta en que se publicó, así que al simular el pasado solo se usa lo que de verdad se sabía en cada momento.
- **Precios:** Yahoo Finance (gratis).
- **Lista de empresas (S&P 1500):** Wikipedia.

## Cómo funciona el método

1. Cada empresa recibe dos notas. **Barata**: beneficio operativo ÷ valor de toda la empresa. **Rentable**: beneficio operativo ÷ capital que necesita el negocio.
2. Se ordenan por cada nota y se suman los dos puestos. Las primeras son las "buenas y baratas".
3. Se eliminan las que tienen un F-Score inferior a 5 de 9.
4. La cartera tiene 20 empresas. Cada 3 meses se compran como mucho 5 nuevas y cada una se mantiene un año; si al cumplirlo sigue entre las mejores, se queda.

Todo se puede cambiar en `config.yaml`.

---

## Puesta en marcha en la nube (gratis, unos 20 minutos)

### 1. Sube el proyecto a GitHub

1. Crea una cuenta en [github.com](https://github.com) si no tienes.
2. Pulsa **New repository**. Ponle un nombre (por ejemplo `inversor`), márcalo como **Public** y créalo.
3. En el repositorio vacío, pulsa **uploading an existing file** y arrastra **todo el contenido** de esta carpeta (no la carpeta en sí).
   - Importante: incluye la carpeta oculta `.github`. En Mac, pulsa `Cmd + Shift + .` en el Finder para ver los archivos ocultos. En Windows, en el Explorador: *Vista → Mostrar → Elementos ocultos*.
   - Comprueba después que en GitHub aparece la carpeta `.github/workflows` con dos archivos.

> **¿Por qué público?** Con la cuenta gratuita, el panel web solo se puede publicar desde un repositorio público. Cualquiera con el enlace podría ver tus carteras **ficticias**, pero nunca tus claves: van guardadas como secretos (paso 2), que GitHub no muestra a nadie.

### 2. Guarda tus datos privados como secretos

En el repositorio: **Settings → Secrets and variables → Actions → New repository secret**. Crea:

| Nombre | Valor |
|---|---|
| `SEC_CONTACTO` | Tu email. La SEC exige identificarse para descargar datos; no se usa para nada más. |
| `TELEGRAM_TOKEN` | El token de tu bot (opcional, ver más abajo) |
| `TELEGRAM_CHAT_ID` | Tu número de chat (opcional) |

### 3. Permite que las tareas guarden resultados

**Settings → Actions → General → Workflow permissions** → marca **Read and write permissions** → **Save**.

### 4. Publica el panel

**Settings → Pages** → en *Source* elige **Deploy from a branch** → rama **main**, carpeta **/docs** → **Save**. A los pocos minutos verás la dirección del panel, del estilo `https://tu-usuario.github.io/inversor/`.

Edita `config.yaml` en GitHub (icono del lápiz) y pon esa dirección en `url_panel` para que aparezca en los avisos de Telegram.

### 5. Crea tu primera cartera ficticia

**Actions → Acciones manuales → Run workflow** → elige **Crear cartera ficticia**, indica el capital y pulsa **Run workflow**.

La primera vez tarda entre 20 y 40 minutos, porque descarga las cuentas de todas las empresas. Después se reutilizan y las ejecuciones diarias duran pocos minutos.

A partir de ahí, la tarea **Actualización diaria** se ejecuta sola de lunes a viernes tras el cierre de Wall Street.

### 6. Instálalo en el móvil

Abre la dirección del panel en el móvil:

- **iPhone (Safari):** botón Compartir → **Añadir a pantalla de inicio**.
- **Android (Chrome):** menú ⋮ → **Instalar aplicación** o **Añadir a pantalla de inicio**.

Se abrirá a pantalla completa, con su icono, como cualquier app. Tiene tres pestañas: **Cartera** (cómo va tu dinero ficticio frente al S&P 500), **Ranking** (las mejores empresas de la semana) y **Pasado** (cómo te habría ido).

También puedes lanzar las acciones manuales desde el móvil con la app de GitHub.

### 7. Simula el pasado

**Actions → Acciones manuales → Run workflow → Simular el pasado.** Si dejas la fecha vacía, empieza en la más antigua con datos suficientes (hacia 2011). El resultado aparece en la pestaña **Pasado** del panel.

---

## Alertas en Telegram (opcional)

1. En Telegram, habla con **@BotFather**, escribe `/newbot` y sigue los pasos. Te dará un *token*.
2. Escribe cualquier mensaje a tu nuevo bot. Después abre `https://api.telegram.org/bot<TU_TOKEN>/getUpdates` en el navegador y busca el número que aparece en `"chat":{"id": ...}`.
3. Guarda ambos como secretos (paso 2).

**Qué te avisa:** cada lunes, un resumen de cómo van las carteras, las mejores empresas explicadas en lenguaje sencillo, cuáles entran y salen del top y alertas si alguna acción que tienes baja del F-Score mínimo. Además, cualquier día en que una cartera ficticia compre o venda, con el porqué de cada operación. Si tienes acciones de verdad, ponlas en `mis_acciones` dentro de `config.yaml` y también las vigilará.

### Bot interactivo con botones (opcional)

Con lo anterior, el bot solo envía avisos. La carpeta `bot/` contiene un bot completo que se instala gratis en **Cloudflare Workers**. Ofrece:

- **Bienvenida** con la explicación del método y sus límites.
- **Menús con botones**: ver cada cartera o todas a la vez, el porqué de cada empresa, los últimos movimientos, las mejores empresas del ranking, cómo funciona y un glosario.
- **Acceso privado**: cuando alguien escribe al bot, te llega un aviso para aprobarlo o rechazarlo. Puedes quitar el acceso cuando quieras desde *Personas con acceso*.
- **Avisos para todas las personas aprobadas.** Cada una puede activarlos o desactivarlos.

El bot lee las carteras de `docs/bot.json`, que se publica en cada ejecución. Para instalarlo, con [Node.js](https://nodejs.org) y una cuenta gratuita de Cloudflare, desde la carpeta `bot/`:

1. `npx wrangler@4 login`
2. `npx wrangler@4 kv namespace create USUARIOS` y copia el `id` que te da en `wrangler.toml`.
3. `npx wrangler@4 deploy`. Apunta la dirección `https://inversor-bot.<algo>.workers.dev`.
4. Guarda los secretos del Worker:
   - Copia el token del bot y ejecuta `pbpaste | npx wrangler@4 secret put TELEGRAM_TOKEN` (en Mac).
   - `printf TU_CHAT_ID | npx wrangler@4 secret put ADMIN_CHAT_ID`
   - Crea una clave compartida y guárdala en los dos sitios:
     `S=$(openssl rand -hex 32); printf %s "$S" | npx wrangler@4 secret put BOT_SECRET && gh secret set BOT_SECRET --body "$S"`
5. En GitHub, crea el secreto `BOT_URL` con la dirección del paso 3.
6. Espera un minuto (los secretos tardan unos segundos en activarse) y abre `https://inversor-bot.<algo>.workers.dev/configurar` para conectar el bot con Telegram. Si después el bot no contesta a `/start`, vuelve a abrir esa dirección.

Para comprobar el bot sin internet: `node bot/prueba_bot.mjs`.

## Varias carteras para comparar

Puedes crear varias con nombres distintos. Las reglas de `config.yaml` se congelan en cada cartera al crearla, así que para comparar estrategias: cambia `config.yaml`, crea otra cartera, y el panel te dejará cambiar entre ellas.

### Estilos de cartera

Al crear una cartera puedes elegir el **estilo**:

- **trimestral** (por defecto): las reglas de Greenblatt. Revisa cada 3 meses y mantiene cada acción un año.
- **semanal**: revisa una vez cada 7 días. Compra las empresas que están entre las 20 mejores si hay hueco y vende en cuanto una cae fuera de las 50 mejores o deja de pasar el F-Score (`cartera_semanal`).
- **diaria**: lo mismo, pero cada día de mercado (`cartera_diaria`).
- **reactiva**: las reglas de la diaria y además reacciona al mercado y a las noticias (`cartera_reactiva`):
  - **Cada hora durante la sesión** vigila sus empresas y vende si una cae un 15 % desde su máximo desde la compra (*stop móvil*), o si sale una noticia grave (fraude, quiebra, investigación oficial…) que el mercado ya castiga con una caída del 5 % en 5 sesiones.
  - No compra empresas con noticias graves o varias negativas recientes, ni el día que caen un 7 % o más.
  - No compra nada si el índice está por debajo de su media de 200 sesiones (tendencia bajista).
  - Lo que vende por protección no lo recompra en 30 días.

Créalas con **Actions → Acciones manuales → Run workflow → Crear cartera ficticia**, eligiendo nombre y estilo. Pueden convivir y compararse en el panel. Cuanto más activa es una cartera, más opera y más comisiones paga. La simulación del pasado usa siempre las reglas trimestrales, porque no hay noticias históricas gratuitas con las que simular la reactiva.

### Noticias y parte diario

Cada día de mercado el bot envía un **parte diario** con:
- cómo ha ido el índice y su tendencia;
- cómo van las carteras hoy y desde el inicio;
- las compras y ventas, con su porqué;
- las noticias destacadas de las empresas que tienes;
- titulares de economía y geopolítica en español.

Las noticias salen de **Google News (RSS, gratuito)** y se clasifican con reglas de palabras clave (🔴 grave, 🟠 negativa, 🟢 positiva). No se usa ninguna IA ni servicio de pago. Es una clasificación sencilla que puede equivocarse, y por eso solo provoca ventas cuando el precio confirma la noticia.

---

## Uso en tu ordenador (opcional)

Con Python 3.10 o superior:

```
pip install -r requirements.txt
```

Pon tu email en `sec_contacto` dentro de `config.yaml` y usa:

| Qué quieres hacer | Comando |
|---|---|
| Ver las mejores empresas hoy | `python main.py ranking` |
| Crear una cartera ficticia | `python main.py crear --nombre prueba --capital 10000` |
| Ver tus carteras | `python main.py estado` |
| Simular el pasado | `python main.py pasado` (o `--inicio 2015-01-01`) |
| Tarea diaria con alertas | `python main.py diario` |
| Regenerar el panel | `python main.py panel` (se abre `docs/index.html`) |

Para comprobar la lógica sin internet: `python tests/prueba_sintetica.py`.

---

## Límites que debes conocer

- **Sesgo de supervivencia.** La simulación del pasado usa las empresas que están **hoy** en el S&P 1500. Las que quebraron o salieron del índice no aparecen, y las que entraron porque les fue bien sí. Eso infla el resultado: tómalo como el escenario optimista. Corregirlo bien exige datos históricos de empresas que ya no cotizan, que no son gratuitos.
- **Datos imperfectos.** Las empresas etiquetan sus cuentas de formas algo distintas. Algunas quedarán con datos incompletos y se omiten. También se omiten las que tienen sus últimas cuentas anuales de hace más de 18 meses. Revisa siempre una empresa antes de comprarla de verdad.
- **Dividendos.** En las carteras hacia delante no se suman (ni a la tuya ni al índice), así que la comparación es justa pero ambas salen algo más bajas que la realidad. En la simulación del pasado sí se incluyen.
- **Paciencia.** La Fórmula Mágica ha tenido rachas de varios años peores que el índice. Solo funciona si la sigues también cuando va mal.
- **Al invertir desde España:** asumes riesgo de cambio euro/dólar, conviene tener firmado el formulario W-8BEN con tu bróker (retención del 15 % en dividendos de EE. UU.) y cada venta con ganancia tributa en la renta.

## Si algo falla

- **En Actions aparece una cruz roja:** entra en la ejecución y abre el paso que ha fallado. El mensaje suele explicar qué ocurre. Si el mensaje habla de la SEC y de un email, falta el secreto `SEC_CONTACTO`.
- **Error de Yahoo por demasiadas peticiones:** a veces Yahoo limita a los servidores de GitHub. El programa reintenta solo; si persiste, al día siguiente suele funcionar.
- **Error al hacer `git push`:** revisa el paso 3 (permisos de escritura).
- **La tarea diaria no se ha ejecutado a la hora exacta:** GitHub puede retrasar las tareas programadas en momentos de mucha carga. Es normal.

## Estructura

```
config.yaml                 ← todas las opciones
main.py                     ← los comandos
inversor/sec.py             ← lectura de las cuentas oficiales de la SEC
inversor/datos.py           ← descargas (SEC, Yahoo, Wikipedia) y caché
inversor/puntuacion.py      ← Fórmula Mágica y F-Score
inversor/cartera.py         ← reglas de compra y venta
inversor/simulacion.py      ← dinero ficticio (hacia delante y hacia atrás)
inversor/analisis.py        ← ranking, informes y Telegram
inversor/web.py             ← panel para el móvil
.github/workflows/          ← tareas automáticas en la nube
docs/                       ← el panel publicado
carteras/, historico/       ← estado guardado entre ejecuciones
```
