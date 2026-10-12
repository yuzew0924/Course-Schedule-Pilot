import json
from typing import Any

from fastapi.testclient import TestClient

from app.ai.client import AIRequestTimeoutError
from app.main import app
from app.models import GenerateSchedulesApiResponse, ParsedPreferences


def courses() -> list[dict[str, object]]:
    return [
        {
            "code": "CSE 373",
            "title": "Data Structures and Algorithms",
            "groups": [
                {
                    "type": "lecture",
                    "sections": [
                        {
                            "id": "A",
                            "status": "open",
                            "meetings": [
                                {
                                    "days": ["M"],
                                    "startTime": "09:30",
                                    "endTime": "10:20",
                                }
                            ],
                        },
                        {
                            "id": "B",
                            "status": "open",
                            "meetings": [
                                {
                                    "days": ["M"],
                                    "startTime": "13:30",
                                    "endTime": "14:20",
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    ]


def parsed_request(**overrides: Any) -> dict[str, object]:
    payload: dict[str, object] = {
        "courses": courses(),
        "preferences": {
            "preferredTimeOfDay": "afternoon",
            "requireOpenSections": True,
        },
        "topN": 1,
        "enhanceReasons": False,
    }
    payload.update(overrides)
    return payload


def test_generate_endpoint_returns_ranked_top_n_and_valid_schema() -> None:
    response = TestClient(app).post(
        "/api/schedules/generate",
        json=parsed_request(),
    )

    assert response.status_code == 200
    body = response.json()
    validated = GenerateSchedulesApiResponse.model_validate(body)
    assert set(body) == {
        "interpretedPreferences",
        "schedules",
        "count",
        "warnings",
    }
    assert set(body["interpretedPreferences"]) == {
        "earliestStart",
        "earliestStartIsHard",
        "preferredDaysOff",
        "requiredDaysOff",
        "preferredTimeOfDay",
            "gapPreference",
            "allowedGapMinutes",
            "minimumLongGapMinutes",
            "fixedSections",
        "requireOpenSections",
        "hardConstraints",
        "softPreferences",
        "conflicts",
        "needsClarification",
        "clarificationQuestions",
    }
    assert validated.count == 1
    assert len(validated.schedules) == 1
    schedule = body["schedules"][0]
    assert set(schedule) == {
        "rank",
        "score",
        "sections",
        "scoreBreakdown",
        "reasons",
        "tradeoffs",
    }
    assert schedule["rank"] == 1
    assert isinstance(schedule["score"], (int, float))
    assert schedule["sections"][0]["sectionId"] == "B"
    assert set(schedule["scoreBreakdown"]) == {
        "earliestStart",
        "preferredTimeOfDay",
        "gaps",
        "preferredDaysOff",
    }
    assert isinstance(schedule["reasons"], list)
    assert isinstance(schedule["tradeoffs"], list)
    assert schedule["score"] == sum(
        item["score"] for item in schedule["scoreBreakdown"].values()
    )
    earliest = schedule["scoreBreakdown"]["earliestStart"]
    assert set(earliest) == {
        "score",
        "maximum",
        "scoreDelta",
        "matchedPreference",
        "details",
        "reasonCandidate",
        "tradeoffCandidate",
        "affectedSections",
        "affectedMeetings",
    }


def test_generate_endpoint_accepts_preference_text(monkeypatch: Any) -> None:
    class SuccessfulParser:
        async def parse(
            self,
            preference_text: str,
            supplied_courses: object,
        ) -> ParsedPreferences:
            assert preference_text == "I prefer afternoon classes."
            assert supplied_courses
            return ParsedPreferences(preferredTimeOfDay="afternoon")

    monkeypatch.setattr("app.main.get_preference_parser", lambda: SuccessfulParser())
    response = TestClient(app).post(
        "/api/schedules/generate",
        json={
            "courses": courses(),
            "preferenceText": "I prefer afternoon classes.",
            "topN": 1,
            "enhanceReasons": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["interpretedPreferences"]["preferredTimeOfDay"] == "afternoon"
    assert body["schedules"][0]["sections"][0]["sectionId"] == "B"


def test_generate_endpoint_honors_top_n_and_is_deterministic() -> None:
    payload = parsed_request(topN=2)

    first_response = TestClient(app).post(
        "/api/schedules/generate",
        json=payload,
    )
    second_response = TestClient(app).post(
        "/api/schedules/generate",
        json=payload,
    )

    assert first_response.status_code == second_response.status_code == 200
    first = GenerateSchedulesApiResponse.model_validate(first_response.json())
    second = GenerateSchedulesApiResponse.model_validate(second_response.json())
    assert first == second
    assert first.count == 2
    assert first.count <= payload["topN"]
    assert [schedule.rank for schedule in first.schedules] == [1, 2]
    assert all(schedule.reasons for schedule in first.schedules)
    assert all(isinstance(schedule.tradeoffs, list) for schedule in first.schedules)


def test_generate_endpoint_returns_stable_empty_result() -> None:
    response = TestClient(app).post(
        "/api/schedules/generate",
        json=parsed_request(
            preferences={
                "requiredDaysOff": ["M"],
                "requireOpenSections": True,
            }
        ),
    )

    assert response.status_code == 200
    assert response.json()["schedules"] == []
    assert response.json()["count"] == 0
    assert response.json()["warnings"] == [
        "Hard day-off or earliest-start constraints eliminate the remaining combinations.",
        "All remaining combinations have meeting conflicts or incompatible course-component requirements.",
    ]


def test_parser_failure_stops_before_scheduler(
    monkeypatch: Any,
) -> None:
    scheduler_called = False

    class FailingParser:
        async def parse(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            raise AIRequestTimeoutError("AI request timed out")

    def fail_if_called(*args: Any, **kwargs: Any) -> tuple[()]:
        del args, kwargs
        nonlocal scheduler_called
        scheduler_called = True
        return ()

    monkeypatch.setattr("app.main.get_preference_parser", lambda: FailingParser())
    monkeypatch.setattr("app.generation.generate_schedule_candidates", fail_if_called)
    response = TestClient(app).post(
        "/api/schedules/generate",
        json={
            "courses": courses(),
            "preferenceText": "Prefer afternoon classes",
            "enhanceReasons": False,
        },
    )

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "ai_request_timeout"
    assert not scheduler_called


def test_reason_ai_failure_uses_deterministic_reasons(monkeypatch: Any) -> None:
    class InvalidReasonClient:
        async def generate_text(self, **request: Any) -> str:
            del request
            return "not json"

    monkeypatch.setattr("app.main.get_ai_client", lambda: InvalidReasonClient())
    response = TestClient(app).post(
        "/api/schedules/generate",
        json=parsed_request(enhanceReasons=True),
    )

    assert response.status_code == 200
    assert "No time conflicts" in response.json()["schedules"][0]["reasons"]


def test_reason_ai_cannot_change_scores_or_ranks(monkeypatch: Any) -> None:
    class EchoReasonClient:
        async def generate_text(self, **request: Any) -> str:
            payload = json.loads(request["input_text"])
            return json.dumps(
                {
                    "reasons": payload["baseReasons"],
                    "tradeoffs": payload["baseTradeoffs"],
                }
            )

    baseline = TestClient(app).post(
        "/api/schedules/generate",
        json=parsed_request(enhanceReasons=False),
    ).json()
    monkeypatch.setattr("app.main.get_ai_client", lambda: EchoReasonClient())
    enhanced = TestClient(app).post(
        "/api/schedules/generate",
        json=parsed_request(enhanceReasons=True),
    ).json()

    assert [item["rank"] for item in enhanced["schedules"]] == [
        item["rank"] for item in baseline["schedules"]
    ]
    assert [item["score"] for item in enhanced["schedules"]] == [
        item["score"] for item in baseline["schedules"]
    ]
    assert [item["scoreBreakdown"] for item in enhanced["schedules"]] == [
        item["scoreBreakdown"] for item in baseline["schedules"]
    ]
