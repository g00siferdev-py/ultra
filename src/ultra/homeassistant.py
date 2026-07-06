"""Home Assistant REST API client for Linux Ultra."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from ultra.config import Config


@dataclass
class HAResult:
    ok: bool
    status_code: int
    data: Any
    error: str | None = None


class HomeAssistantClient:
    def __init__(self, config: Config) -> None:
        self.cfg = config.smart_home.home_assistant
        self.base_url = self.cfg.url.rstrip("/")
        self._token = self.cfg.resolve_token()

    @property
    def configured(self) -> bool:
        return self.cfg.enabled and bool(self._token)

    def _headers(self) -> dict[str, str]:
        if not self._token:
            raise RuntimeError(
                "Home Assistant token not configured. "
                "Create a long-lived token in HA → Profile → Security → Long-Lived Access Tokens, "
                "then save it to smart_home.home_assistant.token or token_file in config."
            )
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> HAResult:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.request(method, url, headers=self._headers(), json=body)
            if resp.status_code == 204:
                return HAResult(ok=True, status_code=204, data=None)
            try:
                data = resp.json()
            except json.JSONDecodeError:
                data = resp.text
            ok = 200 <= resp.status_code < 300
            return HAResult(ok=ok, status_code=resp.status_code, data=data, error=None if ok else str(data))
        except httpx.RequestError as exc:
            return HAResult(ok=False, status_code=0, data=None, error=str(exc))

    def check_api(self) -> HAResult:
        if not self.cfg.enabled:
            return HAResult(ok=False, status_code=0, data=None, error="Home Assistant disabled in config")
        if not self._token:
            # Unauthenticated ping — onboarding may still be in progress
            try:
                with httpx.Client(timeout=10.0) as client:
                    resp = client.get(f"{self.base_url}/")
                running = resp.status_code in (200, 302, 401)
                msg = "Home Assistant is reachable but no API token is configured yet."
                return HAResult(ok=running, status_code=resp.status_code, data={"message": msg})
            except httpx.RequestError as exc:
                return HAResult(ok=False, status_code=0, data=None, error=str(exc))
        return self._request("GET", "/api/")

    def get_states(self) -> HAResult:
        return self._request("GET", "/api/states")

    def get_state(self, entity_id: str) -> HAResult:
        return self._request("GET", f"/api/states/{entity_id}")

    def call_service(
        self,
        domain: str,
        service: str,
        *,
        entity_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> HAResult:
        payload: dict[str, Any] = dict(data or {})
        if entity_id:
            payload["entity_id"] = entity_id
        return self._request("POST", f"/api/services/{domain}/{service}", body=payload)

    def summarize_states(self, *, limit: int = 40) -> str:
        result = self.get_states()
        if not result.ok:
            return f"Failed to load states: {result.error or result.data}"
        states = result.data
        if not isinstance(states, list):
            return str(states)
        lines = [f"{len(states)} entities registered."]
        for item in states[:limit]:
            if not isinstance(item, dict):
                continue
            eid = item.get("entity_id", "?")
            state = item.get("state", "?")
            name = (item.get("attributes") or {}).get("friendly_name", "")
            label = f" ({name})" if name else ""
            lines.append(f"  {eid}{label}: {state}")
        if len(states) > limit:
            lines.append(f"  ... and {len(states) - limit} more")
        return "\n".join(lines)
