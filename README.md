# JarvisCode

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║                      ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗                 ║
║                      ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝                 ║
║                      ██║███████║██████╔╝██║   ██║██║███████╗                 ║
║                 ██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║                 ║
║                 ╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║                 ║
║                  ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝                 ║
║                                                                              ║
║                                  C  O  D  E                                  ║
║                                                                              ║
║      te escucha  ──▶  transcribe  ──▶  PIENSA Y ACTÚA  ──▶   te habla        ║
║      wake word         whisper          Claude Code           piper          ║
║      tu máquina       tu máquina         TU CUENTA          tu máquina       ║
║                                                                              ║
║           Le hablas. Claude Code trabaja. Oyes lo que va haciendo.           ║
║                de tu máquina solo sale el texto ya transcrito                ║
║                                                                              ║
║            1518 tests  ·  4 temas  ·  2 idiomas  ·  solo Windows             ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

<p align="center">
  <img alt="Licencia MIT" src="https://img.shields.io/badge/licencia-MIT-blue">
  <img alt="Python 3.11" src="https://img.shields.io/badge/python-3.11-informational">
  <img alt="Plataforma Windows" src="https://img.shields.io/badge/plataforma-Windows-lightgrey">
  <img alt="Idiomas" src="https://img.shields.io/badge/idiomas-es%20%7C%20en-success">
</p>

JarvisCode no razona: razona Claude Code, con la cuenta y el cupo de
quien lo instala. Este proyecto es la capa que permite hablarle y
escucharle. Se dice *«hey jarvis»*, se habla con normalidad, y la consola
muestra —y la voz narra— lo que ocurre en el proyecto.

**La capa de voz corre íntegramente en local.** La palabra de activación,
la detección de actividad vocal, la transcripción y la síntesis se
ejecutan en la máquina del usuario. Lo único que sale de ella es el
**texto ya transcrito**, es decir, exactamente lo que se habría escrito a
mano en la terminal de Claude Code.

---

## Índice

1. [Advertencias previas a la instalación](#advertencias-previas-a-la-instalación)
2. [Alcance funcional](#alcance-funcional)
3. [Requisitos](#requisitos)
4. [Instalación](#instalación)
5. [Puesta en marcha](#puesta-en-marcha)
6. [Modelo de seguridad: el suelo y la puerta](#modelo-de-seguridad-el-suelo-y-la-puerta)
7. [Uso con una cuenta propia de Claude Code](#uso-con-una-cuenta-propia-de-claude-code)
8. [Estructura del proyecto](#estructura-del-proyecto)
9. [Pruebas](#pruebas)
10. [Licencia](#licencia)
11. [Appendix: English mode](#appendix-english-mode)

---

## Advertencias previas a la instalación

Cuatro puntos que conviene leer antes de instalar. Ninguno es letra
pequeña.

### 1. El proyecto envía datos a la nube

No se trata de telemetría: se envían **las órdenes del usuario** y **el
contenido de los archivos que Claude Code lea para cumplirlas**. El audio
no sale nunca de la máquina; el texto transcrito sí, y con él lo que
contengan los archivos que la sesión abra.

Quien necesite un asistente estrictamente local no debería instalar esto.
JarvisCode deriva de un proyecto anterior cuyo cerebro era un modelo
local; ese diseño y este son incompatibles por definición.

### 2. Funciona con la cuenta y el cupo del usuario

JarvisCode no incluye ningún acceso a Claude. Utiliza el binario `claude`
que el usuario haya instalado y la sesión que él mismo haya iniciado.
Cada turno consume de su plan.

Conviene subrayar un riesgo concreto: **un asistente de voz siempre
encendido puede consumir cupo sin supervisión**. Por eso el sistema
arranca mudo —hasta la primera orden no se abre ninguna sesión ni sale
nada de la máquina— y por eso la consola muestra el consumo de las dos
ventanas de cuota, la de sesión y la semanal.

### 3. Actúa sobre el equipo de forma real

Escribe archivos, ejecuta comandos y lanza programas. Existen una puerta
de aprobación y un suelo de zonas protegidas (véase
[Modelo de seguridad](#modelo-de-seguridad-el-suelo-y-la-puerta)), pero
**la responsabilidad de lo que se le pida es del usuario**: los términos
de Anthropic establecen que responde de *«the actions you direct»*, y
este software se distribuye **sin garantía de ningún tipo**. La cláusula
de [`LICENSE`](LICENSE) no es una fórmula: significa que un borrado no
deseado es un problema de quien lo ordenó.

### 4. Solo funciona en Windows

La ventana emplea el runtime WebView2 que Windows incorpora de fábrica,
el audio va por DirectSound y las rutas son de Windows. No existe port a
macOS ni a Linux, ni está previsto.

---

## Alcance funcional

### Lo que hace

| Capacidad | Detalle |
|---|---|
| **Manos libres** | Palabra de activación, no un atajo de teclado. |
| **Lectura en voz alta** | La respuesta, íntegra o resumida a una o dos frases. |
| **Narración del trabajo** | Cuenta lo que hace mientras lo hace, y un visor muestra el contenido de cada archivo *escribiéndose*. |
| **Interrupción por voz** | La orden «para» corta la cadena de herramientas en curso, no solo la locución. |
| **Consola local** | En `127.0.0.1`, con el flujo completo: escribir un turno, responder una pregunta, aprobar o denegar. |
| **Cambio de proyecto hablando** | Contra un registro explícito definido por el usuario. |
| **Aviso por Telegram** | Cuando el sistema pregunta algo y el usuario no está presente. |

### Lo que no hace

| Limitación | Detalle |
|---|---|
| **No funciona sin conexión** | No hay modo degradado ni cerebro local de reserva: se comporta como Claude Code, devuelve error de conexión y espera. Es una decisión de diseño, no una carencia. |
| **No gestiona credenciales** | No solicita ningún token, no lo almacena y no lo reenvía. Se apoya en que `claude` ya esté autenticado. |
| **No captura la pantalla** | Solo recibe lo que una herramienta haya devuelto ya. |
| **No admite órdenes por Telegram** | Únicamente permite responder preguntas, eligiendo un número entre las opciones que redactó el propio modelo. |

---

## Requisitos

| Requisito | Observaciones |
|---|---|
| Windows 10 u 11 | Con el runtime **WebView2**, incluido de fábrica. |
| **Python 3.11** | No 3.12 ni 3.13: la capa de voz carece de ruedas para versiones más nuevas. |
| **Claude Code** instalado y autenticado | Verificado contra `claude 2.1.263`. |
| Cuenta de Claude (Pro o Max) | Los turnos se descuentan del cupo del usuario. |
| Un micrófono que no sea virtual | Véase la nota siguiente. |

> **El micrófono no se deduce automáticamente, y la razón está medida.**
> En la máquina de desarrollo, **16 de los 23 endpoints de audio** son
> cables virtuales que entregan silencio digital perfecto **sin devolver
> ningún error**. Por eso la entrada se declara por nombre y existe un
> botón para probarla en la pestaña de ajustes. La salida sí puede seguir
> al dispositivo predeterminado de Windows: si el audio se dirige al
> destino equivocado se advierte de inmediato; si la entrada está muda,
> no.

---

## Instalación

El proyecto requiere dos componentes que no instala por su cuenta:
**Python 3.11** —esa versión en concreto— y **Claude Code**, con una
cuenta activa.

Con ambos disponibles, la instalación son dos ejecuciones:

```
instalar.bat      crea el entorno, instala dependencias y descarga los modelos
jarvis.bat        arranca la aplicación
```

El equivalente manual, para inspección o para adaptarlo:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts\bajar_modelos.py
```

`instalar.bat` no es un simple envoltorio de esas tres órdenes:
**comprueba el entorno e informa de lo que falta**, que es donde suele
interrumpirse una instalación. Verifica la versión de Python antes de
crear nada, detecta si Claude Code está presente y, si `pip` falla porque
un antivirus intercepta HTTPS, reintenta contra el almacén de
certificados de Windows. Es idempotente: lo ya realizado no se repite y,
**si algo falla, no informa de una instalación correcta**.

> **Los modelos son dos descargas y residen en ubicaciones distintas**,
> motivo por el cual existe `scripts/bajar_modelos.py` en lugar de dos
> órdenes sueltas. La voz de Piper (60 MB) se instala en `modelos/piper`,
> dentro del proyecto. Los modelos de openWakeWord (20 MB) se instalan
> **dentro del entorno virtual** e incluyen tanto la palabra de
> activación como `silero_vad.onnx`, que es el detector de actividad
> vocal completo; por eso `requirements.txt` no instala el paquete
> `silero-vad` de PyPI, que arrastraría PyTorch para hacer lo mismo. Sin
> estos modelos, el modo `--voz` no arranca. Al rehacer el entorno
> virtual se pierden, y basta con volver a ejecutar el script.

`faster-whisper` descarga el modelo `small` por su cuenta la primera vez
que se transcribe.

El instalador descarga **una** voz, la de fábrica. Las demás se añaden
cuando se desee con `python -m piper.download_voices <nombre>
--download-dir modelos\piper` y se seleccionan en la pestaña de ajustes.

Para disponer de un acceso directo en el Escritorio existe
`crear_acceso_directo.bat`. El arranque automático con Windows se activa
mediante una casilla del menú de la bandeja del sistema, desactivada de
fábrica.

---

## Puesta en marcha

```powershell
:: la aplicación, sin terminal (uso habitual)
.venv\Scripts\pythonw.exe -m escritorio C:\ruta\al\proyecto --voz

:: con terminal, para observar el flujo
.venv\Scripts\python.exe -m puente C:\ruta\al\proyecto --voz

:: sin voz, solo la consola
.venv\Scripts\python.exe -m puente C:\ruta\al\proyecto
```

En el primer arranque el sistema genera su propia configuración e informa
de su ubicación. **El resto se configura en la pestaña de ajustes**: no
es necesario editar ningún archivo YAML a mano.

La consola queda disponible en `http://127.0.0.1:8731`.

> **La palabra de activación se pronuncia a la inglesa.** Hay que decir
> «hey jarvis» con la J de *«yema»*, porque el modelo de activación se
> entrenó en inglés. Medición con la voz de desarrollo: **20/20 en
> silencio, 14/20 con música y 9/20 tecleando**. En modo inglés esta
> advertencia deja de aplicarse.

---

## Modelo de seguridad: el suelo y la puerta

Son los dos mecanismos que distinguen este proyecto de confiar en la
buena disposición del modelo.

### El suelo

Un conjunto de zonas bloqueadas **aguas arriba**, en la configuración de
permisos del propio Claude Code, de modo que cubren incluso aquello que
el modelo no llega a preguntar. Las zonas se **detectan** en cada
arranque —35 obligatorias en la máquina de desarrollo— y cada una viaja
con el GUID de su volumen, porque una letra de unidad puede cambiar y la
regla se evaporaría en silencio.

Se organiza en dos ejes, no en una lista única:

| Eje | Lectura | Escritura |
|---|---|---|
| **Zona de sistema** | permitida | bloqueada |
| **Zona privada** | bloqueada | bloqueada |

**JarvisCode se niega a arrancar si el suelo no está en condiciones.**

### La puerta

Es lo que sí llega a preguntarse. Por defecto no interrumpe: se responde
de forma automática e inmediata, salvo que la acción caiga en una lista
corta de operaciones irreversibles —borrado, `git push`, `rm -rf`, un
servidor MCP no autorizado—. En ese caso **la aprobación se solicita en
voz alta y se contesta hablando**, con una frase derivada de los mismos
datos que pinta la pantalla, de modo que ambas representaciones no puedan
nombrar cosas distintas.

Admite **tres respuestas, no dos**: guardar silencio deja la puerta
pendiente, porque denegar por silencio convertiría «no estaba delante» en
«dijo que no».

Este comportamiento puede desactivarse por proyecto mediante la propiedad
`auto`. Cuando está desactivado, la cabecera de la consola lo indica de
forma permanente: **SIN FRENO**.

---

## Uso con una cuenta propia de Claude Code

Esta sección se contrastó con la documentación de Anthropic el
**2026-09-08**, en concreto con las
[Trademark Guidelines](https://www.anthropic.com/legal/trademark-guidelines)
y con la
[página legal de Claude Code](https://code.claude.com/docs/en/legal-and-compliance).
No constituye asesoramiento legal: los términos cambian y la
interpretación aplicable es la de Anthropic, de modo que conviene
verificarlo antes de instalar.

**Lo que hace JarvisCode**, en términos precisos:

- Ejecuta el binario `claude` **ya instalado y sin modificar**, en modo no
  interactivo (`claude -p`). No lo distribuye, no lo parchea y no altera
  ninguno de sus métodos de autenticación.
- **No interpone ningún servidor propio.** Todo se ejecuta en la máquina
  del usuario, contra su sesión.
- **No manipula credenciales.** No las solicita, no las almacena y no las
  reenvía.

Anthropic menciona este mecanismo explícitamente como uso cubierto por
una suscripción —*«The `claude -p` command in Claude Code (non-interactive
mode)»*, [Agent SDK con tu plan][sdk]— y su página legal lo formula
también en sentido inverso: *«Nor does it prevent an end user from
signing in to the unmodified Claude Code binary with their own Claude
subscription.»* ([Legal and compliance][legal])

**Lo que no está permitido hacer con este software**, tomado de esa misma
página:

> *«Customers may not pay for, resell, or intermediate Claude usage on
> their end users' behalf. Each end user must authenticate with their own
> Anthropic API key, Claude subscription plan credentials, or 3P
> inference provider credential.»*

> *«Anthropic does not permit third-party developers to offer Claude.ai
> login into their own applications, or to route requests through Free,
> Pro, or Max plan credentials on behalf of their users.»*

En resumen: **instalarlo en la propia máquina con la cuenta propia es un
uso admitido; alojarlo para terceros, o poner una suscripción a dar
servicio a varias personas, no lo es.** La licencia MIT permite modificar
y redistribuir este código, pero **no confiere ningún derecho sobre
Claude ni sobre Claude Code**; el cumplimiento de los términos de
Anthropic corresponde a quien lo utilice.

Dos advertencias adicionales, de coste antes que de cumplimiento:

- **Los límites anunciados de Pro y Max** *«assume ordinary, individual
  usage of Claude Code and the Agent SDK»* ([Legal and compliance][legal]).
  Un asistente encendido todo el día consume de esa misma bolsa.
- **El coste puede variar sin que cambie nada en este proyecto.**
  Anthropic anunció trasladar el uso de `claude -p` a una bolsa de
  créditos independiente del cupo ordinario y posteriormente **pausó** el
  cambio ([Agent SDK con tu plan][sdk], actualizado el 16-06-2026). Ante
  un comportamiento distinto del cupo, conviene consultar esa fuente
  antes que el código.

Por último: si la variable de entorno `ANTHROPIC_API_KEY` está definida,
**prevalece sobre la sesión** y la facturación pasa a la API aunque el
usuario esté autenticado con su suscripción. JarvisCode no define esa
variable, pero una heredada del sistema cambia el modo de facturación sin
previo aviso.

[sdk]: https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan
[legal]: https://code.claude.com/docs/en/legal-and-compliance

### Marcas

**Este proyecto no está afiliado a Anthropic, ni patrocinado ni
respaldado por Anthropic.** «Claude», «Claude Code» y «Anthropic» son
marcas de Anthropic PBC y aquí se citan únicamente para describir con qué
software funciona este, que es el uso que su [página legal][legal] admite
en texto plano. El nombre, el icono y la interfaz de JarvisCode son
propios.

---

## Estructura del proyecto

| Directorio | Contenido |
|---|---|
| `puente/` | El cable a Claude Code, la puerta de aprobación y la consola. |
| `voz/` | Escucha, transcripción, síntesis y las órdenes que Jarvis atiende por sí mismo. |
| `seguridad/` | El suelo de zonas protegidas y el registro local de auditoría. |
| `nucleo/` | Configuración, catálogo de ajustes, registro de proyectos y lista blanca de MCP. |
| `canales/` | Telegram como vía de aviso y de respuesta a preguntas. |
| `escritorio/` | La carcasa: ventana propia, icono de bandeja y arranque con Windows. |
| `eval/` | Bancos de pruebas y sondas de medición. |
| `tests/` | Suite de pruebas. |

**El razonamiento de cada decisión vive en el código.** Casi todas las
cifras que aparecen en los comentarios proceden de una medición anotada
con su fecha, junto al código que decidió; los comentarios explican por
qué algo es como es y qué se descartó antes de llegar ahí.

> **El registro de desarrollo no forma parte de esta distribución.** Son
> unas 10 000 líneas escritas en primera persona por su autor, con los
> nombres de sus proyectos y los dispositivos de su máquina. Eso es suyo
> y permanece en su disco. La conclusión de cada decisión está donde hace
> falta: junto al código que la aplica.
>
> Por el mismo motivo, las referencias del tipo `ADR-NNNN` y `JC-NNNN`
> que aparecen en los comentarios remiten a esos registros de decisión,
> que no se distribuyen. Funcionan como identificador estable de cada
> decisión, y lo que cada una concluyó está resumido en el comentario que
> la cita.

---

## Pruebas

```powershell
:: suite rápida
.venv\Scripts\python.exe -m pytest tests\ -m "not lento" -q

:: la que consume red y cupo
.venv\Scripts\python.exe -m pytest tests\ -m lento -q
```

Medición del 2026-09-09 sobre un clon real, con su propio entorno virtual
recién creado —no con el de la máquina de desarrollo, que fue el
procedimiento de la primera pasada y ocultaba un fallo:

| Estado del clon | Resultado |
|---|---|
| Dependencias instaladas, **sin los modelos** | 1440 pasan · 54 saltados · 0 fallos |
| **Tras `instalar.bat`**, sin micrófono seleccionado | 1468 pasan · 32 saltados · 0 fallos |
| Máquina de desarrollo, con las cinco voces y todo configurado | 1518 pasan · 1 saltado · 0 fallos |

**Ningún fallo en los tres escenarios**, y cada prueba saltada indica qué
le falta y con qué orden se resuelve. Lo que varía entre filas son
componentes todavía no instalados, no componentes rotos: los modelos de
escucha, el micrófono sin seleccionar, las voces que el instalador no
descarga y el corpus de audio, que no se publica. Que aparecieran como
fallos fue precisamente lo que se corrigió el 2026-09-09: quien encuentra
17 errores en su primera instalación no lee 17 mensajes.

Hay además 14 pruebas marcadas como `lento` porque invocan a Claude Code
de verdad; consumen red y cupo, y por eso no se ejecutan en la suite
ordinaria.

> **Las grabaciones de voz no se publican, y es deliberado.** Las cifras
> de la capa de voz —WER del 2,4 %, 27 de 30 órdenes perfectas, 20 de 20
> activaciones en silencio— se midieron contra 184 archivos WAV con la
> voz de su autor y tomas de silencio de su habitación. Ese material es
> suyo y permanece en su disco. Los bancos de `eval/` **saben grabar el
> del usuario** (`-m eval.stt_bench --grabar`), que además es lo
> correcto: un banco medido con otra voz no dice nada de la propia.

---

## Licencia

MIT. Véase [`LICENSE`](LICENSE). El software se entrega **tal cual, sin
garantías de ningún tipo**.

---

## Appendix: English mode

Jarvis ships a complete English channel — wake word, transcription, stop
words and a Piper voice — enabled under **SETTINGS → the language it
speaks and hears you in**. It is a separate channel from Spanish:
choosing it switches the decoding language and the vocabulary anchor
together.

**What it does not have is numbers, and that is a decision rather than a
pending task.** Every measured figure in this project comes from its
author's own voice in his own room, and he does not speak English to
Jarvis. The English bench can therefore only be recorded by somebody who
actually uses it that way. If that is you, it takes about fifteen minutes
and the tooling already ships:

```powershell
:: 1. is the English path wired? (30 s, no recording)
.venv\Scripts\python.exe -m eval.sonda_ingles

:: 2. the bench: 30 dictated orders, stops included
.venv\Scripts\python.exe -m eval.stt_bench --grabar --idioma en

:: 3. the wake word: 20 activations, in silence AND with music AND
::    while typing -- those last two are where Spanish dropped to
::    14/20 and 9/20. --guardar keeps the wavs so step 4 can reuse them
.venv\Scripts\python.exe -m eval.wake_bench --activaciones 20 --con-voz --guardar

:: 4. turn what you measured into the setting Jarvis actually uses
.venv\Scripts\python.exe -m eval.wake_bench --calibrar --idioma en
.venv\Scripts\python.exe -m eval.wake_bench --calibrar --idioma en --aplicar
```

**Step 4 is the point of all this.** It reads both halves — the
activations just recorded, and how close the wake word came to firing on
the dictated orders, which are audio that is *not* the wake word — and
proposes a threshold. With `--aplicar` it writes `voz.wake_word.umbral`
into `config/ajustes.yaml`, which is what `voz.wake.Wake` reads at
startup. Restart Jarvis and it takes effect. No YAML editing.

> **It refuses to recommend from half a measurement, and that is
> deliberate.** With only the activations, the "best" threshold is always
> the lowest one that fits — the one that wakes Jarvis up on its own.
> Here a false positive is not an annoyance: it is a window opening by
> itself, transcribing the room and sending whatever it hears to the
> cloud as if it were an order from you. If either half is missing it
> stops and says which. And if the two distributions overlap it says
> **that**, instead of inventing a midpoint where no boundary exists.
>
> Both verdicts were checked against the author's real recordings: saying
> *hey jarvis* the Spanish way, the distributions overlap (weakest good
> attempt 0.018, loudest non-word audio 0.066) and it refuses; saying it
> with the English J they separate (0.917 against 0.100) and it proposes
> **0.51** — landing on the 0.5 a human had picked by hand in August,
> from a different direction.

Run these **from your own terminal**: whoever dictates needs to see which
phrase comes next. Recordings land in `eval/audio_ordenes_en/` and are
git-ignored, so they stay yours.

**Two questions such a recording would settle**, and neither can be
answered from a desk:

- **Does the "English J" requirement disappear?** In Spanish you must say
  *hey jarvis* with the English J, because `hey_jarvis_v0.1` was trained
  in English. In English mode that should stop being necessary. Nobody
  has verified it.
- **Is a two-word window the right one for stop words?** English does not
  mark the imperative, so `stop the server` is an order while `stop` is a
  stop. The window separating them is **reasoned, not measured** —
  `LexicoDeParada.medido` is `False` for English, and a test forbids
  flipping it until the recordings exist. The textual half is already
  settled: 30/30 over the whole corpus, three traps included.

> **Do not generate that bench with a TTS voice, however native it
> sounds.** It was measured: synthetic audio scored **0.994–0.998** on
> the wake word against a 0.5 threshold, and **WER 0.0 %** on the STT —
> easier than the author's real Spanish at 2.4 %. It sits at the ceiling,
> and for a wake word whose models are trained on synthesised speech it
> is circular besides. Synthetic audio has its own path here
> (`-m eval.preparar_audio`, then `--sintetico`), and the bench prints a
> banner declaring it a **regression net**, never a bench.
