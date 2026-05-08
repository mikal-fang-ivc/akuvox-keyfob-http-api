from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ManagersData:
    full_access: set[str]
    limited_access: set[str]


class ManagersStore:
    def __init__(self, json_path: Path, bootstrap_full_email: str) -> None:
        self.json_path = json_path
        self.bootstrap_full_email = bootstrap_full_email.strip().lower()
        self._ensure_exists()

    def get_role(self, email: str) -> str | None:
        target = email.strip().lower()
        data = self._load()
        if target in data.full_access:
            return "full"
        if target in data.limited_access:
            return "limited"
        return None

    def list_managers(self) -> list[dict[str, str]]:
        data = self._load()
        result: list[dict[str, str]] = []
        for email in sorted(data.full_access):
            result.append({"email": email, "role": "full"})
        for email in sorted(data.limited_access):
            result.append({"email": email, "role": "limited"})
        return result

    def upsert(self, email: str, role: str) -> None:
        em = email.strip().lower()
        if not em:
            raise ValueError("Email is required")
        if role not in {"full", "limited"}:
            raise ValueError("Role must be full or limited")

        data = self._load()
        data.full_access.discard(em)
        data.limited_access.discard(em)
        if role == "full":
            data.full_access.add(em)
        else:
            data.limited_access.add(em)
        self._save(data)

    def remove(self, email: str) -> None:
        em = email.strip().lower()
        data = self._load()
        was_full = em in data.full_access

        data.full_access.discard(em)
        data.limited_access.discard(em)

        if was_full and len(data.full_access) == 0:
            raise ValueError("Cannot remove the last full-access manager")

        self._save(data)

    def _ensure_exists(self) -> None:
        if self.json_path.exists():
            return
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        init = {
            "full_access": [self.bootstrap_full_email] if self.bootstrap_full_email else [],
            "limited_access": [],
        }
        self.json_path.write_text(json.dumps(init, indent=2) + "\n", encoding="utf-8")

    def _load(self) -> ManagersData:
        if not self.json_path.exists():
            self._ensure_exists()
        raw = json.loads(self.json_path.read_text(encoding="utf-8"))
        full = {str(x).strip().lower() for x in raw.get("full_access", []) if str(x).strip()}
        limited = {str(x).strip().lower() for x in raw.get("limited_access", []) if str(x).strip()}
        limited -= full
        if not full and self.bootstrap_full_email:
            full.add(self.bootstrap_full_email)
            self._save(ManagersData(full_access=full, limited_access=limited))
        return ManagersData(full_access=full, limited_access=limited)

    def _save(self, data: ManagersData) -> None:
        payload = {
            "full_access": sorted(data.full_access),
            "limited_access": sorted(data.limited_access - data.full_access),
        }
        self.json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
