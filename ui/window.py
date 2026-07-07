import json
import os
import threading
import time
from pathlib import Path

import psutil
import webview

from config.settings import MEMORY_PATH, APP_CONFIG_PATH
from config.providers import PROVIDERS
from core.memory import Memory
from core.app_config import AppConfig
from core.ai import stream_response, answer_with_data, list_live_models
from core.voice import TTS, STT
from core.skill_runner import run_skills
from skills.system_skills import execute_cmd
from skills.spotify_skills import (
    get_access_token_for_sdk, set_device_id as set_spotify_device_id, get_track_style,
)
from skills.email_skills import check_new_emails

_EMAIL_POLL_SECONDS = 60

WEB_DIR = Path(__file__).parent / "web"

# Skills cuya salida es información cruda que conviene que la IA "traduzca"
# a una respuesta natural. Todo lo demás (get_time, bluetooth_*, archivos,
# proyectos, sistema...) ya devuelve una frase lista para hablar — se habla
# directo, sin gastar una segunda llamada al modelo (más rápido).
_NEEDS_INTERPRETATION = {"get_weather", "web_search", "get_wikipedia", "get_news"}

memory      = Memory(MEMORY_PATH)
app_config  = AppConfig(APP_CONFIG_PATH)
stt         = STT()


class TokenStreamer:
    """Buffers streamed AI tokens and flushes to JS at most every ~40ms,
    so the WebView bridge isn't hit at Groq's up-to-500 tok/s rate."""

    def __init__(self, push_fn, interval: float = 0.04):
        self._buf         = []
        self._lock        = threading.Lock()
        self._push        = push_fn
        self._interval     = interval
        self._last_flush   = 0.0

    def add(self, tok: str):
        with self._lock:
            self._buf.append(tok)
        if time.monotonic() - self._last_flush >= self._interval:
            self.flush()

    def flush(self):
        with self._lock:
            if not self._buf:
                return
            chunk = "".join(self._buf)
            self._buf.clear()
        self._last_flush = time.monotonic()
        self._push(chunk)


class Api:
    """Exposed to JS as `pywebview.api.*` — thin forwarders to JarvisApp."""

    def __init__(self, app: "JarvisApp"):
        self._app = app

    def send_message(self, text: str):
        self._app.handle_send(text)

    def toggle_mic(self):
        self._app.toggle_mic()

    def toggle_always_on(self, enabled: bool):
        self._app.toggle_always_on(bool(enabled))

    def clear_chat(self):
        self._app.clear_chat()

    def confirm_response(self, confirmed: bool):
        self._app.on_confirm_response(bool(confirmed))

    def get_providers(self):
        return self._app.get_providers()

    def get_provider_config(self):
        return self._app.get_provider_config()

    def get_provider_models(self, provider_id: str):
        return self._app.get_provider_models(provider_id)

    def set_provider(self, provider_id: str, model_id: str):
        self._app.set_provider(provider_id, model_id)

    def get_spotify_token(self):
        return self._app.get_spotify_token()

    def set_spotify_device_id(self, device_id: str):
        self._app.set_spotify_device_id(device_id)

    def spotify_player_error(self, message: str):
        self._app.spotify_player_error(message)

    def spotify_track_changed(self, track_id, artist_id, is_playing: bool, position_ms):
        self._app.spotify_track_changed(track_id, artist_id, bool(is_playing), position_ms or 0)


class JarvisApp:
    _REPEAT_TRIGGERS = [
        "repite", "répite", "repítelo", "repíteme", "repite eso", "repite lo que dijiste",
        "otra vez", "de nuevo", "again", "dilo de nuevo", "dilo otra vez",
        "vuelve a decir", "vuelve a repetir", "puedes repetir", "puedes decirlo de nuevo",
        "no escuché", "no te escuché", "no oí", "no te oí",
        "qué dijiste", "que dijiste", "no entendí", "no te entendí",
        "más alto", "más despacio", "más claro",
    ]

    def __init__(self):
        self.window = None
        self.api    = Api(self)

        self._busy          = False
        self._listening     = False
        self._always_on     = False
        self._barged_in     = False
        self._last_response = ""

        self._confirm_event  = None
        self._confirm_result = None
        self._js_lock = threading.Lock()
        self._stats_running = False
        self._spotify_last_track_id = None

        self.tts = TTS(
            on_start    = self._on_tts_start,
            on_stop     = self._on_tts_stop,
            on_barge_in = self._on_barge_in,
            on_level    = self._on_voice_level,
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def run(self):
        self.window = webview.create_window(
            "J.A.R.V.I.S",
            url=str(WEB_DIR / "index.html"),
            js_api=self.api,
            width=1080, height=840,
            min_size=(760, 620),
            background_color="#02020a",
        )
        self.window.events.loaded += self._on_loaded
        self.window.events.closed += self._on_closed
        # Requires the Edge WebView2 Runtime (preinstalled on Windows 11).
        # If missing: install the "WebView2 Runtime Evergreen Bootstrapper" from Microsoft.
        webview.start(gui="edgechromium", debug=False)

    def _on_loaded(self):
        msg = "Sistema en línea. ¿En qué puedo asistirle hoy?"
        self._write("jarvis", "JARVIS", msg)
        self._set_state("idle")
        self.tts.speak(msg)
        self._stats_running = True
        threading.Thread(target=self._stats_loop, daemon=True).start()
        threading.Thread(target=self._email_loop, daemon=True).start()

    def _on_closed(self):
        self._stats_running = False

    # ── Estadísticas del sistema ────────────────────────────────────────────

    def _stats_loop(self):
        while self._stats_running:
            cpu = psutil.cpu_percent(interval=1.0)   # también sirve de intervalo del bucle
            ram = psutil.virtual_memory().percent
            self._push_js(f"window.jarvisUpdateStats({cpu},{ram})")

    def _on_voice_level(self, level: float):
        self._push_js(f"window.jarvisSetLevel({level:.3f})")

    # ── Correo — sondeo proactivo en segundo plano ──────────────────────────

    def _email_loop(self):
        time.sleep(10)  # deja que la ventana termine de cargar antes del primer sondeo
        while self._stats_running:
            try:
                if not self._busy:
                    new_mails = check_new_emails()
                    if new_mails:
                        self._announce_new_emails(new_mails)
            except Exception:
                pass
            time.sleep(_EMAIL_POLL_SECONDS)

    def _announce_new_emails(self, mails: list):
        if len(mails) == 1:
            m = mails[0]
            msg = f"Te llegó un correo nuevo de {m['from']}: {m['subject']}."
        else:
            lines = "; ".join(f"{m['from']} — {m['subject']}" for m in mails)
            msg = f"Te llegaron {len(mails)} correos nuevos: {lines}."
        self._write("sys", "CORREO", msg)
        self.tts.speak(msg)

    # ── JS bridge helpers ─────────────────────────────────────────────────

    def _push_js(self, script: str):
        with self._js_lock:
            try:
                self.window.evaluate_js(script)
            except Exception:
                pass

    def _write(self, tag: str, label: str, text: str):
        self._push_js(
            f"window.jarvisWriteLine({json.dumps(tag)},{json.dumps(label)},{json.dumps(text)})"
        )

    def _set_state(self, state: str):
        self._push_js(f"window.jarvisSetState({json.dumps(state)})")

    def clear_chat(self):
        self._push_js("window.jarvisClearChat()")

    # ── Configuración de proveedor de IA ────────────────────────────────────

    def get_providers(self):
        return [
            {
                "id": pid,
                "label": profile["label"],
                "has_key": bool(os.environ.get(profile["api_key_env"], "")),
            }
            for pid, profile in PROVIDERS.items()
        ]

    def get_provider_config(self):
        return app_config.get()

    def get_provider_models(self, provider_id: str):
        return list_live_models(provider_id)

    def set_provider(self, provider_id: str, model_id: str):
        app_config.set(provider_id, model_id)
        label = PROVIDERS.get(provider_id, {}).get("label", provider_id)
        self._write("sys", "JARVIS", f"Proveedor cambiado a {label} ({model_id}).")

    # ── Spotify Web Playback SDK (reproductor embebido en la propia ventana) ──

    def get_spotify_token(self):
        """El SDK de JS pide un access_token fresco por acá (puede bloquear
        si hace falta reautorizar — ya corre en el hilo que llama pywebview,
        no en el hilo principal de la UI)."""
        return get_access_token_for_sdk()

    def set_spotify_device_id(self, device_id):
        set_spotify_device_id(device_id)
        if device_id:
            self._write("sys", "JARVIS", "Reproductor de Spotify listo dentro de JARVIS.")

    def spotify_player_error(self, message: str):
        self._write("err", "SPOTIFY",
                     f"No se pudo iniciar el reproductor embebido ({message}). "
                     "Sigue funcionando el control remoto sobre otros dispositivos.")

    def spotify_track_changed(self, track_id, artist_id, is_playing: bool, position_ms):
        """El SDK avisa acá en cada play/pausa/cambio de canción. Solo cuando
        la canción es nueva se consulta género/tempo (evita golpear la API de
        Spotify de más); un simple play/pause o seek solo reancla la posición."""
        if not is_playing:
            self._push_js("window.jarvisSetMusicStyle(false,null,null,null,0)")
            return
        if track_id and track_id != self._spotify_last_track_id:
            self._spotify_last_track_id = track_id

            def fetch():
                style = get_track_style(track_id, artist_id)
                self._push_js(
                    f"window.jarvisSetMusicStyle(true,{style['color']},"
                    f"{style['tempo']},{style['energy']},{position_ms})"
                )
            threading.Thread(target=fetch, daemon=True).start()
        else:
            self._push_js(f"window.jarvisSetMusicStyle(true,null,null,null,{position_ms})")

    # ── Send / Response ───────────────────────────────────────────────────

    @classmethod
    def _is_repeat(cls, text: str) -> bool:
        low = text.lower().strip()
        return any(t in low for t in cls._REPEAT_TRIGGERS)

    def handle_send(self, text: str):
        text = text.strip()
        if not text:
            return
        if self._busy:
            self._write("sys", "JARVIS", "Espera un momento, aún estoy procesando.")
            return
        if len(text) > 4000:
            self._write("err", "ERROR",
                        f"Mensaje demasiado largo ({len(text)} chars). Máximo 4000.")
            return

        if self._is_repeat(text) and self._last_response:
            self._write("user", "TÚ", text)
            self._write("jarvis", "JARVIS", self._last_response)
            self.tts.speak(self._last_response)
            return

        self._write("user", "TÚ", text)
        self._busy = True
        self._set_state("thinking")
        threading.Thread(target=self._run_response, args=(text,), daemon=True).start()

    def _run_response(self, text: str):
        try:
            self._push_js("window.jarvisBeginJarvisMessage()")
            streamer = TokenStreamer(lambda chunk: self._push_js(
                f"window.jarvisAppendToken({json.dumps(chunk)})"
            ))

            full, tone = stream_response(text, memory, streamer.add)
            streamer.flush()
            self._last_response = full
            self._push_js("window.jarvisEndJarvisMessage()")

            # ── Execute SKILL: directives ──────────────────────────────
            skill_results = run_skills(
                full, confirm_fn=self.confirm_delete, confirm_email_fn=self.confirm_send_email
            )
            good_outputs  = []    # datos crudos que sí necesitan una IA para "traducirlos"
            quick_outputs = []    # salidas que ya son una frase lista para hablar — sin segunda llamada
            for tag, skill_name, output in skill_results:
                self._write(tag, f"SKILL:{skill_name}", output)
                if tag == "sys":
                    if skill_name in _NEEDS_INTERPRETATION:
                        good_outputs.append(output)
                    else:
                        quick_outputs.append(output)

            # ── Legacy CMD: directives ─────────────────────────────────
            for line in full.splitlines():
                s = line.strip()
                if s.startswith("CMD:"):
                    cmd = s[4:].strip()
                    out = execute_cmd(cmd)
                    self._write("sys", "SISTEMA", f"$ {cmd}\n{out}")

            if good_outputs:
                # ── Datos que sí necesitan una segunda llamada a la IA para naturalizarlos
                data_str = "\n\n".join(good_outputs + quick_outputs)
                self._push_js("window.jarvisBeginJarvisMessage()")

                follow, follow_tone = answer_with_data(text, data_str, memory, streamer.add)
                streamer.flush()
                self._last_response = follow
                self._push_js("window.jarvisEndJarvisMessage()")

                self.tts.speak(follow, tone=follow_tone or tone)
            elif quick_outputs:
                # ── Ya son frases naturales (ej. "Bluetooth activado.") — se hablan directo,
                #    sin gastar una llamada extra a la IA (más rápido).
                spoken = " ".join(quick_outputs)
                self._last_response = spoken
                self.tts.speak(spoken, tone=tone)
            else:
                self.tts.speak(full, tone=tone)

        except Exception as exc:
            self._write("err", "ERROR", str(exc))
            self._set_state("idle")
        finally:
            self._busy = False
            if not self._barged_in and not self._listening:
                self._set_state("idle")

    # ── Skill helpers ─────────────────────────────────────────────────────

    def confirm_action(self, title: str, message: str, detail: str,
                        warn: str = "Esta acción no se puede deshacer.",
                        confirm_label: str = "Confirmar") -> bool:
        """Called from the skills thread — blocks until the JS modal answers.
        Reusable por cualquier skill que necesite un sí/no antes de una acción
        riesgosa (borrar, enviar un correo, etc.)."""
        ev     = threading.Event()
        result = [False]
        self._confirm_event  = ev
        self._confirm_result = result
        self._push_js(
            f"window.jarvisShowConfirm({json.dumps(title)},{json.dumps(message)},"
            f"{json.dumps(detail)},{json.dumps(warn)},{json.dumps(confirm_label)})"
        )
        ev.wait(timeout=60)
        return result[0]

    def confirm_delete(self, path: str) -> bool:
        return self.confirm_action(
            "JARVIS — Confirmar eliminación", "¿Eliminar definitivamente?", path,
            confirm_label="Eliminar",
        )

    def confirm_send_email(self, summary: str) -> bool:
        return self.confirm_action(
            "JARVIS — Confirmar envío de correo", "¿Enviar este correo?", summary,
            "Se enviará de inmediato — revisa el destinatario y el contenido.",
            confirm_label="Enviar",
        )

    def on_confirm_response(self, confirmed: bool):
        if self._confirm_event:
            self._confirm_result[0] = confirmed
            self._confirm_event.set()

    # ── Voice ─────────────────────────────────────────────────────────────

    def toggle_mic(self):
        if self._listening:
            self._listening = False
            self._set_state("idle")
        else:
            self.start_mic()

    def toggle_always_on(self, enabled: bool):
        self._always_on = enabled
        if self._always_on:
            self.start_mic()

    def start_mic(self):
        if not stt.available:
            self._write("err", "ERROR",
                        "Micrófono no disponible. Instala pyaudio y speech_recognition, luego reinicia.")
            return
        if self._busy or self._listening:
            return
        self._listening = True
        self._set_state("listening")
        threading.Thread(target=self._mic_loop, daemon=True).start()

    def _mic_loop(self):
        text = stt.listen(timeout=10, phrase_limit=30)
        self._listening = False

        if text and len(text.strip()) >= 3:
            self.handle_send(text.strip())
        else:
            self._on_mic_idle()

    def _on_mic_idle(self):
        self._set_state("idle")
        if self._always_on and not self._busy:
            time.sleep(0.4)
            self.start_mic()

    # ── TTS event handlers (called from the TTS worker thread) ────────────

    def _on_tts_start(self):
        self._set_state("speaking")

    def _on_tts_stop(self):
        if not self._barged_in:
            self._set_state("idle")
        if self._always_on and not self._listening and not self._busy:
            threading.Timer(0.35, self.start_mic).start()

    def _on_barge_in(self):
        """User spoke while JARVIS was talking — stop and listen immediately."""
        self._barged_in = True
        self._set_state("listening")
        self._write("sys", "JARVIS", "[ Interrumpido — te escucho... ]")
        threading.Timer(0.12, self._barge_in_listen).start()

    def _barge_in_listen(self):
        self._barged_in = False
        if not self._listening and stt.available:
            self._listening = True
            threading.Thread(target=self._mic_loop, daemon=True).start()
