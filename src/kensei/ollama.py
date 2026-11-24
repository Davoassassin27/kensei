from __future__ import annotations

import json
import os
from typing import Any

import httpx


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 300.0,
    ):
        self.base_url = (base_url or os.environ.get("KENSEI_OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/")
        self.model = model or os.environ.get("KENSEI_MODEL") or "kensei"
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response
        except httpx.ConnectError as exc:
            raise OllamaError(
                f"No pude conectar a Ollama en {self.base_url}. "
                "¿Está corriendo? `systemctl status ollama` o `ollama serve`."
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise OllamaError(f"Ollama devolvió {exc.response.status_code}: {detail}") from exc
        except httpx.HTTPError as exc:
            raise OllamaError(f"Error hablando con Ollama: {exc}") from exc

    def tags(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/api/tags")
        return list(response.json().get("models", []))

    def has_model(self, name: str | None = None) -> bool:
        target = (name or self.model).split(":")[0]
        for model in self.tags():
            candidate = str(model.get("name", "")).split(":")[0]
            if candidate == target:
                return True
        return False

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        options: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": False,
            "options": options or {},
        }
        if tools:
            payload["tools"] = tools
        response = self._request("POST", "/api/chat", json=payload)
        data = response.json()
        message = data.get("message") or {}
        content = message.get("content")
        if content is None:
            raise OllamaError(f"Respuesta inesperada de Ollama: {json.dumps(data)[:500]}")
        return str(content)

    def pull(self, model: str) -> None:
        response = self._request("POST", "/api/pull", json={"model": model, "stream": False})
        if response.status_code >= 400:
            raise OllamaError(response.text[:500])
