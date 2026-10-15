import base64
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.client import AIInvalidResponseError
from app.ai.course_image_parser import CourseImageParser, normalize_extracted_courses
from app.main import app, get_course_image_parser


class FakeImageClient:
    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output
        self.request: dict[str, Any] | None = None

    async def generate_image_text(self, **request: Any) -> str:
        self.request = request
        return json.dumps(self.output)


def extracted_payload() -> dict[str, Any]:
    return {
        "courses": [
            {
                "code": "CSE 414",
                "title": "Database Systems",
                "groups": [
                    {
                        "type": "lecture",
                        "choose": 1,
                        "sections": [
                            {
                                "id": "A",
                                "status": "open",
                                "sln": "12345",
                                "meetings": [
                                    {
                                        "days": ["M", "W", "F"],
                                        "startTime": "09:30",
                                        "endTime": "10:20",
                                        "location": "KNE 120",
                                    }
                                ],
                                "parentSectionId": None,
                                "requiredSectionIds": [],
                            }
                        ],
                    },
                    {
                        "type": "quiz",
                        "choose": 1,
                        "sections": [
                            {
                                "id": "AA",
                                "status": "open",
                                "sln": "12346",
                                "meetings": [
                                    {
                                        "days": ["Th"],
                                        "startTime": "12:30",
                                        "endTime": "13:20",
                                        "location": "LOW 101",
                                    }
                                ],
                                "parentSectionId": "A",
                                "requiredSectionIds": [],
                            }
                        ],
                    },
                ],
            }
        ],
        "warnings": ["Verify the room number."],
    }


def test_course_image_parser_returns_validated_linked_sections() -> None:
    fake_client = FakeImageClient(extracted_payload())
    parser = CourseImageParser(fake_client)

    import asyncio

    result = asyncio.run(parser.parse("aW1hZ2U=", "image/png"))

    assert result.courses[0].code == "CSE 414"
    assert result.courses[0].groups[1].sections[0].parent_section_id == "A"
    assert fake_client.request is not None
    assert fake_client.request["response_schema_name"] == "course_image_extraction"


def test_normalization_merges_duplicate_groups_and_uses_course_hint() -> None:
    raw = {
        "courses": [
            {
                "code": "UNKNOWN",
                "title": "",
                "groups": [
                    {
                        "type": "lecture",
                        "choose": 1,
                        "sections": [
                            {
                                "id": "a",
                                "status": "OPEN",
                                "sln": 17092,
                                "parentSectionId": None,
                                "requiredSectionIds": [],
                                "meetings": [{"days": ["M", "W", "F"], "startTime": "12:30 PM", "endTime": "1:20 PM", "location": "KNE 120"}],
                            }
                        ],
                    },
                    {
                        "type": "lecture",
                        "choose": 1,
                        "sections": [
                            {
                                "id": "b",
                                "status": "open",
                                "sln": "17093",
                                "parentSectionId": None,
                                "requiredSectionIds": [],
                                "meetings": [{"days": ["M", "W", "F"], "startTime": "8:30 AM", "endTime": "9:20 AM", "location": "KNE 120"}],
                            }
                        ],
                    },
                ],
            }
        ],
        "warnings": [],
    }

    normalized = normalize_extracted_courses(raw, course_code_hint="math 208")
    course = normalized["courses"][0]

    assert course["code"] == "MATH 208"
    assert len(course["groups"]) == 1
    assert [section["id"] for section in course["groups"][0]["sections"]] == ["A", "B"]
    assert course["groups"][0]["sections"][0]["meetings"][0]["startTime"] == "12:30"
    assert course["groups"][0]["sections"][1]["meetings"][0]["startTime"] == "08:30"


def test_course_image_parser_explains_when_no_sections_are_found() -> None:
    parser = CourseImageParser(FakeImageClient({
        "courses": [{"code": "CSE 414", "title": None, "groups": []}],
        "warnings": [],
    }))

    import asyncio

    with pytest.raises(AIInvalidResponseError, match="no lecture, quiz, or lab sections were found"):
        asyncio.run(parser.parse("aW1hZ2U=", "image/png", course_code_hint="CSE 414"))


def test_normalization_drops_blank_placeholder_rows_but_keeps_valid_sections() -> None:
    raw = extracted_payload()
    raw["courses"][0]["title"] = "   "
    raw["courses"][0]["groups"][0]["sections"].append({
        "id": " ",
        "status": "unknown",
        "sln": "",
        "meetings": [],
        "parentSectionId": "",
        "requiredSectionIds": [],
    })

    normalized = normalize_extracted_courses(raw, course_code_hint="CSE 414")

    assert normalized["courses"][0]["title"] is None
    assert [section["id"] for section in normalized["courses"][0]["groups"][0]["sections"]] == ["A"]
    assert any("blank section row" in warning for warning in normalized["warnings"])


def test_extract_courses_endpoint_returns_editable_courses() -> None:
    fake_client = FakeImageClient(extracted_payload())
    app.dependency_overrides[get_course_image_parser] = lambda: CourseImageParser(fake_client)
    try:
        response = TestClient(app).post(
            "/api/courses/extract-from-image",
            json={
                "imageBase64": base64.b64encode(b"image").decode(),
                "mediaType": "image/png",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["courses"][0]["groups"][1]["sections"][0]["parentSectionId"] == "A"
    assert response.json()["warnings"] == ["Verify the room number."]


def test_extract_courses_endpoint_rejects_invalid_image_data() -> None:
    fake_client = FakeImageClient(extracted_payload())
    app.dependency_overrides[get_course_image_parser] = lambda: CourseImageParser(fake_client)
    try:
        response = TestClient(app).post(
            "/api/courses/extract-from-image",
            json={"imageBase64": "not base64", "mediaType": "image/png"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "valid base64" in response.text
