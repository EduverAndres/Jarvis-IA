import os
import shutil
import subprocess
from datetime import datetime

_MAX_READ_BYTES = 10 * 1024 * 1024  # 10 MB
_DANGEROUS_ROOTS = {
    os.environ.get("SystemRoot", "C:\\Windows"),
    os.environ.get("SystemRoot", "C:\\Windows") + "\\System32",
    "C:\\Program Files",
    "C:\\Program Files (x86)",
}


# ── Internal validation ────────────────────────────────────────────────────

def _require_path(path: str, label: str = "path") -> str:
    if not path or not path.strip():
        raise ValueError(f"El {label} no puede estar vacío.")
    path = os.path.expandvars(os.path.expanduser(path.strip()))
    if len(path) > 260:
        raise ValueError(f"La ruta es demasiado larga (máx 260 caracteres).")
    return path


def _require_exists(path: str) -> str:
    path = _require_path(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"No existe: {path}")
    return path


def _guard_dangerous(path: str):
    abs_path = os.path.abspath(path).rstrip("\\")
    for root in _DANGEROUS_ROOTS:
        if abs_path.lower() == root.lower():
            raise PermissionError(
                f"Operación bloqueada: '{abs_path}' es una ruta protegida del sistema."
            )


def _safe_name(name: str) -> str:
    """Valida que el nombre de archivo no tenga separadores de ruta ni caracteres ilegales."""
    bad = set('/\\:*?"<>|')
    illegal = [c for c in name if c in bad]
    if illegal:
        raise ValueError(
            f"Nombre inválido. Caracteres no permitidos: {''.join(set(illegal))}"
        )
    if not name.strip():
        raise ValueError("El nombre del archivo no puede estar vacío.")
    return name.strip()


# ── Public API ────────────────────────────────────────────────────────────

def create_folder(path: str) -> str:
    path = _require_path(path)
    if os.path.isfile(path):
        raise FileExistsError(f"Ya existe un archivo con ese nombre: {path}")
    os.makedirs(path, exist_ok=True)
    return f"Carpeta creada: {path}"


def create_file(path: str, content: str = "") -> str:
    path = _require_path(path)
    if os.path.isdir(path):
        raise IsADirectoryError(f"La ruta es una carpeta, no un archivo: {path}")
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Archivo creado: {path}"


def read_file(path: str) -> str:
    path = _require_exists(path)
    if os.path.isdir(path):
        raise IsADirectoryError(f"Es una carpeta, usa list_files para listar: {path}")
    size = os.path.getsize(path)
    if size > _MAX_READ_BYTES:
        raise ValueError(
            f"Archivo demasiado grande ({size // 1024 // 1024} MB). "
            f"Máximo: {_MAX_READ_BYTES // 1024 // 1024} MB."
        )
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        raise ValueError(f"No se puede leer el archivo: es binario, no es texto plano. Ruta: {path}")


def write_file(path: str, content: str) -> str:
    path = _require_path(path)
    if os.path.isdir(path):
        raise IsADirectoryError(f"La ruta es una carpeta: {path}")
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Archivo guardado: {path}"


_LIST_MAX = 500   # máximo de items para no congelar la UI


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n // 1024} KB"
    return f"{n // 1024 // 1024} MB"


def list_files(path: str = ".") -> str:
    path = _require_path(path) if path and path.strip() else "."
    path = os.path.expandvars(os.path.expanduser(path))
    if not os.path.exists(path):
        raise FileNotFoundError(f"La ruta no existe: {path}")
    if not os.path.isdir(path):
        raise NotADirectoryError(f"No es una carpeta: {path}")
    all_items = sorted(os.listdir(path), key=str.lower)
    total     = len(all_items)
    items     = all_items[:_LIST_MAX]
    if not items:
        return f"(La carpeta está vacía: {path})"
    lines = []
    for item in items:
        full = os.path.join(path, item)
        if os.path.isdir(full):
            lines.append(f"📁 {item}/")
        else:
            try:
                st   = os.stat(full)
                size = _fmt_size(st.st_size)
                mod  = datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y")
                lines.append(f"📄 {item}  ({size}, {mod})")
            except OSError:
                lines.append(f"📄 {item}")
    header = f"Contenido de {path} ({total} elementos):\n"
    footer = f"\n... mostrando primeros {_LIST_MAX} de {total}." if total > _LIST_MAX else ""
    return header + "\n".join(lines) + footer


def delete_item(path: str, confirm_fn=None) -> str:
    path = _require_exists(path)
    _guard_dangerous(path)
    if confirm_fn is None:
        raise PermissionError(
            "Operación de eliminación bloqueada: se requiere confirmación del usuario antes de borrar."
        )
    if not confirm_fn(path):
        return "Eliminación cancelada por el usuario."
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)
    return f"Eliminado correctamente: {path}"


def move_item(src: str, dst: str) -> str:
    src = _require_exists(src)
    dst = _require_path(dst, label="destino")
    dst_parent = os.path.dirname(dst)
    if dst_parent and not os.path.exists(dst_parent):
        raise FileNotFoundError(
            f"La carpeta destino no existe: {dst_parent}"
        )
    if os.path.exists(dst) and not os.path.isdir(dst):
        raise FileExistsError(f"Ya existe un archivo en el destino: {dst}")
    shutil.move(src, dst)
    return f"Movido: {src} → {dst}"


def rename_item(path: str, new_name: str) -> str:
    path     = _require_exists(path)
    new_name = _safe_name(new_name)
    new_path = os.path.join(os.path.dirname(path), new_name)
    if os.path.exists(new_path):
        raise FileExistsError(f"Ya existe un elemento con ese nombre: {new_name}")
    os.rename(path, new_path)
    return f"Renombrado: {os.path.basename(path)} → {new_name}"


def open_explorer(path: str = ".") -> str:
    path = path if path and path.strip() else "."
    path = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
    if not os.path.exists(path):
        raise FileNotFoundError(f"La ruta no existe: {path}")
    subprocess.Popen(f'explorer "{path}"')
    return f"Explorador abierto en: {path}"


def open_file(path: str) -> str:
    path = _require_exists(path)
    if os.path.isdir(path):
        return open_explorer(path)
    os.startfile(path)
    return f"Abierto: {path}"
