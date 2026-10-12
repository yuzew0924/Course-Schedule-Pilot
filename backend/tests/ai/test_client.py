import asyncio
import json
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from app.ai.client import (
    AIClient,
    AIClientSettings,
    AIAuthenticationError,
    AIConfigurationError,
    AIConnectionFailure,
    AIInvalidResponseError,
    AIProviderError,
    AIRateLimitError,
    AIRequestTimeoutError,
    get_ai_client,
)
from app.main import handle_ai_client_error


@dataclass
class FakeResponse:
    output_text: str


class FakeResponses:
    def __init__(self, *, result: Any = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.last_request: dict[str, Any] | None = None

    async def create(self, **request: Any) -> Any:
        self.last_request = request
        if self.error is not None:
            raise self.error
        return self.result


class FakeSDKClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


def settings() -> AIClientSettings:
    return AIClientSettings(
        api_key="secret-test-key",
        model="test-model",
        timeout_seconds=20,
    )


def test_settings_are_loaded_from_environment_without_exposing_key() -> None:
    config = AIClientSettings.from_env(
        {
            "OPENAI_API_KEY": "secret-value",
            "OPENAI_MODEL": "test-model",
            "AI_PREFERENCE_TIMEOUT_SECONDS": "12.5",
        }
    )

    assert config.model == "test-model"
    assert config.timeout_seconds == 12.5
    assert "secret-value" not in repr(config)


def test_shared_client_factory_uses_environment_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_sdk_factory(**configuration: object) -> FakeSDKClient:
        captured.update(configuration)
        return FakeSDKClient(FakeResponses(result=FakeResponse("unused")))

    monkeypatch.setenv("OPENAI_API_KEY", "environment-key")
    monkeypatch.setenv("OPENAI_MODEL", "environment-model")
    monkeypatch.setenv("AI_PREFERENCE_TIMEOUT_SECONDS", "7")
    monkeypatch.setattr("app.ai.client.AsyncOpenAI", fake_sdk_factory)
    get_ai_client.cache_clear()

    first = get_ai_client()
    second = get_ai_client()

    assert first is second
    assert first.settings.model == "environment-model"
    assert captured == {
        "api_key": "environment-key",
        "timeout": 7.0,
        "max_retries": 0,
    }
    get_ai_client.cache_clear()


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({}, "OPENAI_API_KEY"),
        ({"OPENAI_API_KEY": "key"}, "OPENAI_MODEL"),
        (
            {
                "OPENAI_API_KEY": "key",
                "OPENAI_MODEL": "model",
                "AI_PREFERENCE_TIMEOUT_SECONDS": "invalid",
            },
            "must be a number",
        ),
        (
            {
                "OPENAI_API_KEY": "key",
                "OPENAI_MODEL": "model",
                "AI_PREFERENCE_TIMEOUT_SECONDS": "0",
            },
            "greater than zero",
        ),
    ],
)
def test_invalid_ai_configuration_is_rejected(
    environment: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(AIConfigurationError, match=message):
        AIClientSettings.from_env(environment)


def test_generate_text_uses_configured_model_and_returns_trimmed_text() -> None:
    responses = FakeResponses(result=FakeResponse("  parsed output  "))
    client = AIClient(settings(), sdk_client=FakeSDKClient(responses))

    result = asyncio.run(
        client.generate_text(instructions="Parse preferences", input_text="No Fridays")
    )

    assert result == "parsed output"
    assert responses.last_request == {
        "model": "test-model",
        "instructions": "Parse preferences",
        "input": "No Fridays",
    }


def test_generate_text_sends_strict_json_schema() -> None:
    responses = FakeResponses(result=FakeResponse("{}"))
    client = AIClient(settings(), sdk_client=FakeSDKClient(responses))
    schema = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": False,
    }

    asyncio.run(
        client.generate_text(
            instructions="Return JSON",
            input_text="Input",
            response_schema=schema,
            response_schema_name="test_schema",
        )
    )

    assert responses.last_request is not None
    assert responses.last_request["text"] == {
        "format": {
            "type": "json_schema",
            "name": "test_schema",
            "strict": True,
            "schema": schema,
        }
    }


def test_generate_image_text_sends_inline_image() -> None:
    responses = FakeResponses(result=FakeResponse('{"courses":[]}'))
    client = AIClient(settings(), sdk_client=FakeSDKClient(responses))

    result = asyncio.run(
        client.generate_image_text(
            instructions="Extract courses",
            image_base64="aW1hZ2U=",
            media_type="image/png",
        )
    )

    assert result == '{"courses":[]}'
    assert responses.last_request is not None
    assert responses.last_request["input"][0]["content"] == [
        {
            "type": "input_text",
            "text": "Extract every visible course section from this image.",
        },
        {
            "type": "input_image",
            "image_url": "data:image/png;base64,aW1hZ2U=",
            "detail": "high",
        },
    ]


@pytest.mark.parametrize(
    ("provider_error", "application_error"),
    [
        (
            APITimeoutError(httpx.Request("POST", "https://api.openai.com")),
            AIRequestTimeoutError,
        ),
        (
            APIConnectionError(
                request=httpx.Request("POST", "https://api.openai.com")
            ),
            AIConnectionFailure,
        ),
        (
            APIStatusError(
                "provider failed",
                response=httpx.Response(
                    500,
                    request=httpx.Request("POST", "https://api.openai.com"),
                ),
                body=None,
            ),
            AIProviderError,
        ),
        (
            APIStatusError(
                "invalid key",
                response=httpx.Response(
                    401,
                    request=httpx.Request("POST", "https://api.openai.com"),
                ),
                body=None,
            ),
            AIAuthenticationError,
        ),
        (
            APIStatusError(
                "rate limited",
                response=httpx.Response(
                    429,
                    request=httpx.Request("POST", "https://api.openai.com"),
                ),
                body=None,
            ),
            AIRateLimitError,
        ),
    ],
)
def test_provider_failures_are_translated(
    provider_error: Exception,
    application_error: type[Exception],
) -> None:
    client = AIClient(
        settings(),
        sdk_client=FakeSDKClient(FakeResponses(error=provider_error)),
    )

    with pytest.raises(application_error):
        asyncio.run(client.generate_text(instructions="Parse", input_text="Input"))


def test_empty_provider_response_is_rejected() -> None:
    client = AIClient(
        settings(),
        sdk_client=FakeSDKClient(FakeResponses(result=FakeResponse("  "))),
    )

    with pytest.raises(AIInvalidResponseError, match="empty response"):
        asyncio.run(client.generate_text(instructions="Parse", input_text="Input"))


def test_fastapi_error_handler_returns_stable_json() -> None:
    response = asyncio.run(
        handle_ai_client_error(
            None,  # type: ignore[arg-type]
            AIRequestTimeoutError("AI request timed out after 20 seconds"),
        )
    )

    assert response.status_code == 504
    assert json.loads(response.body) == {
        "error": {
            "code": "ai_request_timeout",
            "message": "AI request timed out after 20 seconds",
        }
    }
