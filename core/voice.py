import asyncio
import math
import os
import queue
import re
import struct
import tempfile
import threading
import time
import wave

import numpy as np


# ── Asyncio persistente ───────────────────────────────────────────────────
# asyncio.run() crea un event loop nuevo cada vez — problemático en threads.
# Usamos un loop permanente en su propio thread daemon.

class _AsyncRunner:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        t = threading.Thread(
            target=self._loop.run_forever,
            daemon=True, name="async-voice"
        )
        t.start()

    def run(self, coro):
        """Ejecuta una coroutine y bloquea hasta obtener el resultado."""
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result()


_async = _AsyncRunner()


# ── TTS config ────────────────────────────────────────────────────────────
# es-MX-JorgeNeural: español neutro (registro estándar de doblaje/asistentes
# en LATAM) — menos entonación "dramática" que voces regionales como
# es-CO-GonzaloNeural, sin sonar plano/robótico.
VOICE = "es-MX-JorgeNeural"
RATE  = "+0%"
PITCH = "+0Hz"

# El prompt le pide a la IA que no use emojis, pero no siempre obedece —
# esto lo garantiza a nivel de código: nunca se pronuncia un emoji.
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF"
    "\U0000FE0F"
    "\U0000200D"
    "]+",
    flags=re.UNICODE,
)

# Tono de voz dinámico — la IA marca TONO: <tag> en su respuesta (ver
# core/ai.py) y aquí se traduce a ritmo/tono real de síntesis. Edge-TTS no
# garantiza "estilos" expresivos (Azure Speech Styles) para todas las voces,
# así que usamos rate/pitch — parámetros soportados por cualquier voz.
_TONE_PARAMS = {
    "neutral":    ("+0%",  "+0Hz"),
    "entusiasta": ("+10%", "+18Hz"),
    "serio":      ("-6%",  "-12Hz"),
    "calido":     ("-3%",  "+2Hz"),
    "urgente":    ("+15%", "+10Hz"),
}

_LEVEL_CHUNK_SECS = 0.04   # ventana de la envolvente de volumen (~25 actualizaciones/seg)

# ── Piper TTS — respaldo offline (si Edge-TTS falla: sin internet, servicio
# caído, etc.) — voz neuronal local, no tan natural como Edge-TTS pero mucho
# mejor que pyttsx3 (SAPI de Windows). Modelo se descarga una sola vez.
_PIPER_VOICE      = "es_MX-claude-high"
_PIPER_DIR        = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "data", "piper")
_PIPER_MODEL_PATH = os.path.join(_PIPER_DIR, f"{_PIPER_VOICE}.onnx")
_PIPER_CFG_PATH   = os.path.join(_PIPER_DIR, f"{_PIPER_VOICE}.onnx.json")
_PIPER_BASE_URL   = ("https://huggingface.co/rhasspy/piper-voices/resolve/main/"
                      "es/es_MX/claude/high")

_piper_voice_cache = None


def _ensure_piper_model():
    """Descarga el modelo de voz de Piper (~60MB) la primera vez que hace falta."""
    os.makedirs(_PIPER_DIR, exist_ok=True)
    import requests
    for fname, path in (
        (f"{_PIPER_VOICE}.onnx",      _PIPER_MODEL_PATH),
        (f"{_PIPER_VOICE}.onnx.json", _PIPER_CFG_PATH),
    ):
        if os.path.exists(path):
            continue
        resp = requests.get(f"{_PIPER_BASE_URL}/{fname}", timeout=60)
        resp.raise_for_status()
        with open(path, "wb") as f:
            f.write(resp.content)


def _get_piper_voice():
    global _piper_voice_cache
    if _piper_voice_cache is None:
        from piper import PiperVoice
        _ensure_piper_model()
        _piper_voice_cache = PiperVoice.load(_PIPER_MODEL_PATH)
    return _piper_voice_cache

# Barge-in VAD config
# El umbral YA NO es un número fijo (un micrófono/cuarto distinto lo hacía
# poco confiable — nunca se cruzaba, o se cruzaba con solo ruido ambiente).
# Ahora se calibra en cada reproducción: se mide el piso de ruido real
# durante el warmup y el umbral real = piso * _BARGE_IN_MULTIPLIER, entre
# un mínimo y un máximo razonables.
_BARGE_IN_SAMPLE_RATE   = 16000
_BARGE_IN_CHUNK         = 512
_BARGE_IN_MULTIPLIER    = 2.2    # cuánto debe superar tu voz al ruido de fondo medido
_BARGE_IN_MIN_THRESHOLD = 350    # piso absoluto — evita hipersensibilidad en silencio total
_BARGE_IN_MAX_THRESHOLD = 4000   # techo — evita tener que gritar en cuartos ruidosos
# Jarvis conoce de antemano el volumen de SU PROPIA voz en cada instante (la
# misma envolvente que anima la esfera) — se usa para subir el umbral cuando
# está hablando fuerte, así el eco de su propia voz en el micrófono no se
# confunde con que lo estás interrumpiendo.
_BARGE_IN_ECHO_COMPENSATION = 1800
_BARGE_IN_FRAMES       = 7     # ~224ms de voz sostenida antes de interrumpir
_BARGE_IN_WARMUP_SECS  = 0.6   # skip first 0.6s to let speaker echo settle


async def _synthesize(text: str, path: str, rate: str = RATE, pitch: str = PITCH):
    import edge_tts
    comm = edge_tts.Communicate(text, voice=VOICE, rate=rate, pitch=pitch)
    await comm.save(path)


# ── TTS ───────────────────────────────────────────────────────────────────

class TTS:
    """
    Dedicated daemon thread keeps pygame/pyttsx3 in one thread.
    on_barge_in is called (from main thread via after()) when the user speaks
    during playback and JARVIS stops to listen.
    on_level(float 0..1) is called ~25x/sec with the real volume envelope of
    the synthesized speech while it plays, for audio-reactive UI animations.
    """

    def __init__(self, on_start=None, on_stop=None, on_barge_in=None, on_level=None):
        self._q            = queue.Queue()
        self._on_start     = on_start
        self._on_stop      = on_stop
        self._on_barge_in  = on_barge_in
        self._on_level     = on_level
        threading.Thread(target=self._worker, daemon=True, name="tts").start()

    def speak(self, text: str, tone: str | None = None):
        cleaned = self._clean(text)
        if cleaned:
            rate, pitch = _TONE_PARAMS.get(tone or "neutral", _TONE_PARAMS["neutral"])
            self._q.put((cleaned, rate, pitch))

    def stop(self):
        """Interrupt current speech immediately."""
        self._q.put(None)

    # ── Worker ────────────────────────────────────────────────────────────

    def _worker(self):
        try:
            import pygame
            pygame.mixer.init()
            use_pygame = True
        except Exception:
            use_pygame = False

        while True:
            item = self._q.get()
            if item is None:
                # Clear remaining queue on stop signal
                while not self._q.empty():
                    try:
                        self._q.get_nowait()
                    except queue.Empty:
                        break
                continue

            text, rate, pitch = item
            if not text.strip():
                continue

            if self._on_start:
                self._on_start()

            interrupted = False
            try:
                if use_pygame:
                    interrupted = self._speak_edge(text, pygame, rate, pitch)
                else:
                    self._speak_pyttsx3(text)
            except Exception:
                try:
                    if use_pygame:
                        interrupted = self._speak_piper(text, pygame)
                    else:
                        self._speak_pyttsx3(text)
                except Exception:
                    try:
                        self._speak_pyttsx3(text)
                    except Exception:
                        pass

            if self._on_stop:
                self._on_stop()

            if interrupted and self._on_barge_in:
                self._on_barge_in()

    # ── Edge TTS + barge-in ───────────────────────────────────────────────

    def _speak_edge(self, text: str, pygame, rate: str = RATE, pitch: str = PITCH) -> bool:
        """Synthesize, play, monitor for barge-in. Returns True if interrupted."""
        fd, path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        channel = None
        try:
            _async.run(_synthesize(text, path, rate, pitch))   # loop persistente, sin fugas
            snd = pygame.mixer.Sound(path)
            levels = self._build_envelope(pygame, snd)
            channel = snd.play()
            return self._monitor(channel, levels)
        finally:
            try:
                if channel:
                    channel.stop()
            except Exception:
                pass
            if self._on_level:
                self._on_level(0.0)
            try:
                os.unlink(path)
            except OSError:
                pass

    # ── Piper TTS — respaldo offline ──────────────────────────────────────

    def _speak_piper(self, text: str, pygame) -> bool:
        """Igual que _speak_edge pero sintetizando con Piper (local, sin internet)."""
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        channel = None
        try:
            voice = _get_piper_voice()
            with wave.open(path, "wb") as wf:
                voice.synthesize_wav(text, wf)
            snd = pygame.mixer.Sound(path)
            levels = self._build_envelope(pygame, snd)
            channel = snd.play()
            return self._monitor(channel, levels)
        finally:
            try:
                if channel:
                    channel.stop()
            except Exception:
                pass
            if self._on_level:
                self._on_level(0.0)
            try:
                os.unlink(path)
            except OSError:
                pass

    def _build_envelope(self, pygame, snd) -> "np.ndarray":
        """RMS por ventanas de _LEVEL_CHUNK_SECS, normalizado 0..1 contra el pico."""
        try:
            arr = pygame.sndarray.array(snd).astype(np.float64)
            mono = arr.mean(axis=1) if arr.ndim > 1 else arr
            length = snd.get_length() or 1.0
            sample_rate = len(mono) / length
            chunk = max(1, int(sample_rate * _LEVEL_CHUNK_SECS))
            n_chunks = max(1, len(mono) // chunk)
            levels = np.array([
                math.sqrt(float(np.mean(mono[i * chunk:(i + 1) * chunk] ** 2)))
                for i in range(n_chunks)
            ])
            peak = levels.max()
            return levels / peak if peak > 0 else levels
        except Exception:
            return np.array([0.6])   # envolvente plana de respaldo — sigue habiendo animación

    def _monitor(self, channel, levels: "np.ndarray") -> bool:
        """
        Un solo hilo/bucle: reporta el volumen real (on_level) Y escucha
        barge-in leyendo el mismo stream de mic — evita que dos hilos toquen
        el Channel/PortAudio al mismo tiempo (causaba un crash nativo real).
        Stops playback and returns True if the user starts talking.
        Falls back to simple timed level playback if pyaudio is unavailable.
        """
        start = time.monotonic()
        n     = len(levels)

        def own_level() -> float:
            """Volumen que Jarvis mismo está emitiendo AHORA (0..1) — se conoce
            de antemano por la envolvente ya calculada, no hace falta medirlo."""
            i = int((time.monotonic() - start) / _LEVEL_CHUNK_SECS)
            return float(levels[i]) if i < n else 0.0

        def emit_level(lvl: float):
            if self._on_level:
                self._on_level(lvl)

        try:
            import pyaudio
        except ImportError:
            while channel.get_busy():
                emit_level(own_level())
                time.sleep(_LEVEL_CHUNK_SECS)
            return False

        pa = None
        stream = None
        try:
            pa = pyaudio.PyAudio()
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=_BARGE_IN_SAMPLE_RATE,
                input=True,
                frames_per_buffer=_BARGE_IN_CHUNK,
            )

            # Warm-up: además de dejar asentar el eco del parlante, mide el
            # piso de ruido real (ambiente + posible eco) para calibrar el
            # umbral de esta reproducción — no un número fijo adivinado.
            warmup_chunks = int(_BARGE_IN_SAMPLE_RATE * _BARGE_IN_WARMUP_SECS
                                / _BARGE_IN_CHUNK)
            noise_samples = []
            for _ in range(warmup_chunks):
                if not channel.get_busy():
                    return False
                data    = stream.read(_BARGE_IN_CHUNK, exception_on_overflow=False)
                samples = struct.unpack(f"{len(data)//2}h", data)
                noise_samples.append(math.sqrt(sum(s * s for s in samples) / len(samples)))
                emit_level(own_level())

            noise_floor = (sum(noise_samples) / len(noise_samples)) if noise_samples else _BARGE_IN_MIN_THRESHOLD
            base_threshold = min(_BARGE_IN_MAX_THRESHOLD,
                                  max(_BARGE_IN_MIN_THRESHOLD, noise_floor * _BARGE_IN_MULTIPLIER))

            loud_count = 0
            while channel.get_busy():
                data    = stream.read(_BARGE_IN_CHUNK, exception_on_overflow=False)
                samples = struct.unpack(f"{len(data)//2}h", data)
                rms     = math.sqrt(sum(s * s for s in samples) / len(samples))
                lvl     = own_level()
                emit_level(lvl)

                # Mientras más fuerte esté hablando Jarvis en este instante,
                # más eco de su propia voz puede colarse en el micrófono —
                # el umbral sube con eso para no auto-interrumpirse.
                threshold = min(_BARGE_IN_MAX_THRESHOLD,
                                base_threshold + lvl * _BARGE_IN_ECHO_COMPENSATION)

                if rms > threshold:
                    loud_count += 1
                    if loud_count >= _BARGE_IN_FRAMES:
                        channel.stop()
                        return True
                else:
                    loud_count = 0

            return False

        except Exception:
            # Anything goes wrong → just wait normally
            while channel.get_busy():
                time.sleep(0.05)
            return False

        finally:
            try:
                if stream:
                    stream.stop_stream()
                    stream.close()
            except Exception:
                pass
            try:
                if pa:
                    pa.terminate()
            except Exception:
                pass

    # ── Fallback TTS ─────────────────────────────────────────────────────

    def _speak_pyttsx3(self, text: str):
        import pyttsx3
        eng = pyttsx3.init()
        eng.setProperty("rate", 165)
        for v in eng.getProperty("voices"):
            if "helena" in v.name.lower() or "pablo" in v.name.lower():
                eng.setProperty("voice", v.id)
                break
        eng.say(text)
        eng.runAndWait()

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _clean(text: str) -> str:
        """Quita líneas de directivas y formato markdown antes de hablar —
        que nunca se pronuncien símbolos tipo *, #, ` o guiones de viñeta."""
        lines = [
            ln for ln in text.splitlines()
            if not ln.strip().startswith(("CMD:", "RECORDAR:", "SKILL:", "TONO:"))
        ]
        joined = "\n".join(lines)

        joined = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", joined)   # [texto](url)
        joined = re.sub(r"\*\*([^*]+)\*\*", r"\1", joined)          # **negrita**
        joined = re.sub(r"__([^_]+)__", r"\1", joined)              # __negrita__
        joined = re.sub(r"\*([^*]+)\*", r"\1", joined)              # *cursiva*
        joined = re.sub(r"_([^_]+)_", r"\1", joined)                # _cursiva_
        joined = re.sub(r"`([^`]+)`", r"\1", joined)                # `código`
        joined = re.sub(r"(?m)^\s*#{1,6}\s*", "", joined)           # # Encabezado
        joined = re.sub(r"(?m)^\s*[-*+]\s+", "", joined)            # - viñeta
        joined = re.sub(r"[*_#`]", "", joined)                      # cualquier símbolo suelto
        joined = _EMOJI_RE.sub("", joined)                          # los emojis no se pronuncian

        return " ".join(joined.split())


# ── STT ───────────────────────────────────────────────────────────────────

try:
    import speech_recognition as sr

    class STT:
        available = True

        _RECALIBRATE_EVERY = 5   # recalibra más seguido (antes 8) para no perder precisión

        def __init__(self):
            self._rec = sr.Recognizer()
            # 1.6s de silencio para que Jarvis no corte frases a mitad
            self._rec.pause_threshold          = 1.6
            # Más margen de silencio guardado al inicio/final de la grabación
            # (antes 0.3) — evita que se coma la primera o última sílaba.
            self._rec.non_speaking_duration    = 0.5
            # Frase mínima más corta (antes 0.3) — no descarta palabras breves
            # como "sí"/"no" pensando que son ruido.
            self._rec.phrase_threshold         = 0.2
            self._rec.energy_threshold         = 250
            self._rec.dynamic_energy_threshold = True
            self._mic          = sr.Microphone()
            self._listen_count = 0
            with self._mic as src:
                self._rec.adjust_for_ambient_noise(src, duration=0.8)

        def _recalibrate(self):
            try:
                with self._mic as src:
                    self._rec.adjust_for_ambient_noise(src, duration=0.4)
            except Exception:
                pass

        def listen(self, timeout: int = 10, phrase_limit: int = 30,
                   lang: str = "es-ES") -> str | None:
            self._listen_count += 1
            if self._listen_count % self._RECALIBRATE_EVERY == 0:
                self._recalibrate()
            try:
                with self._mic as src:
                    audio = self._rec.listen(
                        src,
                        timeout=timeout,
                        phrase_time_limit=phrase_limit,
                    )
                return self._rec.recognize_google(audio, language=lang)
            except sr.WaitTimeoutError:
                return None
            except sr.UnknownValueError:
                return None
            except Exception:
                return None

except ImportError:

    class STT:
        available = False

        def listen(self, **_) -> None:
            return None

# Nota: se intentó un MicLevelMonitor que abría su propio stream de PyAudio
# en paralelo a speech_recognition (para animar la burbuja con el volumen
# real del mic mientras escucha) — se retiró porque dos streams de PyAudio
# concurrentes en este sistema provocan un segmentation fault real
# (confirmado). El estado "listening" usa una animación sintética; el
# estado "speaking" sí usa el volumen real (un solo stream a la vez, ver
# TTS._monitor arriba).
