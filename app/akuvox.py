from __future__ import annotations
from typing import Any

import httpx

from .config import Settings


class AkuvoxClient:
    def __init__(self, settings: Settings) -> None:
        self._base_url = f"{settings.akuvox_scheme}://{settings.akuvox_ip}"
        self._auth = (settings.akuvox_username, settings.akuvox_password)
        self._verify_ssl = settings.akuvox_verify_ssl
        self._debug = settings.akuvox_debug
        self._timeout = settings.akuvox_timeout_seconds

    def get_users(self) -> Any:
        with httpx.Client(
            base_url=self._base_url,
            auth=self._auth,
            timeout=self._timeout,
            follow_redirects=True,
            verify=self._verify_ssl,
        ) as client:
            response = client.get("/api/user/get")
            if self._debug:
                print(f"[AKUVOX_DEBUG] GET /api/user/get -> status={response.status_code}", flush=True)
            response.raise_for_status()
            return self._parse_json_or_text(response)

    def set_user(self, payload: dict[str, Any]) -> Any:
        with httpx.Client(
            base_url=self._base_url,
            auth=self._auth,
            timeout=self._timeout,
            follow_redirects=True,
            verify=self._verify_ssl,
        ) as client:
            if self._debug:
                print(f"[AKUVOX_DEBUG] POST /api/user/set payload={payload}", flush=True)
            response = client.post("/api/user/set", json=payload)
            if self._debug:
                print(f"[AKUVOX_DEBUG] POST /api/user/set -> status={response.status_code}", flush=True)
            response.raise_for_status()
            return self._parse_json_or_text(response)

    @staticmethod
    def _parse_json_or_text(response: httpx.Response) -> Any:
        ctype = response.headers.get("content-type", "")
        if "application/json" in ctype:
            return response.json()
        return {"raw": response.text}
