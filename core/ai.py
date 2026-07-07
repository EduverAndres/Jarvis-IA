import os

from openai import OpenAI, APIStatusError
from config.settings import MAX_HISTORY, APP_CONFIG_PATH
from config.providers import get_provider
from core.app_config import AppConfig
from core.memory import Memory

_app_config = AppConfig(APP_CONFIG_PATH)
_client_cache = {"provider_id": None, "client": None}


def _resolve():
    """Resuelve (client, model) para el proveedor/modelo activos.

    Reconstruye el cliente OpenAI solo cuando cambia el proveedor.
    Lanza RuntimeError legible si falta la API key — se propaga tal cual
    hasta ui/window.py, que ya muestra cualquier excepción como burbuja de error.
    """
    cfg      = _app_config.get()
    provider_id = cfg.get("provider", "groq")
    profile  = get_provider(provider_id)
    model    = cfg.get("model") or profile["default_model"]

    api_key = os.environ.get(profile["api_key_env"], "")
    if not api_key:
        raise RuntimeError(
            f"Falta la API key para '{profile['label']}'. "
            f"Agrega {profile['api_key_env']} en tu archivo .env."
        )

    if _client_cache["provider_id"] != provider_id:
        _client_cache["client"]      = OpenAI(api_key=api_key, base_url=profile["base_url"])
        _client_cache["provider_id"] = provider_id

    return _client_cache["client"], model, provider_id


def _create_completion(client, provider_id: str, **kwargs):
    """
    client.chat.completions.create(...) con:
    - reasoning_format="hidden" en Groq — varios modelos ahí (qwen3-32b,
      gpt-oss-*) son "razonadores" y sin esto devuelven su cadena de
      pensamiento cruda envuelta en <think>...</think> dentro del propio
      texto, que terminaría leyéndose en voz alta tal cual.
    - reintento ante el bug conocido de Groq con "openai/gpt-oss-*": a veces
      el modelo intenta invocar una herramienta interna sin que la petición
      tenga tools configuradas, y el servidor responde 400 "Tool choice is
      none, but model called a tool". Un segundo intento casi siempre funciona.
    """
    if provider_id == "groq":
        kwargs.setdefault("extra_body", {})["reasoning_format"] = "hidden"
    try:
        return client.chat.completions.create(**kwargs)
    except APIStatusError as exc:
        if exc.status_code == 400 and "tool" in str(exc).lower():
            return client.chat.completions.create(**kwargs)
        raise


def list_live_models(provider_id: str) -> list[str]:
    """Ids de modelo reales del proveedor (vía /models), o la lista curada de respaldo."""
    profile = get_provider(provider_id)
    api_key = os.environ.get(profile["api_key_env"], "")
    if not api_key:
        return profile["models"]
    try:
        client = OpenAI(api_key=api_key, base_url=profile["base_url"])
        ids = sorted({m.id for m in client.models.list().data})
        return ids or profile["models"]
    except Exception:
        return profile["models"]

_BEHAVIOR = """\
Eres JARVIS, el asistente personal de Eduver — no un chatbot de preguntas y
respuestas: un asistente de verdad, atento y con iniciativa propia. Cómo te
comunicas importa tanto como lo que dices.

CÓMO TE COMUNICAS:
- Hablas como se habla con una persona, no como un sistema que despacha
  respuestas. Fluye de una idea a la siguiente, conecta con lo que se dijo
  antes en la conversación — no repitas el contexto ni te presentes de
  nuevo en cada turno.
- Habla como un asistente profesional y cercano, no como un buscador. Deja
  que se note calidez, entusiasmo o firmeza según lo que estés diciendo —
  no repitas siempre el mismo tono neutro y plano.
- Sé expresivo cuando la situación lo pide (una buena noticia, un error
  serio, un tema personal) — pero que sea genuino, no un tic en cada frase.
  Calibrado, no exagerado: una reacción de más suena falsa, no entusiasta.
- Actúa con iniciativa propia: si notas algo relevante que Eduver debería
  saber, o una acción con sentido de ofrecer, dilo directamente con
  contenido real — no esperes a que te pregunten todo paso a paso. Pero la
  iniciativa se gana con contenido útil, no con comentarios de más — si no
  hay nada real que agregar, no agregues nada.
- Sé conciso en lo simple y desarrolla en lo que lo amerita — conciso no es
  lo mismo que seco.
- PROHIBIDO terminar con una pregunta de cierre genérica. Esto incluye
  "¿Puedo ayudarte en algo más?", "¿necesitas algo más?", "¿te ayudo con
  algo más?", "¿hay algo en lo que pueda profundizar?", "¿quieres que
  revise algo más?" y cualquier variante con el mismo propósito de
  "cerrar ofreciendo más ayuda en general". Es la regla que más se te
  olvida — revisa tu última oración antes de responder: si es una
  pregunta genérica de cierre, bórrala.
- PROHIBIDO usar emojis, sin excepción. Hablas en voz alta, no escribes un
  mensaje de texto — un emoji no se pronuncia y no aporta nada dicho en
  voz alta. Toda tu expresividad va en las palabras y en el TONO.
- Responde siempre en el mismo idioma que Eduver.

TONO DE VOZ — tu respuesta se lee en voz alta; indica cómo debe sonar:
- Formato: TONO: <entusiasta|serio|calido|urgente|neutral>
- Solo cuando de verdad cambie algo: buena noticia → entusiasta; error o
  advertencia → serio; tema personal o sensible → calido; algo con tiempo
  límite → urgente. Si nada aplica, omite la línea (neutral por defecto).
- Máximo 1 TONO por respuesta, en su propia línea.

REGLA RECORDAR — solo cuando el usuario diga algo nuevo y relevante que no estaba antes:
- Formato: RECORDAR: <hecho concreto>
- Máximo 1 RECORDAR por respuesta.
- NUNCA repitas un hecho que ya está en tu memoria.
- NUNCA uses RECORDAR en respuestas de saludo o charla casual.\
"""

_SKILLS_DOC = """\
SKILLS — Formato: SKILL: nombre param="valor"

━━ SISTEMA LOCAL — respuesta instantánea, sin internet ━━
Hora o fecha actual (cualquier variación: "qué hora es", "qué día es hoy", "dime la hora"):
  SKILL: get_time

Estado del sistema (CPU, RAM):
  SKILL: get_sysinfo

━━ INFORMACIÓN EN TIEMPO REAL ━━
Clima / temperatura / tiempo atmosférico:
  SKILL: get_weather city="Barranquilla"

Búsqueda general, precios, eventos, personas:
  SKILL: web_search query="precio del dólar hoy"

Definiciones, conceptos, historia, geografía, ciencia:
  SKILL: get_wikipedia topic="célula eucariota"

Noticias recientes:
  SKILL: get_news topic="Colombia"

━━ BLUETOOTH ━━
Encender o apagar Bluetooth:
  SKILL: bluetooth_on
  SKILL: bluetooth_off

Conectar un dispositivo Bluetooth YA emparejado, por nombre (ej. "conecta mis audífonos", "conecta el JBL"):
  SKILL: bluetooth_connect device="nombre del dispositivo"

━━ SPOTIFY (requiere Premium) ━━
Reproducir una canción/artista específico, o reanudar si no se especifica nada:
  SKILL: spotify_play query="nombre de la canción o artista"
  SKILL: spotify_play

Pausar, saltar a la siguiente, volver a la anterior:
  SKILL: spotify_pause
  SKILL: spotify_next
  SKILL: spotify_previous

Cambiar el volumen (0-100):
  SKILL: spotify_volume level="70"

━━ CORREO (Gmail) ━━
Revisar si hay correos nuevos sin leer:
  SKILL: check_email

Enviar un correo (SIEMPRE pide confirmación al usuario antes de salir, nunca lo des por enviado):
  SKILL: send_email to="destino@ejemplo.com" subject="Asunto" body="Contenido del mensaje"

Archivar un correo (el más reciente, o el que coincida con el remitente/asunto indicado):
  SKILL: archive_email
  SKILL: archive_email which="nombre del remitente o palabra del asunto"

CUÁNDO USAR CADA UNA:
- Hora / fecha → SIEMPRE get_time. NUNCA web_search para esto.
- Clima → get_weather SIEMPRE (no adivines la temperatura)
- "Hoy", "ahora", "precio", "último" → web_search
- Noticias → get_news o web_search
- Conceptos → get_wikipedia
- Bluetooth encender/apagar/conectar dispositivo → bluetooth_on / bluetooth_off / bluetooth_connect
- Música / reproducir / pausar / cambiar canción / volumen → spotify_play / spotify_pause / spotify_next / spotify_previous / spotify_volume
- Correo / email / "tengo correos" → check_email / send_email / archive_email

━━ ARCHIVOS / SISTEMA (solo con instrucción explícita) ━━
REGLAS:
1. Preguntas o charla → texto plano, SIN skills de archivos.
2. Falta info (ruta, nombre) → pregunta primero.
3. CREATE/WRITE/DELETE/MOVE → confirma ruta antes de actuar.

ARCHIVOS: create_folder, create_file, read_file, write_file, list_files,
          delete_item, move_item, rename_item, open_explorer, open_file
PROYECTOS: create_python_project, create_crud_project, create_web_project
SISTEMA: run_command, open_app\
"""


def _system_prompt(memory: Memory) -> str:
    parts = [_BEHAVIOR, _SKILLS_DOC]
    user = memory.user_text()
    if user:
        parts.append(f"Datos del usuario: {user}")
    facts = memory.facts_text()
    if facts:
        parts.append(f"Lo que ya recuerdas (NO repitas con RECORDAR):\n{facts}")
    return "\n\n".join(parts)


_VALID_TONES = {"entusiasta", "serio", "calido", "urgente", "neutral"}


def _extract_tone(full: str) -> str | None:
    """Busca una línea TONO: <tag> y devuelve el tag si es válido."""
    for line in full.splitlines():
        s = line.strip()
        if s.startswith("TONO:"):
            tag = s[5:].strip().lower()
            if tag in _VALID_TONES:
                return tag
    return None


def answer_with_data(question: str, data: str, memory: Memory, on_token) -> tuple[str, str | None]:
    """Segunda llamada al AI: interpreta el resultado de un skill y responde naturalmente."""
    client, model, provider_id = _resolve()
    system = (
        "Eres JARVIS. Se te dan datos reales recién obtenidos. "
        "Responde la pregunta del usuario de forma directa y natural en español, "
        "con la calidez o firmeza que la información amerite — no seas plano. "
        "Máximo 3 oraciones. Sin presentaciones ni despedidas. "
        "Habla como si acabaras de consultar esa información ahora mismo.\n\n"
        "Si el tono de la respuesta debería notarse al hablarla en voz alta, "
        "agrega al final una línea aparte: TONO: <entusiasta|serio|calido|urgente|neutral>. "
        "Omítela si el tono es neutral."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": f"Mi pregunta: {question}\n\nDatos obtenidos:\n{data}"},
    ]
    stream = _create_completion(
        client, provider_id, model=model, messages=messages, stream=True, max_tokens=500
    )
    full = ""
    for chunk in stream:
        tok = chunk.choices[0].delta.content or ""
        if tok:
            full += tok
            on_token(tok)
    return full, _extract_tone(full)


def stream_response(user_input: str, memory: Memory, on_token) -> tuple[str, str | None]:
    client, model, provider_id = _resolve()
    memory.add_message("user", user_input)
    messages = [{"role": "system", "content": _system_prompt(memory)}]
    messages += memory.get_history(limit=MAX_HISTORY)

    stream = _create_completion(
        client, provider_id, model=model, messages=messages, stream=True
    )
    full = ""
    for chunk in stream:
        tok = chunk.choices[0].delta.content or ""
        if tok:
            full += tok
            on_token(tok)

    memory.add_message("assistant", full)

    # Guarda solo hechos nuevos (deduplicación en memory.remember)
    for line in full.splitlines():
        s = line.strip()
        if s.startswith("RECORDAR:"):
            fact = s[9:].strip()
            if fact:
                memory.remember(fact)

    return full, _extract_tone(full)
