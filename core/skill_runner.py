import re
from typing import Callable


def _ruta(exc: Exception) -> str:
    """Extrae solo el nombre de archivo/ruta de una excepción de sistema."""
    if exc.filename:
        return exc.filename
    return str(exc).split(":")[-1].strip().strip("'\"") or str(exc)

_SKILL_RE = re.compile(r'SKILL:\s*(\w+)([^\n]*)', re.MULTILINE)
_ARG_RE   = re.compile(r'(\w+)="([^"]*)"')

# Required args per skill — validated before execution
_REQUIRED: dict[str, list[str]] = {
    "create_folder":         ["path"],
    "create_file":           ["path"],
    "read_file":             ["path"],
    "write_file":            ["path"],
    "list_files":            [],
    "delete_item":           ["path"],
    "move_item":             ["src", "dst"],
    "rename_item":           ["path", "new_name"],
    "open_explorer":         [],
    "open_file":             ["path"],
    "create_python_project": ["path", "name"],
    "create_crud_project":   ["path", "name"],
    "create_web_project":    ["path", "name"],
    "run_command":           ["cmd"],
    "open_app":              ["name"],
    # Web / información en tiempo real
    "get_weather":           ["city"],
    "web_search":            ["query"],
    "get_wikipedia":         ["topic"],
    "get_news":              [],
    # Sistema local (sin internet)
    "get_time":              [],
    "get_sysinfo":           [],
    # Bluetooth
    "bluetooth_on":          [],
    "bluetooth_off":         [],
    "bluetooth_connect":     ["device"],
}


def _parse(text: str):
    for m in _SKILL_RE.finditer(text):
        name = m.group(1).strip()
        args = dict(_ARG_RE.findall(m.group(2)))
        yield name, args


def _validate(skill: str, args: dict) -> str | None:
    """Devuelve mensaje de error en español, o None si todo es válido."""
    required = _REQUIRED.get(skill)
    if required is None:
        return f"Función desconocida: '{skill}'. Verifica el nombre."
    missing = [k for k in required if not args.get(k, "").strip()]
    if missing:
        faltantes = ", ".join(f'"{m}"' for m in missing)
        return (f"La función '{skill}' necesita los parámetros: {faltantes}. "
                f"Por favor proporciona esa información.")
    return None


def run_skills(response: str, confirm_fn: Callable[[str], bool] = None) -> list[tuple]:
    """
    Parse and execute every SKILL: directive in `response`.
    confirm_fn(path) must return True before any delete proceeds.
    Returns list of (tag, skill_name, output_text).
    """
    from skills.file_skills import (
        create_folder, create_file, read_file, write_file,
        list_files, delete_item, move_item, rename_item,
        open_explorer, open_file,
    )
    from skills.project_skills import (
        create_python_project, create_crud_project, create_web_project,
    )
    from skills.system_skills import execute_cmd, open_app, get_time, get_sysinfo
    from skills.web_skills import get_weather, web_search, get_wikipedia, get_news
    from skills.bluetooth_skills import bluetooth_power, bluetooth_connect

    SKILLS = {
        "create_folder":         lambda a: create_folder(a["path"]),
        "create_file":           lambda a: create_file(a["path"], a.get("content", "")),
        "read_file":             lambda a: read_file(a["path"]),
        "write_file":            lambda a: write_file(a["path"], a.get("content", "")),
        "list_files":            lambda a: list_files(a.get("path", ".")),
        "delete_item":           lambda a: delete_item(a["path"], confirm_fn),
        "move_item":             lambda a: move_item(a["src"], a["dst"]),
        "rename_item":           lambda a: rename_item(a["path"], a["new_name"]),
        "open_explorer":         lambda a: open_explorer(a.get("path", ".")),
        "open_file":             lambda a: open_file(a["path"]),
        "create_python_project": lambda a: create_python_project(a["path"], a["name"]),
        "create_crud_project":   lambda a: create_crud_project(a["path"], a["name"]),
        "create_web_project":    lambda a: create_web_project(a["path"], a["name"]),
        "run_command":           lambda a: execute_cmd(a["cmd"]),
        "open_app":              lambda a: open_app(a["name"]),
        # Web / información en tiempo real
        "get_weather":           lambda a: get_weather(a["city"]),
        "web_search":            lambda a: web_search(a["query"], int(a.get("max", 4))),
        "get_wikipedia":         lambda a: get_wikipedia(a["topic"]),
        "get_news":              lambda a: get_news(a.get("topic", "")),
        # Sistema local
        "get_time":              lambda a: get_time(),
        "get_sysinfo":           lambda a: get_sysinfo(),
        # Bluetooth
        "bluetooth_on":          lambda a: bluetooth_power("on"),
        "bluetooth_off":         lambda a: bluetooth_power("off"),
        "bluetooth_connect":     lambda a: bluetooth_connect(a["device"]),
    }

    results = []
    for skill_name, args in _parse(response):
        err = _validate(skill_name, args)
        if err:
            results.append(("err", skill_name, err))
            continue
        fn = SKILLS.get(skill_name)
        if fn is None:
            results.append(("err", skill_name, f"Skill '{skill_name}' no implementada."))
            continue
        try:
            out = fn(args)
            results.append(("sys", skill_name, out))
        except FileNotFoundError as e:
            results.append(("err", skill_name,
                f"No se encontró el archivo o carpeta: {_ruta(e)}"))
        except FileExistsError as e:
            results.append(("err", skill_name,
                f"Ya existe un elemento con ese nombre: {_ruta(e)}"))
        except IsADirectoryError as e:
            results.append(("err", skill_name,
                f"La ruta indicada es una carpeta, no un archivo: {_ruta(e)}"))
        except NotADirectoryError as e:
            results.append(("err", skill_name,
                f"La ruta indicada no es una carpeta: {_ruta(e)}"))
        except PermissionError as e:
            results.append(("err", skill_name,
                f"Permiso denegado. {e}"))
        except ValueError as e:
            results.append(("err", skill_name, str(e)))
        except OSError as e:
            results.append(("err", skill_name,
                f"Error del sistema operativo al ejecutar '{skill_name}'. "
                f"Código: {e.errno}."))
        except Exception as e:
            results.append(("err", skill_name,
                f"Error inesperado al ejecutar '{skill_name}': {type(e).__name__}."))
    return results
