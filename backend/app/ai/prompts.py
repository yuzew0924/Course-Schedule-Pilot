from __future__ import annotations

from typing import Any


PREFERENCE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "earliestStart": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "earliestStartIsHard": {"type": "boolean"},
        "preferredDaysOff": {
            "type": "array",
            "items": {"type": "string", "enum": ["M", "T", "W", "Th", "F"]},
        },
        "requiredDaysOff": {
            "type": "array",
            "items": {"type": "string", "enum": ["M", "T", "W", "Th", "F"]},
        },
        "preferredTimeOfDay": {
            "type": "string",
            "enum": ["morning", "afternoon", "evening", "none"],
        },
        "gapPreference": {
            "type": "string",
            "enum": ["compact", "balanced", "breaks", "none"],
        },
        "allowedGapMinutes": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]},
        "minimumLongGapMinutes": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]},
        "fixedSections": {"type": "array", "items": {"type": "string"}},
        "requireOpenSections": {"type": "boolean"},
        "hardConstraints": {"type": "array", "items": {"type": "string"}},
        "softPreferences": {"type": "array", "items": {"type": "string"}},
        "conflicts": {"type": "array", "items": {"type": "string"}},
        "needsClarification": {"type": "boolean"},
        "clarificationQuestions": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
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
    ],
}


PREFERENCE_PARSER_INSTRUCTIONS = """You convert preferenceText into schedule preference JSON.

Output rules:
- Return exactly one JSON object and nothing else.
- Do not return Markdown, code fences, comments, or natural-language explanation.
- Return every schema field. Do not add fields.
- Use null, false, true, or [] defaults when the user did not specify a value.

Field rules:
- earliestStart: null or a 24-hour HH:MM time such as 09:30.
- earliestStartIsHard: true only when the user clearly says the start limit is mandatory.
- preferredDaysOff: use only M, T, W, Th, or F.
- requiredDaysOff: use only M, T, W, Th, or F, and only for an explicit mandatory day-off requirement.
- preferredTimeOfDay: morning, afternoon, evening, or none.
- gapPreference: compact, balanced, breaks, or none. Use none unless the user expresses a gap preference.
- allowedGapMinutes and minimumLongGapMinutes represent an explicit hard gap
  rule. For example, 'gaps must be 10 minutes or at least 2 hours' becomes
  allowedGapMinutes: 10 and minimumLongGapMinutes: 120. Leave both null for
  soft wording such as 'prefer short gaps'. Never infer numeric values.
- fixedSections: use only '<courseCode> <sectionId>' values present in the supplied courses catalog.
- requireOpenSections: true unless the user explicitly permits closed sections.
- hardConstraints: only clear mandatory requirements not already captured by a structured field.
- softPreferences: ambiguous, approximate, or preference language such as 'prefer', 'ideally', or 'try to'.
- conflicts: describe mutually incompatible or contradictory user requirements.
- needsClarification: true when conflicts exist or a necessary meaning cannot be determined safely.
- clarificationQuestions: focused questions needed to resolve those conflicts or uncertainties.

Grounding rules:
- Use only course codes, section IDs, types, statuses, days, and times present in the courses catalog.
- Never invent or normalize an unknown course, section, weekday, or time.
- If a fixed course or section cannot be matched exactly, do not add it to fixedSections; set needsClarification to true and ask a clarification question.
- If wording is vague, preserve it in softPreferences instead of creating a hard constraint.
- If requirements contradict each other, record the contradiction in conflicts, set needsClarification to true, and add at least one clarification question.

Ambiguity examples:
- 'Not too early' is softPreferences only. Keep earliestStart null because no exact time was given.
- 'Prefer Friday off' adds F to preferredDaysOff and remains a soft preference.
- 'Friday must be free' adds F to requiredDaysOff.
- 'Keep classes close together' sets gapPreference to compact.
- 'I want moderate gaps' sets gapPreference to balanced.
- 'I want breaks between classes' sets gapPreference to breaks.
- 'I want an easier schedule' and 'Prefer afternoons free' belong in softPreferences without setting gapPreference.
- 'Classes must not start before 10:00' sets earliestStart to 10:00 and earliestStartIsHard to true.
- 'Do not start before 10:00' sets earliestStart to 10:00 and earliestStartIsHard to true.
- If a mandatory request is too ambiguous to represent safely, do not invent a value; set needsClarification to true and ask one focused question.
"""


COURSE_IMAGE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "courses": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "code": {"type": "string"},
                    "title": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "groups": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "type": {"type": "string", "enum": ["lecture", "quiz", "lab"]},
                                "choose": {"type": "integer", "const": 1},
                                "sections": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "id": {"type": "string"},
                                            "status": {"type": "string", "enum": ["open", "closed", "unknown"]},
                                            "sln": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                                            "parentSectionId": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                                            "requiredSectionIds": {"type": "array", "items": {"type": "string"}},
                                            "meetings": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "additionalProperties": False,
                                                    "properties": {
                                                        "days": {"type": "array", "items": {"type": "string", "enum": ["M", "T", "W", "Th", "F"]}},
                                                        "startTime": {"type": "string"},
                                                        "endTime": {"type": "string"},
                                                        "location": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                                                    },
                                                    "required": ["days", "startTime", "endTime", "location"],
                                                },
                                            },
                                        },
                                        "required": ["id", "status", "sln", "meetings", "parentSectionId", "requiredSectionIds"],
                                    },
                                },
                            },
                            "required": ["type", "choose", "sections"],
                        },
                    },
                },
                "required": ["code", "title", "groups"],
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["courses", "warnings"],
}


COURSE_IMAGE_PARSER_INSTRUCTIONS = """You extract course meeting data from a registration or time-schedule screenshot.

Return exactly one JSON object matching the supplied schema. Return no Markdown or explanation.

Extraction rules:
- Extract only information visibly supported by the image. Never invent a course, section, day, time, location, SLN, or availability state.
- Use 24-hour HH:MM times and only weekday codes M, T, W, Th, and F.
- Group sections by lecture, quiz, or lab. Each group uses choose: 1.
- Return exactly one group for each visible component type. Put lecture A, B, C,
  and all other lecture rows together in one lecture group's sections array;
  never create a separate lecture group for each row. Apply the same rule to
  quiz and lab rows.
- Read schedule tables row by row. Do not omit a visible section. For each row,
  take days, start/end time, location, SLN, and status from that same row.
- The user may provide a course code or title hint in the text accompanying the
  image. Use that exact hint instead of guessing from a cropped screenshot.
- Normalize course codes to forms such as CSE 414 and section IDs to uppercase.
- Use status unknown when availability is not clearly visible.
- Use null for title, SLN, location, or parentSectionId when it is not visible or cannot be inferred safely.
- A quiz or lab parentSectionId must identify its compatible lecture. A section such as AA normally belongs to lecture A and BA normally belongs to lecture B, but only use that convention when the screenshot supports those section labels.
- Lecture sections always use null parentSectionId.
- requiredSectionIds must be an empty array unless an explicit dependency is shown.
- Put uncertainty, omitted illegible rows, or cropped information in warnings.
- If no complete course and section can be read, do not fabricate one.
"""
