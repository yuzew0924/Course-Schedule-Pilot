from __future__ import annotations

import json
import re
from collections import OrderedDict
from typing import Protocol

from pydantic import ValidationError

from ..models import ExtractCoursesFromImageResponse
from .client import AIInvalidResponseError
from .prompts import COURSE_IMAGE_PARSER_INSTRUCTIONS, COURSE_IMAGE_RESPONSE_SCHEMA


class ImageGenerationClient(Protocol):
    async def generate_image_text(
        self,
        *,
        instructions: str,
        image_base64: str,
        media_type: str,
        input_text: str = "Extract every visible course section from this image.",
        response_schema: dict[str, object] | None = None,
        response_schema_name: str = "structured_response",
    ) -> str: ...


class CourseImageParser:
    """Extract course data from an image and validate it before API use."""

    def __init__(self, client: ImageGenerationClient) -> None:
        self.client = client

    async def parse(
        self,
        image_base64: str,
        media_type: str,
        course_code_hint: str | None = None,
        course_title_hint: str | None = None,
    ) -> ExtractCoursesFromImageResponse:
        hints = ["Extract every visible course section from this image."]
        if course_code_hint:
            hints.append(f"Course code hint: {course_code_hint.strip().upper()}")
        if course_title_hint:
            hints.append(f"Course title hint: {course_title_hint.strip()}")
        output = await self.client.generate_image_text(
            instructions=COURSE_IMAGE_PARSER_INSTRUCTIONS,
            image_base64=image_base64,
            media_type=media_type,
            input_text="\n".join(hints),
            response_schema=COURSE_IMAGE_RESPONSE_SCHEMA,
            response_schema_name="course_image_extraction",
        )
        try:
            raw = json.loads(output)
            normalized = normalize_extracted_courses(
                raw,
                course_code_hint=course_code_hint,
                course_title_hint=course_title_hint,
            )
            return ExtractCoursesFromImageResponse.model_validate(normalized)
        except (json.JSONDecodeError, TypeError, ValidationError) as error:
            detail = "invalid JSON"
            if isinstance(error, ValidationError) and error.errors():
                validation_errors = error.errors()
                empty_collection_error = next(
                    (
                        item for item in validation_errors
                        if item.get("type") == "too_short"
                        and any(part in {"courses", "groups", "sections"} for part in item.get("loc", ()))
                    ),
                    None,
                )
                detail = (
                    "no lecture, quiz, or lab sections were found in the screenshot"
                    if empty_collection_error
                    else str(validation_errors[0].get("msg", "invalid course data"))
                )
            raise AIInvalidResponseError(
                f"Course recognition could not be validated: {detail}. "
                "Confirm the course code, use a clear crop that includes the section rows, "
                "or enter the sections manually."
            ) from error


def normalize_extracted_courses(
    raw: object,
    *,
    course_code_hint: str | None = None,
    course_title_hint: str | None = None,
) -> object:
    """Normalize safe, common vision-output variations before validation."""
    if not isinstance(raw, dict) or not isinstance(raw.get("courses"), list):
        return raw

    warnings = raw.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
        raw["warnings"] = warnings

    for course in raw["courses"]:
        if not isinstance(course, dict):
            continue
        if course_code_hint:
            course["code"] = course_code_hint.strip().upper()
        if course_title_hint:
            course["title"] = course_title_hint.strip() or None
        elif isinstance(course.get("title"), str):
            course["title"] = course["title"].strip() or None

        groups = course.get("groups")
        if not isinstance(groups, list):
            continue
        merged: OrderedDict[str, dict[str, object]] = OrderedDict()
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_type = str(group.get("type", "")).lower()
            sections = group.get("sections", [])
            if group_type not in {"lecture", "quiz", "lab"}:
                continue
            if group_type not in merged:
                merged[group_type] = {
                    "type": group_type,
                    "choose": 1,
                    "sections": [],
                }
            if isinstance(sections, list):
                merged[group_type]["sections"].extend(sections)  # type: ignore[union-attr]

        normalized_groups: list[dict[str, object]] = []
        for group in merged.values():
            valid_sections: list[dict[str, object]] = []
            for section in group.get("sections", []):  # type: ignore[union-attr]
                if not isinstance(section, dict):
                    continue
                section["id"] = str(section.get("id", "")).strip().upper()
                if not section["id"]:
                    warnings.append("Ignored an unreadable blank section row; verify that all visible sections were captured.")
                    continue
                section["status"] = str(section.get("status", "unknown")).lower()
                if section.get("sln") is not None:
                    section["sln"] = str(section["sln"]).strip() or None
                for optional_field in ("sln", "parentSectionId"):
                    if isinstance(section.get(optional_field), str):
                        section[optional_field] = section[optional_field].strip().upper() or None
                for meeting in section.get("meetings", []):
                    if not isinstance(meeting, dict):
                        continue
                    if meeting.get("location") == "":
                        meeting["location"] = None
                    for field in ("startTime", "endTime"):
                        meeting[field] = normalize_extracted_time(meeting.get(field))
                valid_sections.append(section)
            if valid_sections:
                group["sections"] = valid_sections
                normalized_groups.append(group)
        course["groups"] = normalized_groups
    return raw


def normalize_extracted_time(value: object) -> object:
    """Convert a common 12-hour OCR time to the canonical 24-hour format."""
    if not isinstance(value, str):
        return value
    match = re.fullmatch(
        r"\s*(\d{1,2}):(\d{2})\s*([AP])\.?M\.?\s*",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return value.strip()
    hour, minute, meridiem = match.groups()
    hour_value = int(hour) % 12
    if meridiem.upper() == "P":
        hour_value += 12
    return f"{hour_value:02d}:{minute}"
