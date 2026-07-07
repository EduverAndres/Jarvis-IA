"""Catálogo estático de proveedores de IA compatibles con la API de OpenAI.

Cada proveedor expone /chat/completions y /models con el mismo protocolo,
así que un único cliente `openai.OpenAI(api_key=..., base_url=...)` sirve
para los cuatro — solo cambian base_url/api_key/model.

Las listas `models` son un respaldo curado, no una fuente de verdad: los
catálogos gratuitos cambian sin aviso (Groq deprecó llama-3.1-8b-instant
el 17/jun/2026; OpenRouter rota sus modelos ":free" mes a mes). Usar
core.ai.list_live_models() para obtener la lista real vigente.
"""

PROVIDERS = {
    "groq": {
        "id": "groq",
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        # Nota: los modelos "openai/gpt-oss-*" tienen un bug documentado en
        # Groq — a veces intentan invocar una herramienta interna aunque la
        # petición no tiene tools configuradas, y el servidor responde
        # "Tool choice is none, but model called a tool" (400). Por eso NO
        # son el default, aunque siguen disponibles en la lista.
        "default_model": "qwen/qwen3-32b",
        "models": [
            "qwen/qwen3-32b",
            "moonshotai/kimi-k2-instruct",
            "openai/gpt-oss-20b",
            "openai/gpt-oss-120b",
        ],
    },
    "cerebras": {
        "id": "cerebras",
        "label": "Cerebras",
        "base_url": "https://api.cerebras.ai/v1",
        "api_key_env": "CEREBRAS_API_KEY",
        # verificar periódicamente contra https://inference-docs.cerebras.ai/models/overview
        "default_model": "gpt-oss-120b",
        "models": [
            "gpt-oss-120b",
            "llama-3.3-70b",
            "qwen-3-32b",
        ],
    },
    "openrouter": {
        "id": "openrouter",
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        # catálogo ":free" muy volátil — confiar en el botón "Actualizar modelos"
        # (core.ai.list_live_models) antes que en esta lista de respaldo
        "default_model": "meta-llama/llama-3.3-70b-instruct:free",
        "models": [
            "meta-llama/llama-3.3-70b-instruct:free",
        ],
    },
    "mistral": {
        "id": "mistral",
        "label": "Mistral (La Plateforme)",
        "base_url": "https://api.mistral.ai/v1",
        "api_key_env": "MISTRAL_API_KEY",
        "default_model": "mistral-small-latest",
        "models": [
            "mistral-small-latest",
            "mistral-large-latest",
            "open-mistral-nemo-2407",
        ],
    },
    "gemini": {
        "id": "gemini",
        "label": "Google Gemini",
        # Endpoint compatible con OpenAI que expone Google — mismo cliente
        # openai.OpenAI(...) que los demás proveedores, sin SDK aparte.
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key_env": "GEMINI_API_KEY",
        # "gemini-flash-latest" es un alias que Google mantiene apuntando al
        # último modelo "flash" estable — no hay que perseguir versiones a mano.
        "default_model": "gemini-flash-latest",
        "models": [
            "gemini-flash-latest",
            "gemini-2.5-flash",
            "gemini-3.5-flash",
            "gemini-2.0-flash",
        ],
    },
}

DEFAULT_PROVIDER = "groq"


def get_provider(provider_id: str) -> dict:
    return PROVIDERS.get(provider_id, PROVIDERS[DEFAULT_PROVIDER])
