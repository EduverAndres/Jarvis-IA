import os

from openai import OpenAI
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

    return _client_cache["client"], model


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
Eres JARVIS, asistente IA personal. Personalidad: directo, confianzudo, sin rodeos.

REGLAS DE RESPUESTA — OBLIGATORIAS:
- Saludo o charla corta → UNA sola oración. Nunca más.
- Pregunta simple → respuesta directa en 1-2 líneas. Sin introducción, sin despedida.
- Solo desarrolla si el usuario pide explicación o está trabajando en algo técnico.
- NUNCA hagas preguntas retóricas ni ofrezcas múltiples opciones sin que te lo pidan.
- NUNCA termines con "¿Puedo ayudarte en algo más?" ni frases de cierre similares.
- Responde siempre en el mismo idioma que el usuario.

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

CUÁNDO USAR CADA UNA:
- Hora / fecha → SIEMPRE get_time. NUNCA web_search para esto.
- Clima → get_weather SIEMPRE (no adivines la temperatura)
- "Hoy", "ahora", "precio", "último" → web_search
- Noticias → get_news o web_search
- Conceptos → get_wikipedia
- Bluetooth encender/apagar/conectar dispositivo → bluetooth_on / bluetooth_off / bluetooth_connect

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


def answer_with_data(question: str, data: str, memory: Memory, on_token) -> str:
    """Segunda llamada al AI: interpreta el resultado de un skill y responde naturalmente."""
    client, model = _resolve()
    system = (
        "Eres JARVIS. Se te dan datos reales recién obtenidos. "
        "Responde la pregunta del usuario de forma directa y natural en español. "
        "Máximo 3 oraciones. Sin presentaciones ni despedidas. "
        "Habla como si acabaras de consultar esa información ahora mismo."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": f"Mi pregunta: {question}\n\nDatos obtenidos:\n{data}"},
    ]
    stream = client.chat.completions.create(
        model=model, messages=messages, stream=True, max_tokens=300
    )
    full = ""
    for chunk in stream:
        tok = chunk.choices[0].delta.content or ""
        if tok:
            full += tok
            on_token(tok)
    return full


def stream_response(user_input: str, memory: Memory, on_token) -> str:
    client, model = _resolve()
    memory.add_message("user", user_input)
    messages = [{"role": "system", "content": _system_prompt(memory)}]
    messages += memory.get_history(limit=MAX_HISTORY)

    stream = client.chat.completions.create(
        model=model, messages=messages, stream=True
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

    return full
