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
        "default_model": "openai/gpt-oss-20b",
        "models": [
            "openai/gpt-oss-20b",
            "openai/gpt-oss-120b",
            "qwen/qwen3-32b",
            "moonshotai/kimi-k2-instruct",
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
}

DEFAULT_PROVIDER = "groq"


def get_provider(provider_id: str) -> dict:
    return PROVIDERS.get(provider_id, PROVIDERS[DEFAULT_PROVIDER])
