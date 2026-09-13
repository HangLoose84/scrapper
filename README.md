# 🎯 Deal Hunter Bot

Bot asíncrono que detecta **errores de precio y tarifas anómalas en tiempo real**.

Vigila los productos que le indiques y avisa por Telegram cuando uno cae de forma anómala
respecto de su propio historial. Sirve tanto para cazar ofertas reales como *pricing errors*:
esos casos en que una tienda publica un producto de $1.300.000 a $130.000 por un cero de menos
y lo corrige en minutos.

No está atado a ninguna tienda ni vertical: un target es una URL más una regla de extracción,
así que funciona igual sobre un `<span>` de HTML que sobre un endpoint JSON.

---

## ✨ Características principales

### Arquitectura orientada a eventos
Todos los targets se consultan **en paralelo** en cada ciclo mediante `asyncio.gather`. Un
target lento no bloquea a los demás, y un target caído no interrumpe el ciclo.

### Manejo resiliente de red (backoff exponencial)
Ante timeouts, `429` y `5xx` reintenta con esperas de 2s, 4s y 8s. Si la respuesta trae cabecera
`Retry-After`, **respeta ese tiempo** en lugar del backoff, con un tope de 5 minutos para que un
servidor hostil no pueda dejar el bot dormido un día entero.

Lo que no se reintenta también importa: un selector que no matchea nada o un `404` fallan al
primer intento. Son configuración rota, no un problema de red, y reintentar solo castiga al sitio.

### Deduplicación de alertas con estado edge-triggered en SQLite
Se avisa **una sola vez por caída**. Si el precio se queda bajo, no te spamea cada minuto; si se
recupera por encima del umbral, el estado se limpia y una nueva caída la semana que viene vuelve
a avisar. Ese estado vive en SQLite, así que reiniciar el bot no genera alertas duplicadas.

### Administración dinámica vía FSM en Telegram
Los targets se agregan, listan y eliminan desde el propio chat con una máquina de estados que
te guía paso a paso. No hace falta editar archivos ni reiniciar: el motor relee los targets en
cada ciclo. El acceso está restringido a un único usuario.

### Detección por mediana, no por precio anterior
```
caída = (mediana_histórica − precio_actual) / mediana_histórica
```
La mediana, y no el promedio, porque una liquidación puntual en el historial no debe mover la
línea base. Si la caída supera `DROP_THRESHOLD`, salta la alerta.

---

## 🛠️ Tecnologías

| Tecnología | Rol |
|---|---|
| **Python 3.12** | Lenguaje base (compatible desde 3.11). |
| **AsyncIO** | Concurrencia del motor y del bot en un solo proceso. |
| **Aiohttp** | Networking asíncrono hacia las tiendas. |
| **Selectolax** | Parseo de HTML ultrarrápido, muy por encima de BeautifulSoup. |
| **Aiogram 3** | Interfaz de bot: comandos, botones inline y FSM. |
| **SQLite** (SQLAlchemy async + aiosqlite) | Historial de precios, estado de alertas y targets. |
| **Pydantic / pydantic-settings** | Configuración y modelos validados al arrancar. |

---

## 📦 Instalación

Requiere **Python 3.11 o superior** (desarrollado sobre 3.12) y Windows para el supervisor.
El bot en sí es multiplataforma.

```bash
# Clonar
git clone https://github.com/HangLoose84/scrapper.git
cd scrapper

# Crear el entorno virtual
python -m venv .venv

# Activarlo (Windows)
.\.venv\Scripts\activate

# Instalar dependencias
pip install aiohttp aiogram aiosqlite pydantic pydantic-settings selectolax "sqlalchemy[asyncio]"
```

### Configuración

```bash
cp .env.example .env
```

Necesitás tres datos de Telegram:

1. **`TELEGRAM_TOKEN`** — escribile a [@BotFather](https://t.me/BotFather), `/newbot`, y copiá el token.
2. **`TELEGRAM_CHAT_ID`** — mandale un mensaje a tu bot y abrí
   `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`. El número está en `message.chat.id`.
3. **`TELEGRAM_OWNER_ID`** — tu user id. En un chat privado es el mismo número que el anterior.

> ⚠️ `TELEGRAM_OWNER_ID` es el control de acceso: **cualquier otro usuario que le escriba al bot
> es ignorado en silencio**. Si lo dejás vacío, nadie puede usar `/menu`, ni vos.

---

## ▶️ Ejecución

**Foreground** — para probar y ver los logs en vivo:

```bash
python main.py
```

**Background resiliente** — supervisor que reinicia el proceso si muere, con backoff exponencial
de 10s a 5 minutos y reseteo automático del contador si el bot se mantiene estable 5 minutos:

```bash
.\run_bot.ps1
```

### 24/7 al iniciar sesión en Windows

```powershell
$here    = (Get-Location).Path
$argline = '-ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f (Join-Path $here 'run_bot.ps1')
$action  = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argline -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -AtLogOn
$set     = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'Deal_Hunter_Bot' -Action $action -Trigger $trigger -Settings $set -Force
```

`-ExecutionTimeLimit 0` es obligatorio: por defecto el Programador de tareas de Windows mata
cualquier tarea a los 3 días.

---

## 💬 Uso desde Telegram

Mandale `/menu` al bot:

| Botón | Qué hace |
|---|---|
| 📋 Listar | Muestra los targets con su regla de extracción. |
| ➕ Agregar | Diálogo paso a paso: nombre → URL → tipo → ruta/selector → atributo. |
| ❌ Eliminar | Lista los targets como botones; tocás uno y se borra. |

`/cancelar` aborta el alta en cualquier punto.

### Los dos tipos de target

**HTML** — cuando el precio está en la página:

| Campo | Ejemplo |
|---|---|
| `css_selector` | `p.internet span.price-value` |
| `css_attribute` | `data-value` *(opcional)* |

Si dejás el atributo vacío se lee el texto visible, asumiendo **formato CLP** (`$1.369.990`:
puntos como separador de miles, sin centavos). Preferí el atributo cuando exista:
`data-value="1369990.0"` ya viene en formato máquina y no depende de cómo se muestre el precio.

**JSON** — cuando la tienda tiene una API:

| Campo | Ejemplo |
|---|---|
| `json_path` | `data.price`, o `items.0.price` para entrar a una lista |

Los dos campos son **mutuamente excluyentes**: el modelo Pydantic rechaza un target que traiga
ambos o ninguno, antes de que llegue a la base de datos.

> 💡 **Para encontrar el selector**, abrí la página, click derecho sobre el precio →
> *Inspeccionar*. Si el precio no aparece en el HTML, la tienda lo dibuja con JavaScript: buscá
> en la pestaña *Network* si hay un endpoint JSON detrás y usá `json_path`.

---

## 📁 Estructura

```
main.py           Entrypoint: arranca el polling de Telegram y el loop de precios en paralelo
config.py         Settings y el modelo Target (con la validación de exclusión mutua)
scraper.py        Descarga y extracción, con retry/backoff y Retry-After
storage.py        SQLite: historial, estado de alertas y CRUD de targets
notifier.py       Envío de alertas por Telegram
bot_ui.py         /menu, la FSM de alta y el filtro de acceso por owner
core/anomaly.py   El cálculo de la caída contra la mediana
core/engine.py    El ciclo: scrapear → guardar → comparar → alertar
run_bot.ps1       Supervisor con backoff exponencial
tests/            Tests del CRUD y del control de acceso
```

## 🧪 Tests

```bash
python tests/test_storage.py
python tests/test_access.py
```

Sin framework: asserts planos que corren con `python` directamente (y también bajo `pytest`).

---

## 🔒 Seguridad

- `.env` está en `.gitignore` y **nunca** debe commitearse: contiene el token del bot.
- Si alguna vez exponés el token, revocalo en @BotFather y generá uno nuevo.
- El bot solo obedece a `TELEGRAM_OWNER_ID`. No hay comandos administrativos abiertos.

---

## 👤 Autor

**HangLoose84**

- LinkedIn: [linkedin.com/in/hangloose84](https://www.linkedin.com/in/hangloose84/)

---

## 📄 Licencia

MIT © HangLoose84
