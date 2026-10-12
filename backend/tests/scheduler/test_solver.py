import pytest
from pydantic import ValidationError

from app.models import Course, Preferences, ScheduleRequest, SectionGroup
from app.scheduler.explanations import explain_schedule
from app.scheduler.scoring import score_schedule
from app.scheduler.solver import (
    CourseCombination,
    ScheduleCandidate,
    diagnose_no_schedules,
    generate_course_combinations,
    generate_group_combinations,
    generate_schedule_candidates,
    schedule_satisfies_hard_constraints,
)


def section(
    section_id: str,
    *,
    day: str = "M",
    start: str = "09:30",
    end: str = "10:20",
    status: str = "open",
    required_section_ids: list[str] | None = None,
    parent_section_id: str | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "id": section_id,
        "status": status,
        "meetings": [{"days": [day], "startTime": start, "endTime": end}],
        "requiredSectionIds": required_section_ids or [],
    }
    if parent_section_id is not None:
        value["parentSectionId"] = parent_section_id
    return value


def section_without_meetings(
    section_id: str,
    *,
    status: str = "open",
    sln: str | None = None,
) -> dict[str, object]:
    return {"id": section_id, "status": status, "sln": sln, "meetings": []}


def schedule_signature(
    candidate: ScheduleCandidate,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (
            course.course_code,
            tuple(choice.section.id for choice in course.selections),
        )
        for course in candidate.courses
    )


def test_group_combinations_select_one_section() -> None:
    group = SectionGroup.model_validate(
        {
            "type": "lab",
            "sections": [
                section_without_meetings("AA"),
                section_without_meetings("AB"),
                section_without_meetings("AC"),
            ],
        }
    )

    choices = generate_group_combinations(group)

    assert len(choices) == 3
    assert all(len(choice) == 1 for choice in choices)


@pytest.mark.parametrize(
    ("groups", "expected_count"),
    [
        ([("lecture", ["A", "B"])], 2),
        ([("lecture", ["A", "B"]), ("lab", ["AL", "BL"])], 2),
        ([("lecture", ["A", "B"]), ("quiz", ["AA", "AB", "BA"])], 3),
        (
            [
                ("lecture", ["A", "B"]),
                ("quiz", ["AA", "AB", "BA"]),
                ("lab", ["AL", "BL"]),
            ],
            3,
        ),
        (
            [
                ("lecture", ["A", "B"]),
                ("quiz", ["AA", "AB", "AC", "BA", "BB", "BC"]),
                ("lab", ["AL", "BL"]),
            ],
            6,
        ),
    ],
)
def test_course_combinations_follow_only_declared_groups(
    groups: list[tuple[str, list[str]]], expected_count: int
) -> None:
    course = Course.model_validate(
        {
            "code": "TEST 101",
            "groups": [
                {
                    "type": group_type,
                    "sections": [
                        section_without_meetings(section_id)
                        for section_id in section_ids
                    ],
                }
                for group_type, section_ids in groups
            ],
        }
    )

    choices = generate_course_combinations(course)

    assert len(choices) == expected_count
    assert all(choice.course_code == "TEST 101" for choice in choices)
    assert all(len(choice.selections) == len(groups) for choice in choices)
    assert all(
        len({selected.group_type for selected in choice.selections}) == len(groups)
        for choice in choices
    )


def test_lecture_sections_only_pair_with_their_linked_quizzes() -> None:
    course = Course.model_validate(
        {
            "code": "CSE 312",
            "groups": [
                {
                    "type": "lecture",
                    "sections": [
                        section_without_meetings("A"),
                        section_without_meetings("B"),
                    ],
                },
                {
                    "type": "quiz",
                    "sections": [
                        section_without_meetings(section_id)
                        for section_id in ("AA", "AB", "AC", "BA", "BB", "BC")
                    ],
                },
            ],
        }
    )

    combinations = generate_course_combinations(course)
    selected_ids = [
        tuple(choice.section.id for choice in combination.selections)
        for combination in combinations
    ]

    assert selected_ids == [
        ("A", "AA"),
        ("A", "AB"),
        ("A", "AC"),
        ("B", "BA"),
        ("B", "BB"),
        ("B", "BC"),
    ]
    assert ("A", "BA") not in selected_ids


def test_lecture_quiz_and_lab_all_follow_parent_binding() -> None:
    course = Course.model_validate(
        {
            "code": "CHEM 142",
            "groups": [
                {
                    "type": "lecture",
                    "sections": [
                        section_without_meetings("A"),
                        section_without_meetings("B"),
                    ],
                },
                {
                    "type": "quiz",
                    "sections": [
                        section_without_meetings("AA"),
                        section_without_meetings("BA"),
                    ],
                },
                {
                    "type": "lab",
                    "sections": [
                        section_without_meetings("AL"),
                        section_without_meetings("BL"),
                    ],
                },
            ],
        }
    )

    combinations = generate_course_combinations(course)

    assert [
        tuple(choice.section.id for choice in combination.selections)
        for combination in combinations
    ] == [("A", "AA", "AL"), ("B", "BA", "BL")]


def test_explicit_parent_section_id_overrides_prefix_inference() -> None:
    course = Course.model_validate(
        {
            "code": "CHEM 142",
            "groups": [
                {
                    "type": "lecture",
                    "sections": [section_without_meetings("A")],
                },
                {
                    "type": "lab",
                    "sections": [
                        {
                            **section_without_meetings("BL"),
                            "parentSectionId": "A",
                        }
                    ],
                },
            ],
        }
    )

    assert course.groups[1].sections[0].parent_section_id == "A"
    assert len(generate_course_combinations(course)) == 1


def test_incompatible_fixed_lecture_and_quiz_produce_no_result() -> None:
    request = ScheduleRequest.model_validate(
        {
            "courses": [
                {
                    "code": "CSE 312",
                    "groups": [
                        {
                            "type": "lecture",
                            "sections": [
                                section_without_meetings("A"),
                                section_without_meetings("B"),
                            ],
                        },
                        {
                            "type": "quiz",
                            "sections": [
                                section_without_meetings("AA"),
                                section_without_meetings("BA"),
                            ],
                        },
                    ],
                }
            ],
            "preferences": {"fixedSections": {"CSE 312": ["A", "BA"]}},
        }
    )

    assert generate_schedule_candidates(request) == ()


def test_course_combination_preserves_section_metadata() -> None:
    course = Course.model_validate(
        {
            "code": "CSE 373",
            "groups": [
                {
                    "type": "lecture",
                    "sections": [
                        {
                            "id": "A",
                            "status": "closed",
                            "sln": "12345",
                            "meetings": [
                                {
                                    "days": ["M", "W", "F"],
                                    "startTime": "09:30",
                                    "endTime": "10:20",
                                    "location": "KNE 120",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )

    combinations = generate_course_combinations(
        course,
        require_open_sections=False,
    )
    choice = combinations[0].selections[0]

    assert choice.group_type.value == "lecture"
    assert choice.section.id == "A"
    assert choice.section.status.value == "closed"
    assert choice.section.sln == "12345"
    assert choice.section.meetings[0].location == "KNE 120"


def test_empty_declared_group_produces_no_course_combinations() -> None:
    course = Course.model_validate(
        {
            "code": "CHEM 142",
            "groups": [
                {
                    "type": "lecture",
                    "sections": [section_without_meetings("A")],
                },
                {"type": "lab", "sections": []},
            ],
        }
    )

    assert generate_course_combinations(course) == ()


def test_course_with_empty_group_produces_no_final_schedules() -> None:
    request = ScheduleRequest.model_validate(
        {
            "courses": [
                {
                    "code": "CSE 373",
                    "groups": [
                        {
                            "type": "lecture",
                            "sections": [section_without_meetings("A")],
                        }
                    ],
                },
                {
                    "code": "CHEM 142",
                    "groups": [
                        {
                            "type": "lecture",
                            "sections": [section_without_meetings("A")],
                        },
                        {"type": "lab", "sections": []},
                    ],
                },
            ]
        }
    )

    assert generate_schedule_candidates(request) == ()
    assert diagnose_no_schedules(request) == (
        "CHEM 142 lab group has no sections.",
    )


def test_diagnostics_report_open_only_exhaustion() -> None:
    request = ScheduleRequest.model_validate(
        {
            "courses": [
                {
                    "code": "CSE 373",
                    "groups": [
                        {
                            "type": "lecture",
                            "sections": [section_without_meetings("A", status="closed")],
                        }
                    ],
                }
            ],
            "preferences": {"requireOpenSections": True},
        }
    )

    assert diagnose_no_schedules(request) == (
        "CSE 373 lecture group has no open sections while open-only is enabled.",
    )


def test_diagnostics_report_overlapping_fixed_sections() -> None:
    request = ScheduleRequest.model_validate(
        {
            "courses": [
                {"code": "CSE 373", "groups": [{"type": "lecture", "sections": [section("A")]}]},
                {"code": "CSE 414", "groups": [{"type": "lecture", "sections": [section("B")]}]},
            ],
            "preferences": {"fixedSections": {"CSE 373": ["A"], "CSE 414": ["B"]}},
        }
    )

    assert diagnose_no_schedules(request) == (
        "Fixed sections CSE 373 A and CSE 414 B have overlapping meeting times.",
    )


def test_course_combinations_filter_closed_and_keep_fixed_sections() -> None:
    course = Course.model_validate(
        {
            "code": "CSE 373",
            "groups": [
                {
                    "type": "lecture",
                    "choose": 1,
                    "sections": [
                        section("A"),
                        section("B", start="11:30", end="12:20"),
                        section(
                            "C",
                            start="12:30",
                            end="13:20",
                            status="closed",
                        ),
                    ],
                }
            ],
        }
    )

    choices = generate_course_combinations(course, fixed_section_ids={"B"})

    assert len(choices) == 1
    assert choices[0].selections[0].section.id == "B"


def test_course_combinations_enforce_section_dependencies() -> None:
    course = Course.model_validate(
        {
            "code": "CHEM 142",
            "groups": [
                {
                    "type": "lecture",
                    "choose": 1,
                    "sections": [
                        section("A"),
                        section("B", start="11:30", end="12:20"),
                    ],
                },
                {
                    "type": "lab",
                    "choose": 1,
                    "sections": [
                        section(
                            "AA",
                            day="T",
                            start="13:30",
                            end="15:20",
                            required_section_ids=["A"],
                        )
                    ],
                },
            ],
        }
    )

    choices = generate_course_combinations(course)

    assert len(choices) == 1
    assert {choice.section.id for choice in choices[0].selections} == {"A", "AA"}


def test_generate_schedules_filters_cross_course_conflicts() -> None:
    request = ScheduleRequest.model_validate(
        {
            "courses": [
                {
                    "code": "CSE 373",
                    "groups": [
                        {
                            "type": "lecture",
                            "choose": 1,
                            "sections": [section("A")],
                        }
                    ],
                },
                {
                    "code": "INFO 370",
                    "groups": [
                        {
                            "type": "lecture",
                            "choose": 1,
                            "sections": [
                                section("A", start="10:00", end="10:50"),
                                section("B", start="10:30", end="11:20"),
                            ],
                        }
                    ],
                },
            ],
            "preferences": {"requireOpenSections": True},
        }
    )

    schedules = generate_schedule_candidates(request)

    assert len(schedules) == 1
    assert schedule_signature(schedules[0]) == (
        ("CSE 373", ("A",)),
        ("INFO 370", ("B",)),
    )


def test_all_fixed_sections_are_present_in_every_schedule() -> None:
    request = ScheduleRequest.model_validate(
        {
            "courses": [
                {
                    "code": "CSE 123",
                    "groups": [
                        {
                            "type": "lecture",
                            "sections": [
                                section("A"),
                                section("B", start="11:30", end="12:20"),
                            ],
                        },
                        {
                            "type": "quiz",
                            "sections": [
                                section("AA", day="T"),
                                section("AB", day="T", start="11:30", end="12:20"),
                            ],
                        },
                    ],
                }
            ],
            "preferences": {
                "fixedSections": {"CSE 123": ["A", "AA"]},
            },
        }
    )

    schedules = generate_schedule_candidates(request)

    assert len(schedules) == 1
    assert schedule_signature(schedules[0]) == (("CSE 123", ("A", "AA")),)


def test_fixed_section_conflict_with_another_course_produces_no_schedule() -> None:
    request = ScheduleRequest.model_validate(
        {
            "courses": [
                {
                    "code": "CSE 123",
                    "groups": [
                        {
                            "type": "lecture",
                            "sections": [
                                section("A"),
                                section("B", start="11:30", end="12:20"),
                            ],
                        }
                    ],
                },
                {
                    "code": "INFO 200",
                    "groups": [
                        {
                            "type": "lecture",
                            "sections": [
                                section("A", start="10:00", end="10:50")
                            ],
                        }
                    ],
                },
            ],
            "preferences": {"fixedSections": {"CSE 123": ["A"]}},
        }
    )

    assert generate_schedule_candidates(request) == ()


@pytest.mark.parametrize(
    "preferences",
    [
        {"requiredDaysOff": ["M"]},
        {"earliestStart": "10:00", "allowEarlierIfOnlyOption": False},
    ],
)
def test_hard_time_preferences_filter_schedule_candidates(
    preferences: dict[str, object],
) -> None:
    request = ScheduleRequest.model_validate(
        {
            "courses": [
                {
                    "code": "CSE 373",
                    "groups": [
                        {
                            "type": "lecture",
                            "sections": [section("A", day="M", start="09:30")],
                        }
                    ],
                }
            ],
            "preferences": preferences,
        }
    )

    assert generate_schedule_candidates(request) == ()


def test_soft_earliest_start_does_not_filter_schedule_candidates() -> None:
    request = ScheduleRequest.model_validate(
        {
            "courses": [
                {
                    "code": "CSE 373",
                    "groups": [
                        {
                            "type": "lecture",
                            "sections": [section("A", start="09:30")],
                        }
                    ],
                }
            ],
            "preferences": {
                "earliestStart": "10:00",
                "allowEarlierIfOnlyOption": True,
            },
        }
    )

    assert len(generate_schedule_candidates(request)) == 1


@pytest.mark.parametrize(
    ("second_start", "expected_count"),
    [("10:10", 1), ("11:10", 0), ("12:00", 1)],
)
def test_hard_gap_rule_allows_only_short_or_long_gaps(
    second_start: str,
    expected_count: int,
) -> None:
    request = ScheduleRequest.model_validate(
        {
            "courses": [
                {
                    "code": "CSE 373",
                    "groups": [{"type": "lecture", "sections": [section("A", day="M", start="09:00", end="10:00")]}],
                },
                {
                    "code": "CSE 414",
                    "groups": [{"type": "lecture", "sections": [section("A", day="M", start=second_start, end="13:00")]}],
                },
            ],
            "preferences": {
                "allowedGapMinutes": 10,
                "minimumLongGapMinutes": 120,
            },
        }
    )

    assert len(generate_schedule_candidates(request)) == expected_count


def test_closed_fixed_section_cannot_bypass_open_only_validation() -> None:
    with pytest.raises(ValidationError, match="fixed section must be open"):
        ScheduleRequest.model_validate(
            {
                "courses": [
                    {
                        "code": "CSE 123",
                        "groups": [
                            {
                                "type": "lecture",
                                "sections": [
                                    section_without_meetings("A", status="closed")
                                ],
                            }
                        ],
                    }
                ],
                "preferences": {
                    "requireOpenSections": True,
                    "fixedSections": {"CSE 123": ["A"]},
                },
            }
        )


def test_open_only_filter_excludes_closed_sections() -> None:
    request = ScheduleRequest.model_validate(
        {
            "courses": [
                {
                    "code": "CSE 123",
                    "groups": [
                        {
                            "type": "lecture",
                            "sections": [
                                section_without_meetings("A"),
                                section_without_meetings("B", status="closed"),
                            ],
                        }
                    ],
                }
            ],
            "preferences": {"requireOpenSections": True},
        }
    )

    schedules = generate_schedule_candidates(request)

    assert tuple(schedule_signature(schedule) for schedule in schedules) == (
        (("CSE 123", ("A",)),),
    )


def test_closed_sections_are_candidates_when_open_only_is_disabled() -> None:
    request = ScheduleRequest.model_validate(
        {
            "courses": [
                {
                    "code": "CSE 123",
                    "groups": [
                        {
                            "type": "lecture",
                            "sections": [
                                section_without_meetings("A"),
                                section_without_meetings("B", status="closed"),
                            ],
                        }
                    ],
                }
            ],
            "preferences": {"requireOpenSections": False},
        }
    )

    schedules = generate_schedule_candidates(request)

    assert tuple(schedule_signature(schedule) for schedule in schedules) == (
        (("CSE 123", ("A",)),),
        (("CSE 123", ("B",)),),
    )


def test_group_with_only_closed_sections_produces_no_open_only_schedule() -> None:
    request = ScheduleRequest.model_validate(
        {
            "courses": [
                {
                    "code": "CHEM 142",
                    "groups": [
                        {
                            "type": "lecture",
                            "sections": [section_without_meetings("A")],
                        },
                        {
                            "type": "lab",
                            "sections": [
                                section_without_meetings("AL", status="closed")
                            ],
                        },
                    ],
                }
            ],
            "preferences": {"requireOpenSections": True},
        }
    )

    assert generate_schedule_candidates(request) == ()


def test_every_generated_schedule_passes_the_unified_hard_constraint_gate() -> None:
    request = ScheduleRequest.model_validate(
        {
            "courses": [
                {
                    "code": "CSE 123",
                    "groups": [
                        {
                            "type": "lecture",
                            "sections": [
                                section("A"),
                                section("B", status="closed"),
                            ],
                        },
                        {
                            "type": "quiz",
                            "sections": [section("AA", day="T")],
                        },
                    ],
                },
                {
                    "code": "INFO 200",
                    "groups": [
                        {
                            "type": "lecture",
                            "sections": [
                                section("A", start="10:30", end="11:20")
                            ],
                        }
                    ],
                },
            ],
            "preferences": {
                "requireOpenSections": True,
                "fixedSections": {"CSE 123": ["A", "AA"]},
            },
        }
    )

    schedules = generate_schedule_candidates(request)

    assert len(schedules) == 1
    assert all(
        schedule_satisfies_hard_constraints(candidate, request)
        for candidate in schedules
    )


def test_unified_hard_constraint_gate_rejects_missing_course_or_group() -> None:
    request = ScheduleRequest.model_validate(
        {
            "courses": [
                {
                    "code": "CSE 123",
                    "groups": [
                        {
                            "type": "lecture",
                            "sections": [section_without_meetings("A")],
                        },
                        {
                            "type": "quiz",
                            "sections": [section_without_meetings("AA")],
                        },
                    ],
                }
            ]
        }
    )
    valid = generate_schedule_candidates(request)[0]
    incomplete_course = CourseCombination(
        course_code=valid.courses[0].course_code,
        selections=valid.courses[0].selections[:1],
    )

    assert not schedule_satisfies_hard_constraints(
        ScheduleCandidate(courses=()),
        request,
    )
    assert not schedule_satisfies_hard_constraints(
        ScheduleCandidate(courses=(incomplete_course,)),
        request,
    )


def test_multi_course_cartesian_product_is_complete_and_stable() -> None:
    request = ScheduleRequest.model_validate(
        {
            "courses": [
                {
                    "code": course_code,
                    "groups": [
                        {
                            "type": "lecture",
                            "sections": [
                                section_without_meetings(section_id)
                                for section_id in section_ids
                            ],
                        }
                    ],
                }
                for course_code, section_ids in [
                    ("COURSE A", ["A1", "A2"]),
                    ("COURSE B", ["B1", "B2", "B3"]),
                    ("COURSE C", ["C1", "C2", "C3", "C4"]),
                ]
            ]
        }
    )

    first_run = generate_schedule_candidates(request)
    second_run = generate_schedule_candidates(request)
    signatures = tuple(schedule_signature(candidate) for candidate in first_run)

    assert len(first_run) == 24
    assert first_run == second_run
    assert all(len(candidate.courses) == 3 for candidate in first_run)
    assert signatures[0] == (
        ("COURSE A", ("A1",)),
        ("COURSE B", ("B1",)),
        ("COURSE C", ("C1",)),
    )
    assert signatures[-1] == (
        ("COURSE A", ("A2",)),
        ("COURSE B", ("B3",)),
        ("COURSE C", ("C4",)),
    )


def test_scoring_and_explanation_extension_points_are_callable() -> None:
    preferences = Preferences()
    candidate = ScheduleCandidate(courses=())

    assert score_schedule(candidate, preferences) == 100.0
    assert explain_schedule(candidate, preferences) == ("No time conflicts",)
