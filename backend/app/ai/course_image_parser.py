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
                detail = str(error.errors()[0].get("msg", "invalid course data"))
            raise AIInvalidResponseError(
                f"Course recognition could not be validated: {detail}. "
                "Try a tighter crop or correct the course manually."
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

    for course in raw["courses"]:
        if not isinstance(course, dict):
            continue
        if course_code_hint:
            course["code"] = course_code_hint.strip().upper()
        if course_title_hint:
            course["title"] = course_title_hint.strip()
        elif course.get("title") == "":
            course["title"] = None

        groups = course.get("groups")
        if not isinstance(groups, list):
            continue
        merged: OrderedDict[str, dict[str, object]] = OrderedDict()
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_type = str(group.get("type", "")).lower()
            sections = group.get("sections", [])
            if group_type not in merged:
                merged[group_type] = {
                    "type": group_type,
                    "choose": 1,
                    "sections": [],
                }
            if isinstance(sections, list):
                merged[group_type]["sections"].extend(sections)  # type: ignore[union-attr]

        course["groups"] = list(merged.values())
        for group in course["groups"]:
            for section in group.get("sections", []):
                if not isinstance(section, dict):
                    continue
                section["id"] = str(section.get("id", "")).strip().upper()
                section["status"] = str(section.get("status", "unknown")).lower()
                if section.get("sln") is not None:
                    section["sln"] = str(section["sln"])
                for optional_field in ("sln", "parentSectionId"):
                    if section.get(optional_field) == "":
                        section[optional_field] = None
                for meeting in section.get("meetings", []):
                    if not isinstance(meeting, dict):
                        continue
                    if meeting.get("location") == "":
                        meeting["location"] = None
                    for field in ("startTime", "endTime"):
                        meeting[field] = normalize_extracted_time(meeting.get(field))
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
