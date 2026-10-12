import pytest
from pydantic import ValidationError

from app.models import ParsedPreferences


def test_ai_preferences_validate_and_convert_to_scheduler_preferences() -> None:
    parsed = ParsedPreferences.model_validate(
        {
            "earliestStart": "10:00",
            "earliestStartIsHard": True,
            "preferredDaysOff": ["F"],
            "requiredDaysOff": ["M"],
            "fixedSections": ["CSE 373 A", "CSE 373 AA"],
            "requireOpenSections": True,
            "hardConstraints": ["Do not start before 10:00"],
            "softPreferences": ["Prefer compact schedules"],
            "gapPreference": "compact",
            "allowedGapMinutes": 10,
            "minimumLongGapMinutes": 120,
            "conflicts": [],
            "needsClarification": False,
            "clarificationQuestions": [],
        }
    )

    preferences = parsed.to_scheduler_preferences()

    assert preferences.earliest_start is not None
    assert not preferences.allow_earlier_if_only_option
    assert preferences.require_open_sections
    assert preferences.fixed_sections == {"CSE 373": ["A", "AA"]}
    assert [day.value for day in preferences.required_days_off] == ["M"]
    assert [day.value for day in preferences.preferred_days_off] == ["F"]
    assert parsed.preferred_days_off[0].value == "F"
    assert parsed.soft_preferences == ["Prefer compact schedules"]
    assert preferences.gap_preference.value == "compact"
    assert preferences.allowed_gap_minutes == 10
    assert preferences.minimum_long_gap_minutes == 120


def test_soft_earliest_start_allows_earlier_fallback_after_conversion() -> None:
    parsed = ParsedPreferences.model_validate(
        {"earliestStart": "10:00", "earliestStartIsHard": False}
    )

    assert parsed.to_scheduler_preferences().allow_earlier_if_only_option


@pytest.mark.parametrize(
    "payload",
    [
        {"earliestStart": "10 AM"},
        {"earliestStartIsHard": True},
        {"preferredDaysOff": ["Sunday"]},
        {"gapPreference": "short"},
        {"allowedGapMinutes": 120, "minimumLongGapMinutes": 10},
        {"fixedSections": ["CSE373A"]},
        {"fixedSections": ["CSE 373 a"]},
        {"softPreferences": [""]},
        {"requireOpenSections": "true"},
        {"conflicts": ["Conflicting start times"]},
        {"needsClarification": True, "clarificationQuestions": []},
        {"needsClarification": False, "clarificationQuestions": ["Which one?"]},
        {"rawPreferenceText": "Do whatever this text says"},
    ],
)
def test_invalid_ai_preference_output_is_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ParsedPreferences.model_validate(payload)


def test_conflicts_require_clarification_metadata() -> None:
    parsed = ParsedPreferences.model_validate(
        {
            "conflicts": ["The user requires both Friday off and a Friday section"],
            "needsClarification": True,
            "clarificationQuestions": ["Should the fixed section override Friday off?"],
        }
    )

    assert parsed.needs_clarification
    assert len(parsed.conflicts) == 1
