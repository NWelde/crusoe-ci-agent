"""Small, redaction-safe client for Crusoe's OpenAI-compatible inference API."""

from __future__ import annotations

import json
import os
import time
from typing import TypeVar
from urllib.parse import urlparse

import requests
from pydantic import BaseModel, ValidationError

DEFAULT_BASE_URL = "https://api.inference.crusoecloud.com/v1"
T = TypeVar("T", bound=BaseModel)


class InferenceError(RuntimeError):
    """An actionable inference failure that never includes request credentials."""


class CrusoeInference:
    """Call Crusoe chat completions with bounded retries and no payload logging."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 30,
        max_retries: int = 2,
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.session = session or requests.Session()
        parsed = urlparse(self.base_url)
        local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not local_http:
            raise ValueError("Crusoe endpoint must use HTTPS (HTTP is allowed only for localhost tests).")
        if not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Crusoe endpoint must be a plain HTTPS base URL without embedded credentials or query.")
        if not self.api_key:
            raise ValueError("CRUSOE_API_KEY is required.")
        if not self.model:
            raise ValueError("CRUSOE_MODEL is required.")
        if timeout_seconds <= 0 or max_retries < 0:
            raise ValueError("timeout must be positive and retries cannot be negative.")

    @classmethod
    def from_env(cls, *, timeout_seconds: float = 90) -> CrusoeInference:
        """Build a client from environment variables without echoing their values."""
        missing = [name for name in ("CRUSOE_API_KEY", "CRUSOE_MODEL") if not os.getenv(name, "").strip()]
        if missing:
            raise InferenceError("Missing configuration: " + ", ".join(missing))
        try:
            return cls(
                api_key=os.environ["CRUSOE_API_KEY"],
                model=os.environ["CRUSOE_MODEL"],
                base_url=os.getenv("CRUSOE_BASE_URL", "").strip() or DEFAULT_BASE_URL,
                timeout_seconds=timeout_seconds,
            )
        except ValueError as exc:
            raise InferenceError(str(exc)) from exc

    def complete(self, *, system_prompt: str, user_prompt: str, max_tokens: int = 2048) -> str:
        """Return one assistant message. Prompts and responses are never logged."""
        if not system_prompt.strip() or not user_prompt.strip():
            raise ValueError("system_prompt and user_prompt must both be non-empty.")
        if not 1 <= max_tokens <= 8192:
            raise ValueError("max_tokens must be between 1 and 8192.")
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.post(
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt < self.max_retries:
                    time.sleep(0.25 * (2**attempt))
                    continue
                kind = "timed out" if isinstance(exc, requests.Timeout) else "could not connect"
                raise InferenceError(f"Crusoe inference {kind}; check the endpoint and network, then retry.") from None
            except requests.RequestException as exc:
                raise InferenceError(
                    f"Crusoe request failed ({type(exc).__name__}); check endpoint configuration."
                ) from None

            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self.max_retries:
                    time.sleep(0.25 * (2**attempt))
                    continue
                if response.status_code == 429:
                    raise InferenceError("Crusoe rate limit reached after bounded retries; retry later.")
                raise InferenceError(f"Crusoe service returned HTTP {response.status_code} after bounded retries.")
            if response.status_code in {401, 403}:
                raise InferenceError("Crusoe rejected the API key; check its validity and project access.")
            if not response.ok:
                raise InferenceError(f"Crusoe returned HTTP {response.status_code}; check model and request settings.")
            try:
                data = response.json()
                choice = data["choices"][0]
                content = choice["message"]["content"]
                finish_reason = choice.get("finish_reason")
            except (ValueError, KeyError, IndexError, TypeError):
                raise InferenceError("Crusoe returned an unexpected response shape; no response body was saved.") from None
            if not isinstance(content, str) or not content.strip():
                if attempt < self.max_retries:
                    time.sleep(0.25 * (2**attempt))
                    continue
                reason = f" (finish reason: {finish_reason})" if finish_reason else ""
                raise InferenceError(f"Crusoe returned an empty message{reason}.")
            return content.strip()
        raise AssertionError("retry loop must return or raise")

    def complete_structured(self, *, system_prompt: str, user_prompt: str, output_model: type[T]) -> T:
        """Request JSON matching a Pydantic schema and validate the response."""
        schema = json.dumps(output_model.model_json_schema(), sort_keys=True)
        content = self.complete(
            system_prompt=(
                system_prompt.rstrip()
                + "\nReturn only one JSON object matching this schema; do not include markdown.\n"
                + schema
            ),
            user_prompt=user_prompt,
            max_tokens=8192,
        )
        try:
            return output_model.model_validate_json(content)
        except ValidationError as exc:
            issues = "; ".join(
                f"{'.'.join(str(part) for part in issue['loc']) or '<root>'}: {issue['type']}"
                for issue in exc.errors()
            )
            raise InferenceError(
                "Crusoe response did not match the required structured output schema"
                + (f" ({issues})." if issues else ".")
            ) from None


def proposer_call(client: CrusoeInference, *, system_prompt: str, user_prompt: str,
                  output_model: type[T]) -> T:
    """Structured proposer call; accepts its own prompt pair, separate from verification."""
    return client.complete_structured(
        system_prompt=system_prompt, user_prompt=user_prompt, output_model=output_model
    )


def verifier_call(client: CrusoeInference, *, system_prompt: str, user_prompt: str,
                  output_model: type[T]) -> T:
    """Structured verifier call with independently supplied instructions and evidence."""
    return client.complete_structured(
        system_prompt=system_prompt, user_prompt=user_prompt, output_model=output_model
    )
