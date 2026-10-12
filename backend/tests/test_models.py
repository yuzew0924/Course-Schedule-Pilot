import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.models import (
    Course,
    GenerateScheduleResponse,
    GenerateSchedulesApiRequest,
    GenerateSchedulesApiResponse,
    Meeting,
    ParsedPreferences,
    Preferences,
    ScheduleRequest,
    ScoreBreakdownItem,
    Section,
    SectionGroup,
)


SAMPLE_DATA_PATH = Path(__file__).resolve().parents[2] / "sample-data" / "courses.json"


@pytest.fixture
def sample_request_data() -> dict[str, object]:
    return json.loads(SAMPLE_DATA_PATH.read_text())


def test_meeting_accepts_supported_weekdays() -> None:
    meeting = Meeting.model_validate(
        {
            "days": ["M", "W", "F"],
            "startTime": "09:30",
            "endTime": "10:20",
            "location": "KNE 120",
        }
    )

    assert meeting.model_dump(mode="json", by_alias=True) == {
        "days": ["M", "W", "F"],
        "startTime": "09:30",
        "endTime": "10:20",
        "location": "KNE 120",
    }


@pytest.mark.parametrize("day", ["Monday", "TH", "Sa", "X"])
def test_meeting_rejects_unsupported_weekday(day: str) -> None:
    with pytest.raises(ValidationError):
        Meeting.model_validate(
            {
                "days": [day],
                "startTime": "09:30",
                "endTime": "10:20",
            }
        )


@pytest.mark.parametrize("invalid_time", ["9:30", "09:30:00", "24:00", "09:60"])
def test_meeting_rejects_invalid_time_format(invalid_time: str) -> None:
    with pytest.raises(ValidationError, match="24-hour HH:MM format"):
        Meeting.model_validate(
            {
                "days": ["M"],
                "startTime": invalid_time,
                "endTime": "10:20",
            }
        )


@pytest.mark.parametrize(
    ("start_time", "end_time"),
    [("10:20", "10:20"), ("11:20", "10:20")],
)
def test_meeting_rejects_invalid_time_range(start_time: str, end_time: str) -> None:
    with pytest.raises(ValidationError, match="startTime must be earlier than endTime"):
        Meeting.model_validate(
            {
                "days": ["M"],
                "startTime": start_time,
                "endTime": end_time,
            }
        )


def test_section_can_contain_multiple_meetings() -> None:
    section = Section.model_validate(
        {
            "id": "A",
            "status": "open",
            "sln": "12345",
            "meetings": [
                {
                    "days": ["M", "W"],
                    "startTime": "09:30",
                    "endTime": "10:20",
                },
                {
                    "days": ["F"],
                    "startTime": "11:30",
                    "endTime": "12:20",
                },
            ],
        }
    )

    assert len(section.meetings) == 2


def test_section_group_accepts_valid_choose_count() -> None:
    group = SectionGroup.model_validate(
        {
            "type": "quiz",
            "choose": 1,
            "sections": [
                {
                    "id": "AA",
                    "status": "open",
                    "meetings": [],
                }
            ],
        }
    )

    assert group.choose == 1


def test_empty_section_group_is_valid_and_remains_required() -> None:
    group = SectionGroup(type="lab", sections=[])

    assert group.sections == []
    assert group.choose == 1


@pytest.mark.parametrize("choose", [0, 2])
def test_section_group_rejects_choose_other_than_one(choose: int) -> None:
    with pytest.raises(ValidationError):
        SectionGroup(type="quiz", choose=choose, sections=[])


def test_course_can_contain_multiple_section_groups() -> None:
    course = Course.model_validate(
        {
            "code": "CSE 123",
            "title": "Computer Programming III",
            "groups": [
                {"type": "lecture", "sections": []},
                {"type": "quiz", "sections": []},
                {"type": "lab", "sections": []},
            ],
        }
    )

    assert len(course.groups) == 3


def test_preferences_accept_documented_fields() -> None:
    preferences = Preferences.model_validate(
        {
            "earliestStart": "09:30",
            "allowEarlierIfOnlyOption": True,
            "allowedGapMinutes": 90,
            "minimumLongGapMinutes": 120,
            "requireOpenSections": True,
            "fixedSections": {"CSE 123": ["A", "AA"]},
        }
    )

    payload = preferences.model_dump(mode="json", by_alias=True)
    assert payload["earliestStart"] == "09:30"
    assert payload["allowedGapMinutes"] == 90
    assert payload["fixedSections"] == {"CSE 123": ["A", "AA"]}


@pytest.mark.parametrize("invalid_time", ["9:30", "09:30:00", "24:00", "09:60"])
def test_preferences_reject_invalid_earliest_start(invalid_time: str) -> None:
    with pytest.raises(ValidationError, match="24-hour HH:MM format"):
        Preferences.model_validate({"earliestStart": invalid_time})


@pytest.mark.parametrize(
    "field_name", ["allowedGapMinutes", "minimumLongGapMinutes"]
)
def test_preferences_reject_negative_gap_values(field_name: str) -> None:
    with pytest.raises(ValidationError):
        Preferences.model_validate({field_name: -1})


def test_request_rejects_unknown_fixed_course(
    sample_request_data: dict[str, object],
) -> None:
    invalid_request = deepcopy(sample_request_data)
    invalid_request["preferences"]["fixedSections"] = {"CSE 999": ["A"]}

    with pytest.raises(ValidationError, match="fixed section course does not exist"):
        ScheduleRequest.model_validate(invalid_request)


def test_request_rejects_unknown_fixed_section(
    sample_request_data: dict[str, object],
) -> None:
    invalid_request = deepcopy(sample_request_data)
    invalid_request["preferences"]["fixedSections"] = {"CSE 373": ["missing"]}

    with pytest.raises(ValidationError, match="fixed section does not exist"):
        ScheduleRequest.model_validate(invalid_request)


def test_sample_data_matches_request_model(sample_request_data: dict[str, object]) -> None:
    request = ScheduleRequest.model_validate(sample_request_data)

    assert len(request.courses) == 3
    assert request.preferences.earliest_start is not None


def test_sample_covers_group_driven_course_structures(
    sample_request_data: dict[str, object],
) -> None:
    request = ScheduleRequest.model_validate(sample_request_data)
    component_types = {
        course.code: [group.type.value for group in course.groups]
        for course in request.courses
    }

    assert component_types["CSE 373"] == ["lecture"]
    assert component_types["CHEM 142"] == ["lecture", "lab"]
    assert component_types["BIOL 180"] == ["lecture", "quiz", "lab"]


def test_parsing_does_not_add_missing_components() -> None:
    course = Course.model_validate(
        {
            "code": "CSE 373",
            "groups": [
                {
                    "type": "lecture",
                    "choose": 1,
                    "sections": [
                        {"id": "A", "status": "open", "meetings": []}
                    ],
                }
            ],
        }
    )

    assert [group.type.value for group in course.groups] == ["lecture"]


def test_request_accepts_lecture_only_course() -> None:
    request = ScheduleRequest.model_validate(
        {
            "courses": [
                {
                    "code": "CSE 373",
                    "groups": [
                        {
                            "type": "lecture",
                            "choose": 1,
                            "sections": [
                                {
                                    "id": "A",
                                    "status": "open",
                                    "meetings": [],
                                }
                            ],
                        }
                    ],
                }
            ],
            "preferences": {
                "earliestStart": "09:30",
                "allowEarlierIfOnlyOption": True,
                "allowedGapMinutes": 90,
                "minimumLongGapMinutes": 120,
                "requireOpenSections": True,
                "fixedSections": {},
            },
        }
    )

    assert [group.type.value for group in request.courses[0].groups] == ["lecture"]


def test_request_rejects_empty_courses() -> None:
    with pytest.raises(ValidationError):
        ScheduleRequest.model_validate({"courses": [], "preferences": {}})


def test_request_applies_nested_meeting_validation(
    sample_request_data: dict[str, object],
) -> None:
    invalid_request = deepcopy(sample_request_data)
    invalid_request["courses"][0]["groups"][0]["sections"][0][
        "meetings"
    ][0]["days"] = ["Saturday"]

    with pytest.raises(ValidationError):
        ScheduleRequest.model_validate(invalid_request)


def test_request_schema_uses_documented_json_names() -> None:
    properties = ScheduleRequest.model_json_schema(by_alias=True)["properties"]

    assert set(properties) == {"courses", "preferences"}


def test_core_model_schemas_use_documented_fields() -> None:
    meeting_schema = Meeting.model_json_schema(by_alias=True)
    section_schema = Section.model_json_schema(by_alias=True)
    group_schema = SectionGroup.model_json_schema(by_alias=True)
    course_schema = Course.model_json_schema(by_alias=True)
    preferences_schema = Preferences.model_json_schema(by_alias=True)
    parsed_preferences_schema = ParsedPreferences.model_json_schema(by_alias=True)

    assert set(meeting_schema["properties"]) == {
        "days",
        "startTime",
        "endTime",
        "location",
    }
    assert set(meeting_schema["required"]) == {"days", "startTime", "endTime"}
    assert set(section_schema["required"]) == {
        "id",
        "status",
        "meetings",
    }
    assert set(group_schema["properties"]) == {"type", "choose", "sections"}
    assert set(course_schema["properties"]) == {
        "code",
        "title",
        "groups",
    }
    assert set(preferences_schema["properties"]) == {
        "earliestStart",
        "allowEarlierIfOnlyOption",
        "allowedGapMinutes",
        "minimumLongGapMinutes",
        "requireOpenSections",
        "fixedSections",
        "requiredDaysOff",
        "preferredDaysOff",
        "preferredTimeOfDay",
        "gapPreference",
    }
    assert set(parsed_preferences_schema["properties"]) == {
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


def test_score_breakdown_rejects_inconsistent_delta() -> None:
    with pytest.raises(ValidationError, match="scoreDelta must equal"):
        ScoreBreakdownItem.model_validate(
            {
                "score": 20,
                "maximum": 25,
                "scoreDelta": 0,
                "details": "Five-point penalty",
            }
        )


def test_unknown_section_dependency_is_rejected(
    sample_request_data: dict[str, object],
) -> None:
    invalid_request = deepcopy(sample_request_data)
    courses = invalid_request["courses"]
    courses[1]["groups"][1]["sections"][0]["requiredSectionIds"] = [
        "missing"
    ]

    with pytest.raises(ValidationError, match="requires unknown section missing"):
        ScheduleRequest.model_validate(invalid_request)


def test_quiz_parent_must_reference_a_lecture_in_the_same_course() -> None:
    with pytest.raises(ValidationError, match="must reference a lecture section"):
        Course.model_validate(
            {
                "code": "CSE 312",
                "groups": [
                    {
                        "type": "lecture",
                        "sections": [
                            {"id": "A", "status": "open", "meetings": []}
                        ],
                    },
                    {
                        "type": "quiz",
                        "sections": [
                            {
                                "id": "BA",
                                "status": "open",
                                "parentSectionId": "B",
                                "meetings": [],
                            }
                        ],
                    },
                ],
            }
        )


def test_inferred_quiz_parent_must_exist() -> None:
    with pytest.raises(ValidationError, match=r"same course: B"):
        Course.model_validate(
            {
                "code": "CSE 312",
                "groups": [
                    {
                        "type": "lecture",
                        "sections": [
                            {"id": "A", "status": "open", "meetings": []}
                        ],
                    },
                    {
                        "type": "quiz",
                        "sections": [
                            {"id": "BA", "status": "open", "meetings": []}
                        ],
                    },
                ],
            }
        )


def test_lecture_rejects_parent_section_id() -> None:
    with pytest.raises(ValidationError, match="must not have parentSectionId"):
        Course.model_validate(
            {
                "code": "CSE 312",
                "groups": [
                    {
                        "type": "lecture",
                        "sections": [
                            {
                                "id": "A",
                                "status": "open",
                                "parentSectionId": "A",
                                "meetings": [],
                            }
                        ],
                    }
                ],
            }
        )


def test_generate_response_accepts_empty_scaffold() -> None:
    response = GenerateScheduleResponse.model_validate(
        {"schedules": [], "count": 0, "warnings": []}
    )

    assert response.model_dump(mode="json", by_alias=True) == {
        "schedules": [],
        "count": 0,
        "warnings": [],
    }


def test_generate_response_uses_typed_schedules() -> None:
    response = GenerateScheduleResponse.model_validate(
        {
            "schedules": [
                {
                    "id": "option-1",
                    "rank": 1,
                    "score": 94,
                    "selections": [
                        {
                            "courseCode": "CSE 414",
                            "groupType": "lecture",
                            "section": {
                                "id": "C",
                                "status": "open",
                                "meetings": [
                                    {
                                        "days": ["M", "W", "F"],
                                        "startTime": "12:30",
                                        "endTime": "13:20",
                                    }
                                ],
                            },
                        }
                    ],
                    "reasons": ["No conflicts"],
                }
            ],
            "count": 1,
        }
    )

    assert response.schedules[0].selections[0].course_code == "CSE 414"
    assert response.count == 1


def test_generate_response_rejects_incorrect_count() -> None:
    with pytest.raises(ValidationError, match="count must equal"):
        GenerateScheduleResponse.model_validate(
            {"schedules": [], "count": 1, "warnings": []}
        )


def test_models_can_be_used_as_fastapi_schemas() -> None:
    api = FastAPI()

    @api.post("/generate", response_model=GenerateScheduleResponse)
    def generate_schedules(
        request: ScheduleRequest,
    ) -> GenerateScheduleResponse:
        return GenerateScheduleResponse(schedules=[], count=0)

    operation = api.openapi()["paths"]["/generate"]["post"]
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    response_schema = operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ]

    assert request_schema["$ref"].endswith("/ScheduleRequest")
    assert response_schema["$ref"].endswith("/GenerateScheduleResponse")


@pytest.mark.parametrize(
    "payload",
    [
        {"courses": []},
        {"courses": [], "preferenceText": "text", "preferences": {}},
    ],
)
def test_generate_api_request_requires_one_preference_source(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        GenerateSchedulesApiRequest.model_validate(payload)


def test_generate_api_models_are_exposed_in_openapi() -> None:
    from app.main import app

    operation = app.openapi()["paths"]["/api/schedules/generate"]["post"]
    request_schema = operation["requestBody"]["content"]["application/json"][
        "schema"
    ]
    response_schema = operation["responses"]["200"]["content"][
        "application/json"
    ]["schema"]

    assert request_schema["$ref"].endswith("/GenerateSchedulesApiRequest")
    assert response_schema["$ref"].endswith("/GenerateSchedulesApiResponse")
    assert "interpretedPreferences" in GenerateSchedulesApiResponse.model_json_schema(
        by_alias=True
    )["properties"]
