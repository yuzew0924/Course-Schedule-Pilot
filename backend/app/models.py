from __future__ import annotations

import base64
import binascii
from datetime import time
from enum import Enum
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_serializer,
    field_validator,
    model_validator,
)

from .scheduler.time_utils import DayCode, parse_time_string


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class APIModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class SectionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class SectionType(str, Enum):
    LECTURE = "lecture"
    QUIZ = "quiz"
    LAB = "lab"
    DISCUSSION = "discussion"
    OTHER = "other"


class PreferredTimeOfDay(str, Enum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    NONE = "none"


class GapPreference(str, Enum):
    COMPACT = "compact"
    BALANCED = "balanced"
    BREAKS = "breaks"
    NONE = "none"


class Meeting(APIModel):
    days: list[DayCode] = Field(min_length=1)
    start_time: time
    end_time: time
    location: str | None = None

    @field_validator("days")
    @classmethod
    def validate_unique_days(cls, days: list[DayCode]) -> list[DayCode]:
        if len(days) != len(set(days)):
            raise ValueError("meeting days must not contain duplicates")
        return days

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def validate_time_format(cls, value: object) -> object:
        return parse_time_string(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_time_range(self) -> Self:
        if self.start_time >= self.end_time:
            raise ValueError("startTime must be earlier than endTime")
        return self

    @field_serializer("start_time", "end_time", when_used="json")
    def serialize_time(self, value: time) -> str:
        return value.strftime("%H:%M")


class Section(APIModel):
    id: str = Field(min_length=1, pattern=r"^[A-Z0-9]+$")
    status: SectionStatus
    sln: str | None = None
    meetings: list[Meeting]
    parent_section_id: str | None = Field(
        default=None,
        min_length=1,
        pattern=r"^[A-Z0-9]+$",
    )
    required_section_ids: list[str] = Field(default_factory=list)

    @field_validator("required_section_ids")
    @classmethod
    def validate_required_section_ids(cls, section_ids: list[str]) -> list[str]:
        if any(not section_id for section_id in section_ids):
            raise ValueError("required section IDs must not be empty")
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("required section IDs must not contain duplicates")
        return section_ids

    @model_validator(mode="after")
    def validate_no_self_dependency(self) -> Self:
        if self.id in self.required_section_ids:
            raise ValueError("a section cannot require itself")
        return self


class SectionGroup(APIModel):
    type: SectionType
    choose: Literal[1] = 1
    sections: list[Section]


class Course(APIModel):
    code: str = Field(min_length=1)
    groups: list[SectionGroup] = Field(min_length=1)
    title: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_groups_and_dependencies(self) -> Self:
        group_types = [group.type for group in self.groups]
        if len(group_types) != len(set(group_types)):
            raise ValueError("section group types must be unique within a course")

        sections: dict[str, Section] = {}
        section_types: dict[str, SectionType] = {}
        for group in self.groups:
            for section in group.sections:
                if section.id in sections:
                    raise ValueError("section IDs must be unique within a course")
                sections[section.id] = section
                section_types[section.id] = group.type

        lecture_ids = {
            section.id
            for group in self.groups
            if group.type is SectionType.LECTURE
            for section in group.sections
        }
        for group in self.groups:
            for section in group.sections:
                if group.type is SectionType.LECTURE:
                    if section.parent_section_id is not None:
                        raise ValueError(
                            f"lecture section {section.id} must not have parentSectionId"
                        )
                    continue
                if group.type not in {SectionType.QUIZ, SectionType.LAB}:
                    continue

                parent_id = section.parent_section_id or section.id[0]
                if parent_id not in lecture_ids:
                    raise ValueError(
                        f"section {section.id} parentSectionId must reference a "
                        f"lecture section in the same course: {parent_id}"
                    )
                section.parent_section_id = parent_id

                required_lecture_ids = {
                    required_id
                    for required_id in section.required_section_ids
                    if section_types.get(required_id) is SectionType.LECTURE
                }
                if required_lecture_ids and required_lecture_ids != {parent_id}:
                    raise ValueError(
                        f"section {section.id} has conflicting lecture dependencies"
                    )

        for section in sections.values():
            for required_id in section.required_section_ids:
                if required_id not in sections:
                    raise ValueError(
                        f"section {section.id} requires unknown section {required_id}"
                    )
                if section_types[required_id] is section_types[section.id]:
                    raise ValueError("section dependencies must reference another group")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(section_id: str) -> None:
            if section_id in visiting:
                raise ValueError("section dependencies must not contain cycles")
            if section_id in visited:
                return

            visiting.add(section_id)
            for required_id in sections[section_id].required_section_ids:
                visit(required_id)
            visiting.remove(section_id)
            visited.add(section_id)

        for section_id in sections:
            visit(section_id)

        return self


class Preferences(APIModel):
    """Validated preferences consumed by the scheduling engine."""

    earliest_start: time | None = None
    allow_earlier_if_only_option: bool = False
    allowed_gap_minutes: int | None = Field(default=None, ge=0)
    minimum_long_gap_minutes: int | None = Field(default=None, ge=0)
    require_open_sections: bool = True
    fixed_sections: dict[str, list[str]] = Field(default_factory=dict)
    required_days_off: list[DayCode] = Field(default_factory=list)
    preferred_days_off: list[DayCode] = Field(default_factory=list)
    preferred_time_of_day: PreferredTimeOfDay = PreferredTimeOfDay.NONE
    gap_preference: GapPreference = GapPreference.NONE

    @field_validator("earliest_start", mode="before")
    @classmethod
    def validate_earliest_start_format(cls, value: object) -> object:
        return parse_time_string(value) if isinstance(value, str) else value

    @field_validator("fixed_sections")
    @classmethod
    def validate_fixed_sections(
        cls, fixed_sections: dict[str, list[str]]
    ) -> dict[str, list[str]]:
        for course_code, section_ids in fixed_sections.items():
            if not course_code:
                raise ValueError("fixed section course codes must not be empty")
            if not section_ids or any(not section_id for section_id in section_ids):
                raise ValueError("fixed section ID lists must not be empty")
            if len(section_ids) != len(set(section_ids)):
                raise ValueError("fixed section IDs must not contain duplicates")
        return fixed_sections

    @field_validator("required_days_off", "preferred_days_off")
    @classmethod
    def validate_unique_required_days(cls, days: list[DayCode]) -> list[DayCode]:
        if len(days) != len(set(days)):
            raise ValueError("day-off lists must not contain duplicates")
        return days

    @field_serializer("earliest_start", when_used="json")
    def serialize_earliest_start(self, value: time | None) -> str | None:
        return value.strftime("%H:%M") if value is not None else None


class ParsedPreferences(APIModel):
    """Strict structured output accepted from an AI preference parser."""

    earliest_start: time | None = None
    earliest_start_is_hard: StrictBool = False
    preferred_days_off: list[DayCode] = Field(default_factory=list)
    required_days_off: list[DayCode] = Field(default_factory=list)
    preferred_time_of_day: PreferredTimeOfDay = PreferredTimeOfDay.NONE
    gap_preference: GapPreference = GapPreference.NONE
    allowed_gap_minutes: int | None = Field(default=None, ge=0)
    minimum_long_gap_minutes: int | None = Field(default=None, ge=0)
    fixed_sections: list[str] = Field(default_factory=list)
    require_open_sections: StrictBool = True
    hard_constraints: list[str] = Field(default_factory=list)
    soft_preferences: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    needs_clarification: StrictBool = False
    clarification_questions: list[str] = Field(default_factory=list)

    @field_validator("earliest_start", mode="before")
    @classmethod
    def validate_earliest_start_format(cls, value: object) -> object:
        return parse_time_string(value) if isinstance(value, str) else value

    @field_validator("preferred_days_off", "required_days_off")
    @classmethod
    def validate_unique_preferred_days(cls, days: list[DayCode]) -> list[DayCode]:
        if len(days) != len(set(days)):
            raise ValueError("day-off lists must not contain duplicates")
        return days

    @field_validator("fixed_sections")
    @classmethod
    def validate_fixed_section_references(cls, references: list[str]) -> list[str]:
        if len(references) != len(set(references)):
            raise ValueError("fixedSections must not contain duplicates")
        for reference in references:
            try:
                course_code, section_id = reference.rsplit(" ", 1)
            except ValueError as error:
                raise ValueError(
                    "fixedSections entries must use '<course code> <section ID>'"
                ) from error
            if (
                not course_code
                or not section_id.isalnum()
                or section_id != section_id.upper()
            ):
                raise ValueError(
                    "fixedSections entries must use '<course code> <section ID>'"
                )
        return references

    @field_validator(
        "hard_constraints",
        "soft_preferences",
        "conflicts",
        "clarification_questions",
    )
    @classmethod
    def validate_preference_notes(cls, notes: list[str]) -> list[str]:
        if any(not note for note in notes):
            raise ValueError("preference notes must not be empty")
        if len(notes) != len(set(notes)):
            raise ValueError("preference notes must not contain duplicates")
        return notes

    @model_validator(mode="after")
    def validate_hard_earliest_start(self) -> Self:
        if self.earliest_start_is_hard and self.earliest_start is None:
            raise ValueError("earliestStart is required when earliestStartIsHard is true")
        if self.conflicts and not self.needs_clarification:
            raise ValueError("conflicts require needsClarification to be true")
        if self.needs_clarification and not self.clarification_questions:
            raise ValueError(
                "clarificationQuestions are required when needsClarification is true"
            )
        if self.clarification_questions and not self.needs_clarification:
            raise ValueError(
                "needsClarification must be true when clarificationQuestions are set"
            )
        if (
            self.allowed_gap_minutes is not None
            and self.minimum_long_gap_minutes is not None
            and self.allowed_gap_minutes >= self.minimum_long_gap_minutes
        ):
            raise ValueError(
                "allowedGapMinutes must be less than minimumLongGapMinutes"
            )
        return self

    @field_serializer("earliest_start", when_used="json")
    def serialize_earliest_start(self, value: time | None) -> str | None:
        return value.strftime("%H:%M") if value is not None else None

    def to_scheduler_preferences(self) -> Preferences:
        """Convert validated AI output into scheduler-safe preferences."""
        fixed_sections: dict[str, list[str]] = {}
        for reference in self.fixed_sections:
            course_code, section_id = reference.rsplit(" ", 1)
            fixed_sections.setdefault(course_code, []).append(section_id)

        return Preferences(
            earliest_start=self.earliest_start,
            allow_earlier_if_only_option=(
                self.earliest_start is not None and not self.earliest_start_is_hard
            ),
            require_open_sections=self.require_open_sections,
            fixed_sections=fixed_sections,
            required_days_off=self.required_days_off,
            preferred_days_off=self.preferred_days_off,
            preferred_time_of_day=self.preferred_time_of_day,
            gap_preference=self.gap_preference,
            allowed_gap_minutes=self.allowed_gap_minutes,
            minimum_long_gap_minutes=self.minimum_long_gap_minutes,
        )


class ScheduleRequest(APIModel):
    courses: list[Course] = Field(min_length=1)
    preferences: Preferences = Field(default_factory=Preferences)

    @model_validator(mode="after")
    def validate_courses_and_fixed_sections(self) -> Self:
        course_codes = [course.code for course in self.courses]
        if len(course_codes) != len(set(course_codes)):
            raise ValueError("course codes must be unique within a request")

        available_sections: dict[str, dict[str, Section]] = {}
        for course in self.courses:
            course_sections: dict[str, Section] = {}
            for group in course.groups:
                for section in group.sections:
                    course_sections[section.id] = section
            available_sections[course.code] = course_sections

        for course_code, section_ids in self.preferences.fixed_sections.items():
            course_sections = available_sections.get(course_code)
            if course_sections is None:
                raise ValueError(f"fixed section course does not exist: {course_code}")

            for section_id in section_ids:
                section = course_sections.get(section_id)
                if section is None:
                    raise ValueError(
                        f"fixed section does not exist: {course_code} {section_id}"
                    )
                if (
                    self.preferences.require_open_sections
                    and section.status is not SectionStatus.OPEN
                ):
                    raise ValueError(
                        "fixed section must be open when requireOpenSections is true: "
                        f"{course_code} {section_id}"
                    )

        return self


class ParsePreferencesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    courses: list[Course] = Field(min_length=1)
    preferenceText: str = Field(min_length=1)

    @field_validator("preferenceText")
    @classmethod
    def validate_preference_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("preferenceText must not be blank")
        return value


class ExtractCoursesFromImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    imageBase64: str = Field(min_length=1)
    mediaType: Literal["image/png", "image/jpeg", "image/webp"]
    courseCodeHint: str | None = Field(default=None, min_length=1)
    courseTitleHint: str | None = Field(default=None, min_length=1)

    @field_validator("imageBase64")
    @classmethod
    def validate_image_base64(cls, value: str) -> str:
        try:
            image_bytes = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("imageBase64 must contain valid base64 data") from error
        if not image_bytes:
            raise ValueError("imageBase64 must not be empty")
        if len(image_bytes) > 10 * 1024 * 1024:
            raise ValueError("image must not exceed 10 MB")
        return value


class ExtractCoursesFromImageResponse(APIModel):
    courses: list[Course] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class GenerateSchedulesApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    courses: list[Course] = Field(min_length=1)
    preferenceText: str | None = None
    preferences: ParsedPreferences | None = None
    topN: int = Field(default=5, ge=1, le=50)
    enhanceReasons: bool = True

    @model_validator(mode="after")
    def validate_preference_source(self) -> Self:
        if (self.preferenceText is None) == (self.preferences is None):
            raise ValueError(
                "exactly one of preferenceText or preferences must be provided"
            )
        if self.preferenceText is not None and not self.preferenceText.strip():
            raise ValueError("preferenceText must not be blank")
        return self


class SelectedSection(APIModel):
    course_code: str = Field(min_length=1)
    group_type: SectionType
    section: Section


class ScheduleOption(APIModel):
    id: str = Field(min_length=1)
    rank: int = Field(ge=1)
    score: float = Field(ge=0, le=100)
    selections: list[SelectedSection] = Field(min_length=1)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GenerateScheduleResponse(APIModel):
    schedules: list[ScheduleOption]
    count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_schedules(self) -> Self:
        if self.count != len(self.schedules):
            raise ValueError("count must equal the number of returned schedules")

        schedule_ids = [schedule.id for schedule in self.schedules]
        if len(schedule_ids) != len(set(schedule_ids)):
            raise ValueError("schedule IDs must be unique")

        expected_ranks = list(range(1, len(self.schedules) + 1))
        if [schedule.rank for schedule in self.schedules] != expected_ranks:
            raise ValueError("schedules must be ordered with consecutive ranks")

        return self


class AffectedMeeting(APIModel):
    course_code: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    day: DayCode
    start_time: time
    end_time: time

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def validate_time_format(cls, value: object) -> object:
        return parse_time_string(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_time_range(self) -> Self:
        if self.start_time >= self.end_time:
            raise ValueError("startTime must be earlier than endTime")
        return self

    @field_serializer("start_time", "end_time", when_used="json")
    def serialize_time(self, value: time) -> str:
        return value.strftime("%H:%M")


class ScoreBreakdownItem(APIModel):
    score: float = Field(ge=0)
    maximum: float = Field(gt=0)
    score_delta: float = Field(le=0)
    matched_preference: str | None = Field(default=None, min_length=1)
    details: str = Field(min_length=1)
    reason_candidate: str | None = Field(default=None, min_length=1)
    tradeoff_candidate: str | None = Field(default=None, min_length=1)
    affected_sections: list[str] = Field(default_factory=list)
    affected_meetings: list[AffectedMeeting] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_score_calculation(self) -> Self:
        if self.score > self.maximum:
            raise ValueError("score must not exceed maximum")
        expected_delta = round(self.score - self.maximum, 2)
        if abs(self.score_delta - expected_delta) > 0.001:
            raise ValueError("scoreDelta must equal score minus maximum")
        return self


class ScheduleSection(APIModel):
    course_code: str = Field(min_length=1)
    group_type: SectionType
    section_id: str = Field(min_length=1)
    status: SectionStatus
    sln: str | None = None
    meetings: list[Meeting] = Field(default_factory=list)


class RankedSchedule(APIModel):
    rank: int = Field(ge=1)
    score: float = Field(ge=0, le=100)
    sections: list[ScheduleSection] = Field(min_length=1)
    score_breakdown: dict[str, ScoreBreakdownItem]
    reasons: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_score_breakdown(self) -> Self:
        expected_rules = {
            "earliestStart",
            "preferredTimeOfDay",
            "gaps",
            "preferredDaysOff",
        }
        if set(self.score_breakdown) != expected_rules:
            raise ValueError("scoreBreakdown must contain every scoring rule")
        calculated = round(sum(item.score for item in self.score_breakdown.values()), 2)
        if abs(calculated - self.score) > 0.001:
            raise ValueError("score must equal the scoreBreakdown total")
        return self


class GenerateSchedulesApiResponse(APIModel):
    interpreted_preferences: ParsedPreferences
    schedules: list[RankedSchedule]
    count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ranked_schedules(self) -> Self:
        if self.count != len(self.schedules):
            raise ValueError("count must equal the number of returned schedules")
        if [schedule.rank for schedule in self.schedules] != list(
            range(1, self.count + 1)
        ):
            raise ValueError("schedules must use consecutive ranks starting at 1")
        return self


GenerateScheduleRequest = ScheduleRequest
