from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    OpenAIError,
)


class AIClientError(Exception):
    """Base error safe to serialize from the API layer."""

    code = "ai_request_failed"
    status_code = 502


class AIConfigurationError(AIClientError):
    code = "ai_not_configured"
    status_code = 503


class AIRequestTimeoutError(AIClientError):
    code = "ai_request_timeout"
    status_code = 504


class AIConnectionFailure(AIClientError):
    code = "ai_connection_failed"
    status_code = 502


class AIProviderError(AIClientError):
    code = "ai_provider_error"
    status_code = 502


class AIAuthenticationError(AIClientError):
    code = "ai_authentication_failed"
    status_code = 502


class AIRateLimitError(AIClientError):
    code = "ai_rate_limited"
    status_code = 503


class AIInvalidResponseError(AIClientError):
    code = "ai_invalid_response"
    status_code = 502


@dataclass(frozen=True, slots=True)
class AIClientSettings:
    api_key: str = field(repr=False)
    model: str
    timeout_seconds: float

    @classmethod
    def from_env(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> AIClientSettings:
        values = os.environ if environment is None else environment
        api_key = values.get("OPENAI_API_KEY", "").strip()
        model = values.get("OPENAI_MODEL", "").strip()
        timeout_value = values.get("AI_PREFERENCE_TIMEOUT_SECONDS", "20").strip()

        if not api_key:
            raise AIConfigurationError("OPENAI_API_KEY is not configured")
        if not model:
            raise AIConfigurationError("OPENAI_MODEL is not configured")

        try:
            timeout_seconds = float(timeout_value)
        except ValueError as error:
            raise AIConfigurationError(
                "AI_PREFERENCE_TIMEOUT_SECONDS must be a number"
            ) from error
        if timeout_seconds <= 0:
            raise AIConfigurationError(
                "AI_PREFERENCE_TIMEOUT_SECONDS must be greater than zero"
            )

        return cls(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
        )


class AIClient:
    """Application-owned wrapper around the OpenAI Responses API."""

    def __init__(
        self,
        settings: AIClientSettings | None = None,
        *,
        sdk_client: Any | None = None,
    ) -> None:
        self.settings = settings or AIClientSettings.from_env()
        self._sdk_client = sdk_client or AsyncOpenAI(
            api_key=self.settings.api_key,
            timeout=self.settings.timeout_seconds,
            max_retries=0,
        )

    async def generate_text(
        self,
        *,
        instructions: str,
        input_text: str,
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str = "structured_response",
    ) -> str:
        """Generate text and translate provider failures into stable app errors."""
        return await self._generate(
            instructions=instructions,
            input_data=input_text,
            response_schema=response_schema,
            response_schema_name=response_schema_name,
        )

    async def generate_image_text(
        self,
        *,
        instructions: str,
        image_base64: str,
        media_type: str,
        input_text: str = "Extract every visible course section from this image.",
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str = "structured_response",
    ) -> str:
        """Generate validated text from an inline image input."""
        input_data = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": input_text,
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:{media_type};base64,{image_base64}",
                        "detail": "high",
                    },
                ],
            }
        ]
        return await self._generate(
            instructions=instructions,
            input_data=input_data,
            response_schema=response_schema,
            response_schema_name=response_schema_name,
        )

    async def _generate(
        self,
        *,
        instructions: str,
        input_data: Any,
        response_schema: dict[str, Any] | None,
        response_schema_name: str,
    ) -> str:
        request: dict[str, Any] = {
            "model": self.settings.model,
            "instructions": instructions,
            "input": input_data,
        }
        if response_schema is not None:
            request["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": response_schema_name,
                    "strict": True,
                    "schema": response_schema,
                }
            }

        try:
            response = await self._sdk_client.responses.create(**request)
        except APITimeoutError as error:
            raise AIRequestTimeoutError(
                f"AI request timed out after {self.settings.timeout_seconds:g} seconds"
            ) from error
        except APIConnectionError as error:
            raise AIConnectionFailure("Unable to connect to the AI service") from error
        except APIStatusError as error:
            if error.status_code in {401, 403}:
                raise AIAuthenticationError(
                    "AI service authentication failed"
                ) from error
            if error.status_code == 429:
                raise AIRateLimitError(
                    "AI service rate limit was exceeded; try again later"
                ) from error
            raise AIProviderError(
                f"AI service returned HTTP {error.status_code}"
            ) from error
        except OpenAIError as error:
            raise AIProviderError("AI service request failed") from error

        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise AIInvalidResponseError("AI service returned an empty response")
        return output_text.strip()


@lru_cache(maxsize=1)
def get_ai_client() -> AIClient:
    """Return the process-wide AI client configured from the environment."""
    return AIClient()
