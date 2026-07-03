import subprocess
import datetime
import platform
import os

# Patrones de comandos peligrosos — bloqueados siempre
_BLOCKED_PATTERNS = [
    "del ",  "del/",   "rmdir",  "rd /s",
    "format", "mkformat",
    "shutdown", "restart",
    "taskkill", "tskill",
    "reg delete", "reg add",
    "bcdedit", "diskpart",
    "net user", "net localgroup",
    "rm -", "rm/",
    ":(){:|:&};:",   # fork bomb
    "powershell -enc",
]


def _is_safe(cmd: str) -> tuple[bool, str]:
    lower = cmd.lower().strip()
    for pattern in _BLOCKED_PATTERNS:
        if pattern in lower:
            return False, pattern
    return True, ""


def execute_cmd(cmd: str) -> str:
    if not cmd or not cmd.strip():
        return "Comando vacío."
    safe, reason = _is_safe(cmd)
    if not safe:
        return (
            f"Comando bloqueado por seguridad: contiene '{reason}'.\n"
            "Si necesitas esta operación, hazla manualmente."
        )
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True,
            text=True, timeout=30
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        if stdout and stderr:
            return f"{stdout}\n[Advertencias]: {stderr}"
        return stdout or stderr or "(sin salida)"
    except subprocess.TimeoutExpired:
        return "Error: el comando superó el tiempo límite de 30 segundos."
    except Exception as exc:
        return f"Error al ejecutar el comando: {exc}"


def get_time() -> str:
    now = datetime.datetime.now()
    return now.strftime("%H:%M — %d/%m/%Y")


def get_sysinfo() -> str:
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        return (
            f"CPU: {cpu}%  |  "
            f"RAM: {ram.percent}% usada "
            f"({ram.used // 1024**2} MB / {ram.total // 1024**2} MB)"
        )
    except ImportError:
        return f"psutil no instalado. Plataforma: {platform.platform()}"


def open_app(name: str) -> str:
    if not name or not name.strip():
        return "Especifica el nombre de la aplicación."
    apps = {
        "chrome":    "start chrome",
        "firefox":   "start firefox",
        "notepad":   "notepad",
        "calc":      "calc",
        "calculadora": "calc",
        "explorer":  "explorer",
        "spotify":   "start spotify",
        "vscode":    "code",
        "paint":     "mspaint",
        "word":      "start winword",
        "excel":     "start excel",
    }
    key = name.lower().strip()
    cmd = apps.get(key, f"start {name}")
    return execute_cmd(cmd)
