import asyncio
import math
import os
import queue
import struct
import tempfile
import threading
import time

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
VOICE = "es-CO-GonzaloNeural"
RATE  = "+0%"
PITCH = "+0Hz"

_LEVEL_CHUNK_SECS = 0.04   # ventana de la envolvente de volumen (~25 actualizaciones/seg)

# Barge-in VAD config
# Raise _BARGE_IN_THRESHOLD if ambient noise triggers false interrupts.
# Lower it if you need to speak softly to interrupt.
_BARGE_IN_SAMPLE_RATE  = 16000
_BARGE_IN_CHUNK        = 512
_BARGE_IN_THRESHOLD    = 1100   # RMS energy — high enough to ignore ambient/echo
_BARGE_IN_FRAMES       = 7     # ~224ms of sustained voice required before interrupting
_BARGE_IN_WARMUP_SECS  = 0.6   # skip first 0.6s to let speaker echo settle


async def _synthesize(text: str, path: str):
    import edge_tts
    comm = edge_tts.Communicate(text, voice=VOICE, rate=RATE, pitch=PITCH)
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

    def speak(self, text: str):
        cleaned = self._clean(text)
        if cleaned:
            self._q.put(cleaned)

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
            text = self._q.get()
            if text is None:
                # Clear remaining queue on stop signal
                while not self._q.empty():
                    try:
                        self._q.get_nowait()
                    except queue.Empty:
                        break
                continue

            if not text.strip():
                continue

            if self._on_start:
                self._on_start()

            interrupted = False
            try:
                if use_pygame:
                    interrupted = self._speak_edge(text, pygame)
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

    def _speak_edge(self, text: str, pygame) -> bool:
        """Synthesize, play, monitor for barge-in. Returns True if interrupted."""
        fd, path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        channel = None
        try:
            _async.run(_synthesize(text, path))   # loop persistente, sin fugas
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

        def emit_level():
            if self._on_level:
                i = int((time.monotonic() - start) / _LEVEL_CHUNK_SECS)
                if i < n:
                    self._on_level(float(levels[i]))

        try:
            import pyaudio
        except ImportError:
            while channel.get_busy():
                emit_level()
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

            # Warm-up: read and discard initial frames (avoid speaker echo)
            warmup_chunks = int(_BARGE_IN_SAMPLE_RATE * _BARGE_IN_WARMUP_SECS
                                / _BARGE_IN_CHUNK)
            for _ in range(warmup_chunks):
                if not channel.get_busy():
                    return False
                stream.read(_BARGE_IN_CHUNK, exception_on_overflow=False)
                emit_level()

            loud_count = 0
            while channel.get_busy():
                data    = stream.read(_BARGE_IN_CHUNK, exception_on_overflow=False)
                samples = struct.unpack(f"{len(data)//2}h", data)
                rms     = math.sqrt(sum(s * s for s in samples) / len(samples))
                emit_level()

                if rms > _BARGE_IN_THRESHOLD:
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
        """Strip directive lines before speaking."""
        lines = [
            ln for ln in text.splitlines()
            if not ln.strip().startswith(("CMD:", "RECORDAR:", "SKILL:"))
        ]
        return " ".join(" ".join(lines).split())


# ── STT ───────────────────────────────────────────────────────────────────

try:
    import speech_recognition as sr

    class STT:
        available = True

        _RECALIBRATE_EVERY = 8

        def __init__(self):
            self._rec = sr.Recognizer()
            # 1.5s de silencio para que Jarvis no corte frases a mitad
            self._rec.pause_threshold          = 1.5
            # Espera hasta 0.3s de non-speech antes de empezar a grabar
            self._rec.non_speaking_duration    = 0.3
            self._rec.energy_threshold         = 300
            self._rec.dynamic_energy_threshold = True
            self._mic          = sr.Microphone()
            self._listen_count = 0
            with self._mic as src:
                self._rec.adjust_for_ambient_noise(src, duration=0.6)

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
