"""Speech to text with faster-whisper, local and on CPU.

ADR-0001 fixes the CPU part and it is not a detail: the 6 GB of this GPU
belong to the planner, and the 5700G has 8 idle cores while the GPU is
busy planning. Putting Whisper on the GPU would buy latency in the one
place that is not the bottleneck and pay for it where it is.

The language is PINNED, never autodetected: autodetection costs a pass
over the first window and can pick wrong on a short command, which is
exactly the shape of everything the user says here.

>>> A QUE SE FIJA LO DECIDE `voz.idioma`, Y HASTA EL 2026-09-08 NO <<<
Este parrafo decia "pinned to Spanish" y era literal: `transcribir`
llevaba `idioma: str = "es"` por defecto y `escuchar()` lo llamaba SIN
pasarle nada, o sea que el canal ingles de JC-0018 decodificaba en
español. `_idioma()` -- que si lee la config -- solo se usaba para
rellenar el campo de los dos caminos que NO transcriben (sin habla y
ventana abortada), asi que `Transcripcion.idioma` decia "en" justo en
los casos vacios y "es" en los que traian texto.
LO QUE LA SONDA MIDIO, y corrige la mitad alarmista de esto: con
`language="es"` forzado, seis frases inglesas SINTETICAS salieron 5 de 6
perfectas. Whisper es multilingue y con audio limpio no se inmuta. O sea
que el cable estaba suelto de verdad y **cuanto duele no esta medido**
(6 muestras, 0 casos discriminantes: esa tanda no contesto).
Se arregla igual, porque el sitio donde se espera que duela -- voz con
acento, en una sala, con ruido -- es justo el que el sintetico no toca.
SE RESUELVE UNA SOLA VEZ, AL CONSTRUIR, y junto al ancla: las dos salen
de `voz.idioma`, y resolverlas por separado permite la combinacion
absurda de ancla inglesa decodificando en español. Un solo sitio decide.
Y por eso `voz.idioma` declara `aplica: reiniciar` en el panel: hay un
`STT` por sesion. Si algun dia se resolviera por llamada, ese `reiniciar`
pasaria a ser mentira.

WHISPER INVENTS WORDS WHEN NOBODY SPOKE. Measured here on 2026-08-20,
12 takes of real room silence through the real microphone:

    10 de 12 inventaron texto
      'Subtitulos realizados por la comunidad de Amara.org'  x6
      '!Suscribete!'                                         x3
      'No.'                                                  x1

It is trained on subtitles, so given silence it fills in. This is the
seam in its worst form yet: "nobody spoke" and "the user said this"
would leave through the same door, and what comes out the other side is
an ORDER the planner will try to carry out.

AND THE MODEL'S OWN VERDICT IS NOT ENOUGH TO STOP IT, which is the part
worth remembering. `no_speech_prob` went as low as **0.351** on those
hallucinations. A threshold that catches 0.351 would start rejecting
real speech, so there is no value that separates them. It is the rule
again -- the model's self-assessment is advice, not permission.

The guard that works is ENERGY, and it is O(1): room tone sits at the
microphone's measured noise floor and speech does not. Pass `suelo` from
`voz.audio.calibrar_suelo` and the veto applies; without it you get
transcription only, and `verdicto_fiable` says so instead of pretending.

THE REAL FIX IS UPSTREAM AND IT IS 5.3: silero decides where speech
starts and ends, and Whisper only ever sees audio that the VAD already
marked as speech. That is what the design prescribes, and
these numbers are why it is not optional.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from nucleo.configuracion import load_general_config
from voz.audio import SAMPLE_RATE_VOZ, ConfigAudio, Dispositivo, Nivel, Suelo

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Kept out of the venv for the same reason as the Piper voices:
# reinstalling dependencies must not throw away gigabytes of models.
DIR_MODELOS = PROJECT_ROOT / "modelos" / "whisper"

# Above this, the model itself says the audio is not speech. NECESSARY
# AND NOT SUFFICIENT: measured on 2026-08-20, hallucinations on pure
# silence scored as low as 0.351, so this catches most and not all. The
# energy veto below is what closes the gap, and silero closes it properly
# in 5.3.
#
# >>> HAY DOS UMBRALES PORQUE ANCLAR VOCABULARIO MUEVE LA FRONTERA. <<<
# Medido el 2026-08-21 sobre el mismo corpus (30 ordenes reales de esta
# sala y 12 tomas de su silencio), `small`, los cuatro numeros de la
# misma tanda:
#
#                 HABLA (30)              SILENCIO (12)
#     sin ancla   max 0.219        <      min 0.686
#     con ancla   max 0.031        <      min 0.490
#
# Las dos nubes SIGUEN SEPARADAS -- anclar no rompe la guarda --, pero la
# frontera se corre entera hacia abajo: el modelo se vuelve mucho mas
# seguro de que hay habla cuando la hay, y algo menos seguro de que no la
# hay cuando no la hay. Dejar el 0.6 con el ancla puesta colaria CUATRO
# de los doce silencios como si fueran ordenes, que es un fallo ABIERTO
# y del peor tipo: el texto inventado con `initial_prompt` eran palabras
# del propio vocabulario ('Escritorio,', 'Imagenes,').
#
# Por eso el umbral NO es una constante global sino una propiedad de CADA
# transcripcion, segun como se produjo. Es la leccion del 2026-08-04 otra
# vez (`formato` y `razonamiento_interno` fijados a nivel de rol): nada
# que dependa de como se hace la llamada puede fijarse fuera de ella.
#
# HONESTIDAD SOBRE LA MUESTRA: 12 silencios no bastan para el extremo de
# la distribucion. Los valores estan puestos con margen a los dos lados de
# lo medido, no pegados al dato.
UMBRAL_SIN_HABLA = 0.6
UMBRAL_SIN_HABLA_CON_ANCLA = 0.25

# El vocabulario del dominio que se le adelanta al modelo. NO son las
# frases del banco -- eso seria darle las respuestas al examen --: son las
# palabras que el usuario nombra al dar ordenes.
#
# SE USA `hotwords` Y NO `initial_prompt`, y no es indiferente aunque los
# dos midieran igual de bien (3 ordenes arregladas, 0 rotas, WER 4.2% ->
# 2.4%). La diferencia esta en QUE se inventan ante silencio, que es
# donde duele: con `initial_prompt` el modelo continua el texto y escupe
# palabras de esta misma lista ('Escritorio,', 'Imagenes,'), que parecen
# una orden; con `hotwords` escupe basura ('p.p.p.p', numeros sueltos),
# que no puede confundirse con nada. A igualdad de calidad, se elige la
# que falla de forma reconocible.
ANCLA_POR_DEFECTO = (
    "bloc de notas, Descargas, Documentos, Imagenes, Escritorio, "
    "papelera, captura, informe, factura, carpeta, archivo, "
    "navegador, calculadora, explorador, git status, pip list, PDF"
)


class STTError(RuntimeError):
    """The model is missing or the audio cannot be transcribed."""


@dataclass
class Transcripcion:
    """What was heard, and how sure the model is that anything was said.

    THREE answers, not two: `sin_habla` is not "empty text". A
    Whisper that hallucinates on silence returns confident, well-formed
    Spanish, so an empty-string check would never fire and the invented
    sentence would reach the planner as if the user had said it.
    """

    texto: str
    latencia_s: float
    duracion_audio_s: float
    prob_sin_habla: float
    idioma: str
    modelo: str
    segmentos: list[str] = field(default_factory=list)
    # El umbral con el que se juzga `prob_sin_habla`, y viaja CON la
    # transcripcion porque depende de si se anclo vocabulario al pedirla.
    umbral_sin_habla: float = UMBRAL_SIN_HABLA
    # Que ancla se uso, si se uso alguna. Informativo, para el log.
    ancla: str = ""
    # None means the check was NOT applied, which is a third state and
    # not a "yes". Collapsing it into "there was speech" is the default
    # mistake here and it fails open: an invented order.
    #
    # `hay_habla_vad` es la SEGUNDA SEÑAL desde el 2026-08-21 y sustituye
    # a `supera_suelo` en el veredicto. Medido sobre 30 ordenes reales y
    # 12 silencios reales de la misma sala: el VAD acierta 30/30 y 12/12.
    hay_habla_vad: bool | None = None
    # `sin_senal` es ABSOLUTO (rms practicamente cero) y por eso si es
    # fiable: dice "esto no es un microfono", no "nadie hablo". Caza el
    # cable de audio virtual, que entrega silencio digital perfecto
    # sin dar error.
    sin_senal: bool | None = None
    # >>> INFORMATIVO DESDE EL 2026-08-21: YA NO DECIDE NADA. <<<
    # El veto de energia comparaba el RMS del CLIP ENTERO contra el suelo
    # medido mas `MARGEN_SOBRE_SUELO_DB` (8 dB). Medido ese dia:
    #     habla    min -29.9 dBFS
    #     silencio max -30.0 dBFS   -> 0.1 dB de separacion
    # No hay margen que funcione, porque el RMS promedia el habla con sus
    # propios silencios y la hunde hasta el suelo. Y encima el suelo
    # oscila 13 dB entre calibraciones seguidas de la misma sala, asi que
    # con mala suerte el veto rechazaba las 30 ordenes: fallaba cerrado
    # de forma INTERMITENTE, que es la peor manera de fallar.
    # Se conserva el campo porque sigue siendo un buen dato de
    # diagnostico; lo que se le quito es el voto.
    supera_suelo: bool | None = None
    nivel_dbfs: float | None = None
    # COMO se cerro la ventana de dictado (JC-0013). None = la ventana
    # era fija, o sea que nadie pregunto cuando dejaste de hablar.
    # Informativo, pero es LA cifra con la que se afina el umbral de fin
    # de turno: un `tope` en uso normal significa que no cerro solo.
    cierre: str | None = None

    @property
    def verdicto_fiable(self) -> bool:
        """Whether "did anyone speak" was answered with both signals.

        False means only the model was asked, and the model alone is not
        enough: medido el 2026-08-20, `no_speech_prob` bajo a 0.351 en
        alucinaciones sobre silencio, o sea por debajo del umbral. La
        segunda señal es el VAD desde el 2026-08-21.
        """
        return self.hay_habla_vad is not None

    @property
    def sin_habla(self) -> bool:
        """Nothing was said. Conservative on purpose.

        Fails CLOSED: a false "nobody spoke" makes Jarvis ignore you,
        which is annoying; a false "the user said this" makes Jarvis act
        on an order that was never given. Only one of those is safe, so
        any one signal saying "silence" is enough to discard.
        """
        if not self.texto.strip():
            return True
        if self.sin_senal is True:
            # No es "nadie hablo" sino "esto no es un microfono", pero la
            # accion es la misma y en la direccion segura: no seguir.
            return True
        if self.prob_sin_habla >= self.umbral_sin_habla:
            return True
        return self.hay_habla_vad is False

    @property
    def factor_tiempo_real(self) -> float:
        """Seconds of audio processed per second of work."""
        return self.duracion_audio_s / self.latencia_s if self.latencia_s else 0.0

    @property
    def cumple_meta(self) -> bool:
        """The target for STT: under 1.0 s from end of speech to text."""
        return self.latencia_s < 1.0

    def describe(self) -> str:
        if self.sin_habla:
            motivo = "p_modelo" if self.prob_sin_habla >= self.umbral_sin_habla else ""
            if self.hay_habla_vad is False:
                motivo = f"{motivo}+vad" if motivo else "vad"
            if self.sin_senal is True:
                motivo = f"{motivo}+sin_senal" if motivo else "sin_senal"
            aviso = "" if self.verdicto_fiable else "  [sin VAD]"
            return (
                f"SIN HABLA ({motivo or 'vacio'}, p={self.prob_sin_habla:.2f}) en "
                f"{self.latencia_s:.2f} s. Descartado: "
                f"{self.texto.strip()!r}{aviso}"
            )
        return (
            f"{self.texto.strip()!r} en {self.latencia_s:.2f} s "
            f"({self.duracion_audio_s:.1f} s de audio, "
            f"x{self.factor_tiempo_real:.1f} tiempo real)"
        )


def modelos_descargados(directorio: Path | None = None) -> list[str]:
    """Whisper sizes already on disk, by the name faster-whisper uses."""
    carpeta = directorio or DIR_MODELOS
    if not carpeta.is_dir():
        return []
    nombres = []
    for hijo in carpeta.glob("models--Systran--faster-whisper-*"):
        nombres.append(hijo.name.rsplit("faster-whisper-", 1)[-1])
    return sorted(nombres)


class STT:
    """A loaded Whisper model, ready to transcribe.

    Loading costs seconds and gigabytes, so the instance is kept alive
    for the session instead of rebuilt per utterance.
    """

    def __init__(
        self,
        modelo: str | None = None,
        config_dir: Path | None = None,
        directorio: Path | None = None,
        compute_type: str = "int8",
        ancla: str | None = None,
        idioma: str | None = None,
    ) -> None:
        self.modelo = modelo or self._modelo_configurado(config_dir)
        self.compute_type = compute_type
        # >>> EL IDIOMA VA AQUI, PEGADO AL ANCLA, Y NO ES ORDEN <<<
        # Los dos salen de `voz.idioma`. Resolverlos en momentos
        # distintos permite la combinacion que no significa nada -- ancla
        # inglesa decodificando en español -- y esa no da error: da una
        # transcripcion peor sin decir por que.
        # `None` = lo que diga la config, que ante cualquier duda es "es"
        # (`voz.idioma.hablado`). Pasarlo explicito es para los bancos.
        self.idioma = self._idioma(config_dir) if idioma is None else idioma
        # `None` = lo que diga la config. Cadena vacia = sin ancla, a
        # proposito, y eso es distinto de "no me lo han dicho".
        self.ancla = (self._ancla_configurada(config_dir)
                      if ancla is None else ancla)
        inicio = time.perf_counter()
        try:
            from faster_whisper import WhisperModel

            self._modelo = WhisperModel(
                self.modelo,
                device="cpu",  # ADR-0001: la VRAM es del planner.
                compute_type=compute_type,
                download_root=str(directorio or DIR_MODELOS),
            )
        except Exception as exc:  # noqa: BLE001 - ctranslate2 raises broadly
            raise STTError(
                f"No se pudo cargar el modelo STT '{self.modelo}': {exc}"
            ) from exc
        self.carga_s = time.perf_counter() - inicio

    @staticmethod
    def _modelo_configurado(config_dir: Path | None = None) -> str:
        try:
            bloque = (load_general_config(config_dir) or {}).get("voz") or {}
            configurado = (bloque.get("stt") or {}).get("modelo")
        except Exception as exc:  # noqa: BLE001
            raise STTError(f"No se pudo leer config/jarvis.yaml: {exc}") from exc
        if not configurado:
            raise STTError(
                "config/jarvis.yaml no declara voz.stt.modelo. ADR-0006 se cierra "
                "MIDIENDO (small / medium / large-v3): correr "
                "`python -m eval.stt_bench`."
            )
        return str(configurado)

    @staticmethod
    def _ancla_configurada(config_dir: Path | None = None) -> str:
        """The domain vocabulary to bias the model with.

        `voz.stt.ancla_vocabulario` accepts a string or a list. Absent
        means the measured default; `false` or an empty string means the
        user turned it OFF on purpose, and that is not the same thing.
        """
        # >>> EL ANCLA ES DE IDIOMA, Y LA MEDIDA ES LA ESPAÑOLA <<<
        # La española bajo el WER de 4,2 % a 2,4 % contra las 30 ordenes
        # reales. La inglesa es la misma idea traducida y NO tiene banco
        # detras (JC-0018). Se usa igual porque vaciarla tampoco es
        # neutro -- mueve el umbral de `sin_habla`, ver arriba --, pero
        # no se puede citar como medida.
        from voz.idioma import ancla as _del_idioma

        try:
            por_defecto = _del_idioma(config_dir=config_dir)
        except Exception:  # noqa: BLE001
            por_defecto = ANCLA_POR_DEFECTO
        try:
            bloque = (load_general_config(config_dir) or {}).get("voz") or {}
            valor = (bloque.get("stt") or {}).get("ancla_vocabulario", None)
        except Exception:  # noqa: BLE001
            return por_defecto
        if valor is None:
            return por_defecto
        if valor is False:
            return ""
        if isinstance(valor, (list, tuple)):
            return ", ".join(str(v) for v in valor)
        return str(valor)

    @staticmethod
    def _idioma(config_dir: Path | None = None) -> str:
        # >>> MANDA `voz.idioma`, NO `voz.stt.idioma` <<<
        # La primera version de esto dejaba `voz.stt.idioma` por encima
        # "como escape para quien quiera transcribir en un idioma y
        # hablar en otro", y un test lo tumbo en el acto: `jarvis.yaml`
        # TRAE ESA CLAVE PUESTA A "es" desde el proyecto original. O sea
        # que el ajuste nuevo habria sido un control decorativo -- lo
        # mueves, no pasa nada, y Whisper sigue transcribiendo ingles
        # como si fuera español, que ademas es el fallo que no da error.
        # El "escape" era imaginario y el coste, real.
        #
        # >>> Y EL CODIGO DE DEBAJO LO CONTRADECIA (2026-09-08) <<<
        # Habia DOS `except Exception` colgando del mismo `try`, y el
        # primero leia precisamente `voz.stt.idioma`, o sea el escape que
        # este comentario dice haber rechazado. El segundo era ademas
        # codigo muerto: un handler no captura lo que lanza su hermano,
        # asi que si ese `load_general_config` reventaba, `_idioma`
        # levantaba en vez de caer a "es". La tercera salida estaba
        # escrita y no existia.
        # Ahora hay UNA fuente y ya trae su propia guarda: `hablado`
        # devuelve "es" ante cualquier duda y no puede levantar. Repetir
        # aqui ese apaño es la forma de que los dos diverjan.
        from voz.idioma import hablado

        return hablado(config_dir)

    def transcribir(
        self,
        audio: np.ndarray,
        idioma: str | None = None,
        suelo: Suelo | None = None,
        hay_habla_vad: bool | None = None,
    ) -> Transcripcion:
        """Turn a mono 16 kHz float32 buffer into text.

        The buffer is what `voz.audio` records and what silero will hand
        over in 5.3, so no resampling happens here: the sample rate is
        fixed by what the three voice models were trained on.

        `suelo` is the microphone's measured noise floor. Given it, the
        energy veto applies and the "did anyone speak" verdict uses two
        independent signals instead of the model's opinion alone. Left
        out, the transcription still works and `verdicto_fiable` reports
        that the question was only half answered.
        """
        # >>> `None` ES "EL DEL CANAL", NUNCA "QUE LO ADIVINE" <<<
        # Dejarlo pasar tal cual a faster-whisper significa autodeteccion,
        # que es lo que las primeras lineas de este modulo descartan por
        # medido: cuesta una pasada sobre la primera ventana y se
        # equivoca en ordenes cortas, que es todo lo que se dice aqui.
        # Un argumento explicito sigue mandando: es como piden los bancos
        # un idioma que no es el configurado.
        idioma = idioma or self.idioma
        plano = np.asarray(audio, dtype="float32").reshape(-1)
        duracion = len(plano) / SAMPLE_RATE_VOZ
        inicio = time.perf_counter()
        try:
            segmentos, info = self._modelo.transcribe(
                plano,
                language=idioma,
                beam_size=5,
                # `condition_on_previous_text` off: with it on, one bad
                # transcription poisons the next, and Jarvis's utterances
                # are independent commands, not a continuous narration.
                condition_on_previous_text=False,
                # El ancla de vocabulario. Medido: arregla 'bloc' ->
                # 'blog' las tres veces y no rompe ninguna de las otras
                # 27. Va por `hotwords` y no por `initial_prompt` a
                # proposito -- ver la nota de ANCLA_POR_DEFECTO.
                **({"hotwords": self.ancla} if self.ancla else {}),
            )
            trozos = list(segmentos)
        except Exception as exc:  # noqa: BLE001
            raise STTError(f"Fallo transcribiendo con {self.modelo}: {exc}") from exc
        latencia = time.perf_counter() - inicio

        textos = [s.text for s in trozos]
        # Whisper reports no_speech per segment. With no segments at all
        # there is nothing to average, and "no segments" IS the strongest
        # possible statement that nobody spoke.
        prob = (
            float(np.mean([s.no_speech_prob for s in trozos])) if trozos else 1.0
        )
        nivel = Nivel(
            rms=float(np.sqrt(np.mean(plano**2))) if plano.size else 0.0,
            pico=float(np.max(np.abs(plano))) if plano.size else 0.0,
            segundos=duracion,
        )
        return Transcripcion(
            umbral_sin_habla=(UMBRAL_SIN_HABLA_CON_ANCLA if self.ancla
                              else UMBRAL_SIN_HABLA),
            ancla=self.ancla,
            texto="".join(textos),
            latencia_s=latencia,
            duracion_audio_s=duracion,
            prob_sin_habla=prob,
            idioma=getattr(info, "language", idioma),
            modelo=self.modelo,
            segmentos=[t.strip() for t in textos],
            hay_habla_vad=hay_habla_vad,
            sin_senal=nivel.sin_senal,
            # Informativo: ya no vota. Ver el comentario en el campo.
            supera_suelo=nivel.supera(suelo) if suelo is not None else None,
            nivel_dbfs=nivel.dbfs,
        )

    def escuchar(
        self,
        segundos: float = 4.0,
        dispositivo: Dispositivo | None = None,
        suelo: Suelo | None = None,
        usar_vad: bool = True,
        cancelar: threading.Event | None = None,
    ) -> Transcripcion:
        """Record a fixed window from the microphone and transcribe it.

        VIA `voz.audio.grabar` Y NO `sd.rec`, y no es un detalle de
        estilo: las funciones de conveniencia de sounddevice comparten un
        stream a nivel de modulo, asi que reproducir algo y grabar en el
        mismo proceso se BLOQUEA -- no falla, espera. Esta funcion es
        justo TTS-y-luego-STT en un proceso, o sea lo que hara la Fase
        5.5 entera, asi que con `sd.rec` era una mina puesta donde iba a
        pisar el ensamblado. Encontrado el 2026-08-21 (tercera aparicion
        del mismo bug; ver `voz/audio.py`). `grabar` trae ademas el tope
        duro, que importa igual: un fallo ruidoso en segundos no atasca
        el endpoint de audio, y un cuelgue que obliga a matar el proceso
        si -- eso costo un reinicio del PC el 2026-08-20.

        EL VAD VA DELANTE DE WHISPER, no despues. Si nadie hablo, el
        modelo NO LLEGA A VERLO: no se puede alucinar sobre un audio que
        no se transcribe, y ademas se ahorra la latencia entera. Cuando
        si hay habla, Whisper recibe el audio YA RECORTADO.
        """
        from voz.audio import grabar, grabar_hasta

        micro = dispositivo or ConfigAudio.desde_config().microfono()

        if cancelar is None:
            audio = np.asarray(
                grabar(micro, segundos), dtype="float32"
            ).reshape(-1)
        else:
            # >>> LA VENTANA SE PUEDE SOLTAR A MEDIAS <<<
            # El hilo del oido sondea paradas cada `segundos`, y mientras
            # tanto TIENE el microfono. Si en ese rato se abre una puerta,
            # quien la tiene que contestar espera a que esta vuelta acabe:
            # medido, hasta 3,0 s de grabacion + 1,7-1,9 s de Whisper. Lo
            # que el usuario diga en ese hueco no existe, porque el
            # microfono no era suyo todavia.
            # Con `cancelar` puesto la vuelta se suelta en cuanto llega el
            # aviso, y NO se transcribe lo que llevara grabado: transcribir
            # es justo el segundo y pico que se venia a quitar.
            if cancelar.is_set():
                return self._ventana_abortada(0.0)
            audio, llego_al_tope = grabar_hasta(
                micro, lambda _t: cancelar.is_set(), tope_s=segundos
            )
            audio = np.asarray(audio, dtype="float32").reshape(-1)
            if not llego_al_tope:
                return self._ventana_abortada(len(audio) / SAMPLE_RATE_VOZ)

        if not usar_vad:
            return self.transcribir(audio, suelo=suelo)

        # `self._el_vad()` y no `VAD()`: esto corre en el hilo del oido
        # cada VENTANA_PARADA_S, y construir la sesion de onnxruntime en
        # cada vuelta se pagaba en cada vuelta (es la misma
        # forma que ya se arreglo en `escuchar_turno`, que la necesitaba
        # antes de abrir el microfono).
        habla = self._el_vad().recortar(audio)
        if not habla.hay_habla:
            # Ni se transcribe. Se devuelve un veredicto completo para que
            # quien llama no tenga que distinguir este camino del otro.
            return Transcripcion(
                texto="",
                latencia_s=0.0,
                duracion_audio_s=len(audio) / SAMPLE_RATE_VOZ,
                prob_sin_habla=1.0,
                idioma=self.idioma,
                modelo=self.modelo,
                hay_habla_vad=False,
            )
        return self.transcribir(habla.audio, suelo=suelo, hay_habla_vad=True)

    def _ventana_abortada(self, duracion_s: float) -> Transcripcion:
        """La ventana se solto porque otro necesitaba el microfono.

        `hay_habla_vad` se queda en None A PROPOSITO, y no en False: nadie
        ha mirado si hubo habla, asi que decir que no la hubo seria
        inventarse la respuesta. Es la tercera salida en su sitio,
        y `verdicto_fiable` lo dira.
        """
        from voz.vad import Cierre

        return Transcripcion(
            texto="",
            latencia_s=0.0,
            duracion_audio_s=duracion_s,
            prob_sin_habla=1.0,
            idioma=self.idioma,
            modelo=self.modelo,
            hay_habla_vad=None,
            cierre=Cierre.ABORTADO.value,
        )

    def _el_vad(self):
        """Silero, cargado una vez y reutilizado.

        Antes se instanciaba por llamada, y para recortar a posteriori
        daba igual. Para JC-0013 no: el detector tiene que estar cargado
        ANTES de abrir el microfono, asi que pagar la carga ahi seria
        pagarla mientras el usuario ya esta hablando.
        """
        from voz.vad import VAD

        if getattr(self, "_vad_cache", None) is None:
            self._vad_cache = VAD()
        return self._vad_cache

    def escuchar_turno(
        self,
        dispositivo: Dispositivo | None = None,
        suelo: Suelo | None = None,
        tope_s: float | None = None,
        silencio_fin_ms: float | None = None,
        espera_inicio_ms: float | None = None,
    ) -> Transcripcion:
        """Listen until the speaker stops, not until a clock runs out.

        ESTO ES JC-0013, y sustituye a `escuchar` para los turnos de
        palabra. `escuchar` graba una ventana FIJA, asi que si hablabas
        mas de esos segundos te cortaba a mitad de frase -- siempre, no a
        veces, y por eso ocurria tambien sin ruido de fondo. Aqui la
        ventana la cierra el usuario callandose.

        DOS PASADAS DEL VAD, Y HACEN COSAS DISTINTAS:
          1. EN VIVO (`FinDeTurno`), decide UNICAMENTE cuando parar.
          2. DESPUES (`VAD.recortar`), decide si alguien hablo y recorta
             lo que va a Whisper. Es la pasada de siempre, la que esta
             medida 30/30 y 12/12, y sigue siendo la que manda: si la de
             en vivo se dejo abrir por un ruido, esta lo desmiente y la
             transcripcion sale SIN HABLA igual que antes.

        TRES SALIDAS, y viajan en `Transcripcion.cierre`:
        `silencio` (dejaste de hablar), `tope` (se acabo el maximo
        absoluto) y `sin_habla` (no empezaste nunca).
        """
        from dataclasses import replace

        from voz.audio import grabar_hasta
        from voz.vad import (
            ESPERA_INICIO_MS,
            SILENCIO_FIN_TURNO_MS,
            TOPE_TURNO_S,
            Cierre,
            FinDeTurno,
        )

        micro = dispositivo or ConfigAudio.desde_config().microfono()
        vad = self._el_vad()
        detector = FinDeTurno(
            vad,
            silencio_fin_ms=(SILENCIO_FIN_TURNO_MS if silencio_fin_ms is None
                             else silencio_fin_ms),
            espera_inicio_ms=(ESPERA_INICIO_MS if espera_inicio_ms is None
                              else espera_inicio_ms),
        )
        audio, llego_al_tope = grabar_hasta(
            micro,
            detector.empujar,
            tope_s=(TOPE_TURNO_S if tope_s is None else tope_s),
        )
        cierre = Cierre.TOPE if llego_al_tope else (detector.cierre or Cierre.TOPE)

        habla = vad.recortar(audio)
        if not habla.hay_habla:
            # El de despues desmiente al de en vivo, o coinciden. En los
            # dos casos manda este, y el motivo del cierre se conserva
            # tal cual: no es lo mismo "no dijo nada" que "hablo y no se
            # le entendio al recortar".
            return Transcripcion(
                texto="",
                latencia_s=0.0,
                duracion_audio_s=len(audio) / SAMPLE_RATE_VOZ,
                prob_sin_habla=1.0,
                idioma=self.idioma,
                modelo=self.modelo,
                hay_habla_vad=False,
                cierre=cierre.value,
            )
        return replace(
            self.transcribir(habla.audio, suelo=suelo, hay_habla_vad=True),
            cierre=cierre.value,
        )
