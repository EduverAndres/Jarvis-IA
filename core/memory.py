import json
import os
import shutil
import threading
from datetime import datetime

_MAX_HISTORY = 60
_MAX_FACTS   = 100   # guardados en disco; se leen últimos 30 en el prompt


class Memory:
    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._data = self._load()

    # ── Persistence ───────────────────────────────────────────────────────

    def _load(self) -> dict:
        for candidate in (self._path, self._path + ".bak"):
            if os.path.exists(candidate):
                try:
                    with open(candidate, encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    continue
        return {"user": {}, "facts": [], "history": []}

    def _save(self):
        # Backup antes de sobrescribir (protege contra corrupción)
        if os.path.exists(self._path):
            try:
                shutil.copy2(self._path, self._path + ".bak")
            except OSError:
                pass
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def _safe_save(self):
        """Llama _save() bajo lock para evitar escrituras concurrentes."""
        with self._lock:
            self._save()

    # ── Conversation history ──────────────────────────────────────────────

    def add_message(self, role: str, content: str):
        with self._lock:
            self._data["history"].append({
                "role":    role,
                "content": content,
                "ts":      datetime.now().isoformat(),
            })
            if len(self._data["history"]) > _MAX_HISTORY:
                self._data["history"] = self._data["history"][-_MAX_HISTORY:]
            self._save()

    def get_history(self, limit: int = 20) -> list[dict]:
        with self._lock:
            return [
                {"role": m["role"], "content": m["content"]}
                for m in self._data["history"][-limit:]
            ]

    # ── Facts (long-term memory) ──────────────────────────────────────────

    def remember(self, fact: str):
        fact = fact.strip()
        if not fact:
            return
        with self._lock:
            # Deduplicación: ignora si ya existe un hecho muy similar
            existing = {f["text"].lower() for f in self._data["facts"]}
            fact_lower = fact.lower()
            # Coincidencia exacta o contenida
            if any(fact_lower == e or fact_lower in e or e in fact_lower
                   for e in existing):
                return
            self._data["facts"].append({"text": fact, "ts": datetime.now().isoformat()})
            if len(self._data["facts"]) > _MAX_FACTS:
                self._data["facts"] = self._data["facts"][-_MAX_FACTS:]
            self._save()

    def facts_text(self) -> str:
        with self._lock:
            return "\n".join(f"- {f['text']}" for f in self._data["facts"][-30:])

    # ── User profile ──────────────────────────────────────────────────────

    def set_user(self, key: str, value: str):
        with self._lock:
            self._data["user"][key] = value
            self._save()

    def user_text(self) -> str:
        with self._lock:
            u = self._data["user"]
            if not u:
                return ""
            return ", ".join(f"{k}: {v}" for k, v in u.items())
