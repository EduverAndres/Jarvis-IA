"""Control de reproducción de Spotify (requiere Spotify Premium).

Flujo de autorización (una sola vez): abre el navegador para que el usuario
inicie sesión y autorice la app, captura el código de retorno con un
servidor HTTP local temporal, y lo cambia por un access_token + refresh_token
que se guardan en data/spotify_token.json. De ahí en adelante el refresh_token
renueva el acceso solo, sin volver a pedir login.
"""

import http.server
import json
import os
import time
import webbrowser
from urllib.parse import urlencode, urlparse, parse_qs

import requests

_REDIRECT_URI = "http://127.0.0.1:8888/callback"
# "streaming" + user-read-email/private son los que exige el Web Playback SDK
# para que la propia ventana de Jarvis pueda ser un dispositivo de Spotify.
_SCOPES = (
    "user-read-playback-state user-modify-playback-state user-read-currently-playing "
    "streaming user-read-email user-read-private"
)
_TOKEN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "spotify_token.json"
)

# device_id del reproductor embebido en la propia ventana de Jarvis (Web
# Playback SDK) — si está disponible, se usa como destino de la reproducción
# en vez de "cualquier dispositivo activo".
_jarvis_device_id: str | None = None


def set_device_id(device_id: str | None):
    global _jarvis_device_id
    _jarvis_device_id = device_id


def get_access_token_for_sdk() -> str | None:
    """El Web Playback SDK (JS) pide un access_token fresco por este camino."""
    return _get_valid_access_token()


def _client_id() -> str:
    return os.environ.get("SPOTIFY_CLIENT_ID", "")


def _client_secret() -> str:
    return os.environ.get("SPOTIFY_CLIENT_SECRET", "")


def _load_token() -> dict:
    try:
        with open(_TOKEN_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_token(data: dict):
    os.makedirs(os.path.dirname(_TOKEN_PATH), exist_ok=True)
    with open(_TOKEN_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        self.server.auth_code = params.get("code", [None])[0]
        self.server.auth_error = params.get("error", [None])[0]
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        ok = bool(self.server.auth_code)
        msg = "Autorización completa — ya puedes cerrar esta pestaña." if ok \
            else "Autorización cancelada o con error — vuelve a intentarlo desde Jarvis."
        self.wfile.write(f"<html><body><h2>{msg}</h2></body></html>".encode("utf-8"))

    def log_message(self, fmt, *args):
        pass   # silencia el log de acceso en consola


def _authorize() -> bool:
    """Login único en el navegador. Bloquea hasta que el usuario autorice o pase el tiempo límite."""
    if not _client_id() or not _client_secret():
        return False

    try:
        server = http.server.HTTPServer(("127.0.0.1", 8888), _CallbackHandler)
    except OSError:
        return False
    server.auth_code = None
    server.auth_error = None
    server.timeout = 120

    url = "https://accounts.spotify.com/authorize?" + urlencode({
        "client_id": _client_id(),
        "response_type": "code",
        "redirect_uri": _REDIRECT_URI,
        "scope": _SCOPES,
    })
    webbrowser.open(url)
    server.handle_request()
    server.server_close()

    if not server.auth_code:
        return False

    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "authorization_code",
            "code": server.auth_code,
            "redirect_uri": _REDIRECT_URI,
        },
        auth=(_client_id(), _client_secret()),
        timeout=15,
    )
    if resp.status_code != 200:
        return False
    data = resp.json()
    _save_token({
        "access_token":  data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at":    time.time() + data["expires_in"] - 30,
    })
    return True


def _refresh_access_token(refresh_token: str) -> str | None:
    try:
        resp = requests.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            auth=(_client_id(), _client_secret()),
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        _save_token({
            "access_token":  data["access_token"],
            "refresh_token": data.get("refresh_token", refresh_token),
            "expires_at":    time.time() + data["expires_in"] - 30,
        })
        return data["access_token"]
    except requests.RequestException:
        return None


def _get_valid_access_token() -> str | None:
    data = _load_token()
    if data.get("access_token") and time.time() < data.get("expires_at", 0):
        return data["access_token"]
    if data.get("refresh_token"):
        token = _refresh_access_token(data["refresh_token"])
        if token:
            return token
    if _authorize():
        return _load_token().get("access_token")
    return None


def _request(method: str, path: str, target_device: bool = False, **kwargs):
    """Devuelve (response, error_legible). error_legible es None si todo salió bien.

    target_device=True agrega el device_id del reproductor embebido de Jarvis
    (si ya se conectó vía Web Playback SDK) como destino explícito — así la
    reproducción sale por la propia ventana de Jarvis en vez de "cualquier
    dispositivo activo".
    """
    if not _client_id() or not _client_secret():
        return None, ("Falta configurar Spotify: agrega SPOTIFY_CLIENT_ID y "
                       "SPOTIFY_CLIENT_SECRET en tu archivo .env.")
    token = _get_valid_access_token()
    if not token:
        return None, "No pude autorizar el acceso a Spotify — inténtalo de nuevo."
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    if target_device and _jarvis_device_id:
        params = kwargs.setdefault("params", {})
        params["device_id"] = _jarvis_device_id
    try:
        resp = requests.request(
            method, f"https://api.spotify.com/v1{path}", headers=headers, timeout=10, **kwargs
        )
        return resp, None
    except requests.RequestException as exc:
        return None, f"No pude conectar con Spotify: {exc}"


def _handle_player_response(resp, ok_message: str) -> str:
    if resp.status_code == 404:
        return ("No encontré ningún dispositivo activo de Spotify — abre Spotify en tu "
                "celular, computador o parlante y vuelve a intentar.")
    if resp.status_code == 403:
        return "Spotify rechazó la acción — revisa que tu cuenta tenga Premium."
    if resp.status_code >= 400:
        return f"Spotify no pudo completar la acción (error {resp.status_code})."
    return ok_message


def _ensure_device_active():
    """Un dispositivo del Web Playback SDK recién conectado queda 'listo' pero
    no 'activo' para Spotify hasta que se transfiere la reproducción — sin
    esto, los comandos de play fallan aunque el dispositivo esté conectado."""
    if _jarvis_device_id:
        _request("PUT", "/me/player", json={"device_ids": [_jarvis_device_id], "play": False})


def spotify_play(query: str = "") -> str:
    _ensure_device_active()
    query = (query or "").strip()
    if query:
        resp, err = _request("GET", "/search", params={"q": query, "type": "track", "limit": 1})
        if err:
            return err
        if resp.status_code != 200:
            return f"No pude buscar en Spotify (error {resp.status_code})."
        items = resp.json().get("tracks", {}).get("items", [])
        if not items:
            return f"No encontré ninguna canción para '{query}' en Spotify."
        track   = items[0]
        name    = track["name"]
        artists = ", ".join(a["name"] for a in track["artists"])
        resp2, err2 = _request("PUT", "/me/player/play", target_device=True, json={"uris": [track["uri"]]})
        if err2:
            return err2
        return _handle_player_response(resp2, f"Reproduciendo '{name}' de {artists}.")
    else:
        resp, err = _request("PUT", "/me/player/play", target_device=True)
        if err:
            return err
        return _handle_player_response(resp, "Reproducción reanudada.")


def spotify_pause() -> str:
    resp, err = _request("PUT", "/me/player/pause", target_device=True)
    if err:
        return err
    return _handle_player_response(resp, "Pausado.")


def spotify_next() -> str:
    resp, err = _request("POST", "/me/player/next", target_device=True)
    if err:
        return err
    return _handle_player_response(resp, "Siguiente canción.")


def spotify_previous() -> str:
    resp, err = _request("POST", "/me/player/previous", target_device=True)
    if err:
        return err
    return _handle_player_response(resp, "Canción anterior.")


def spotify_volume(level: str) -> str:
    try:
        pct = max(0, min(100, int(str(level).strip().rstrip("%"))))
    except (ValueError, TypeError):
        return "Especifica el volumen como un número entre 0 y 100."
    resp, err = _request("PUT", "/me/player/volume", target_device=True, params={"volume_percent": pct})
    if err:
        return err
    return _handle_player_response(resp, f"Volumen de Spotify en {pct}%.")


# ── Estilo visual según la canción ──────────────────────────────────────────
# Spotify no deja leer el audio real (todo pasa por su SDK con DRM), así que
# el "efecto según el estilo de música" se arma con los propios metadatos que
# la API sí entrega: el género del artista (para el color) y el tempo/energía
# de la canción vía audio-features (para el ritmo del pulso del orbe).
_GENRE_COLORS = [
    (("metal",), 0x8b0000),
    (("rock",), 0xff3245),
    (("hip hop", "rap", "trap"), 0x9d4edd),
    (("electronic", "edm", "dance", "house", "techno"), 0x00e5ff),
    (("pop",), 0xff4fa3),
    (("reggaeton", "latin", "salsa", "cumbia", "urbano"), 0xff6b35),
    (("jazz", "blues"), 0xffb703),
    (("classical", "instrumental", "soundtrack"), 0xffd166),
    (("reggae",), 0x2dd881),
    (("acoustic", "folk", "indie", "singer-songwriter"), 0xffa552),
]
_DEFAULT_MUSIC_COLOR = 0xff3245  # brand-500, si no reconoce el género


def _genre_to_color(genres: list) -> int:
    joined = " ".join(g.lower() for g in genres)
    for keywords, color in _GENRE_COLORS:
        if any(k in joined for k in keywords):
            return color
    return _DEFAULT_MUSIC_COLOR


def get_track_style(track_id: str | None, artist_id: str | None) -> dict:
    """Color (según género del artista), tempo y energía de la canción actual."""
    color, tempo, energy = _DEFAULT_MUSIC_COLOR, 100.0, 0.5
    if artist_id:
        resp, err = _request("GET", f"/artists/{artist_id}")
        if not err and resp.status_code == 200:
            color = _genre_to_color(resp.json().get("genres", []))
    if track_id:
        resp, err = _request("GET", f"/audio-features/{track_id}")
        if not err and resp.status_code == 200:
            data = resp.json()
            tempo  = data.get("tempo") or tempo
            energy = data.get("energy") if data.get("energy") is not None else energy
    return {"color": color, "tempo": tempo, "energy": energy}
