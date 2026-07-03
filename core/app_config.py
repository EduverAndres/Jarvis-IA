import json
import os
import shutil
import threading

from config.providers import DEFAULT_PROVIDER, get_provider


class AppConfig:
    """Persiste el proveedor/modelo de IA activo — misma forma que core.memory.Memory."""

    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        for candidate in (self._path, self._path + ".bak"):
            if os.path.exists(candidate):
                try:
                    with open(candidate, encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    continue
        return {
            "provider": DEFAULT_PROVIDER,
            "model": get_provider(DEFAULT_PROVIDER)["default_model"],
        }

    def _save(self):
        if os.path.exists(self._path):
            try:
                shutil.copy2(self._path, self._path + ".bak")
            except OSError:
                pass
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def get(self) -> dict:
        with self._lock:
            return dict(self._data)

    def set(self, provider: str, model: str):
        with self._lock:
            self._data = {"provider": provider, "model": model}
            self._save()
