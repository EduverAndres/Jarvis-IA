import os

from dotenv import load_dotenv

_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_base, ".env"))

WAKE_WORD     = "jarvis"
TTS_RATE      = 165
MAX_HISTORY   = 10                       # Less context = menos latencia

MEMORY_PATH     = os.path.join(_base, "data", "memory.json")
APP_CONFIG_PATH = os.path.join(_base, "data", "app_config.json")
