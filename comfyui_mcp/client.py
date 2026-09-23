"""Thin synchronous HTTP client for the ComfyUI REST API."""

from __future__ import annotations

import base64
import os
import time
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

DEFAULT_BASE_URL = "http://10.0.54.157:8188"


class ComfyUIError(RuntimeError):
    """Raised when a ComfyUI request fails or times out."""


class ComfyUIClient:
    """A small wrapper around ComfyUI's REST endpoints.

    Configuration comes from constructor args, falling back to environment
    variables, falling back to sensible defaults:
      * COMFYUI_URL          (default: http://10.0.54.157:8188)
      * COMFYUI_TIMEOUT      (default: 120s)  -- per-request HTTP timeout
      * COMFYUI_WAIT_TIMEOUT (default: 900s)  -- max time to wait for a generation
      * COMFYUI_POLL_INTERVAL(default: 1.0s)
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        wait_timeout: Optional[float] = None,
        poll_interval: Optional[float] = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("COMFYUI_URL", DEFAULT_BASE_URL)).rstrip("/")
        # Per-request HTTP timeout (individual calls are fast).
        self.timeout = float(timeout or os.environ.get("COMFYUI_TIMEOUT", "120"))
        # Total time to wait for a generation to finish (cold model loads can be slow).
        self.wait_timeout = float(wait_timeout or os.environ.get("COMFYUI_WAIT_TIMEOUT", "900"))
        self.poll_interval = float(poll_interval or os.environ.get("COMFYUI_POLL_INTERVAL", "1.0"))
        self._http = httpx.Client(base_url=self.base_url, timeout=self.timeout)

    # -- low level ---------------------------------------------------------- #
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ComfyUIError(f"Could not reach ComfyUI at {self.base_url}: {exc}") from exc
        if resp.status_code >= 400:
            raise ComfyUIError(f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:500]}")
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.content

    # -- system / discovery ------------------------------------------------- #
    def system_stats(self) -> Any:
        return self._request("GET", "/system_stats")

    def queue(self) -> Any:
        return self._request("GET", "/queue")

    def object_info(self, node_type: Optional[str] = None) -> Any:
        path = "/object_info" if node_type is None else f"/object_info/{node_type}"
        return self._request("GET", path)

    def models(self) -> Any:
        return self._request("GET", "/models")

    def models_for(self, category: str) -> Any:
        return self._request("GET", f"/models/{category}")

    # -- job lifecycle ------------------------------------------------------ #
    def history(self, prompt_id: Optional[str] = None) -> Any:
        path = "/history" if prompt_id is None else f"/history/{prompt_id}"
        return self._request("GET", path)

    def prompt(self, workflow: dict[str, Any], front: bool = False, number: int = -1) -> Any:
        body = {"prompt": workflow, "front": front, "number": number}
        return self._request("POST", "/prompt", json=body)

    def interrupt(self) -> Any:
        return self._request("POST", "/interrupt")

    def free(self, unload_models: bool = False, rerun_outputs: bool = False) -> Any:
        return self._request("POST", "/free", json={"unload_models": unload_models, "rerun_outputs": rerun_outputs})

    # -- media -------------------------------------------------------------- #
    def view_bytes(self, filename: str, subfolder: str = "", media_type: str = "output") -> bytes:
        params = {"filename": filename, "subfolder": subfolder, "type": media_type}
        try:
            resp = self._http.get("/view", params=params)
        except httpx.HTTPError as exc:
            raise ComfyUIError(f"Could not reach ComfyUI at {self.base_url}: {exc}") from exc
        if resp.status_code >= 400:
            raise ComfyUIError(f"GET /view -> HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.content

    def view_base64(self, filename: str, subfolder: str = "", media_type: str = "output") -> str:
        return base64.b64encode(self.view_bytes(filename, subfolder, media_type)).decode("ascii")

    def view_url(self, filename: str, subfolder: str = "", media_type: str = "output") -> str:
        params = urlencode({"filename": filename, "subfolder": subfolder, "type": media_type})
        return f"{self.base_url}/view?{params}"

    # -- wait / extract ----------------------------------------------------- #
    def wait_for_completion(
        self,
        prompt_id: str,
        timeout: Optional[float] = None,
        poll_interval: Optional[float] = None,
    ) -> dict[str, Any]:
        """Poll /history/{prompt_id} until the job reports outputs or a terminal
        status. Returns the completed history entry (a dict)."""
        timeout = self.wait_timeout if timeout is None else timeout
        interval = self.poll_interval if poll_interval is None else poll_interval
        deadline = time.time() + timeout
        while True:
            data = self.history(prompt_id)
            # ComfyUI nests the entry under its prompt_id key
            # ({"<prompt_id>": {"outputs": ..., "status": ...}}), so unwrap it.
            entry = data.get(prompt_id) if isinstance(data, dict) and prompt_id in data else data
            if isinstance(entry, dict) and entry:
                status = (entry.get("status") or {})
                if entry.get("outputs") or status.get("status_str") in ("success", "error", "interrupted"):
                    return entry
            if time.time() >= deadline:
                raise ComfyUIError(f"Timed out after {timeout:.0f}s waiting for prompt {prompt_id}")
            time.sleep(interval)


def extract_media(entry: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Pull image and audio outputs out of a completed history entry.

    Returns {"images": [{filename, subfolder, type}], "audio": [...]}.
    """
    images: list[dict[str, str]] = []
    audio: list[dict[str, str]] = []
    for node_out in (entry.get("outputs") or {}).values():
        if not isinstance(node_out, dict):
            continue
        for item in node_out.get("images") or []:
            images.append({"filename": item.get("filename", ""), "subfolder": item.get("subfolder", ""), "type": item.get("type", "output")})
        for item in node_out.get("audio") or []:
            audio.append({"filename": item.get("filename", ""), "subfolder": item.get("subfolder", ""), "type": item.get("type", "output")})
    return {"images": images, "audio": audio}