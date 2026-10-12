from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product

from ..models import (
    Course,
    ScheduleRequest,
    Section,
    SectionGroup,
    SectionStatus,
    SectionType,
)
from .time_utils import DayCode, meetings_overlap, time_to_minutes


@dataclass(frozen=True, slots=True)
class SectionChoice:
    group_type: SectionType
    section: Section


@dataclass(frozen=True, slots=True)
class CourseCombination:
    course_code: str
    selections: tuple[SectionChoice, ...]


@dataclass(frozen=True, slots=True)
class ScheduleCandidate:
    courses: tuple[CourseCombination, ...]


def generate_group_combinations(
    group: SectionGroup,
    *,
    require_open_sections: bool = False,
) -> tuple[tuple[Section, ...], ...]:
    """Return one eligible section choice for a required group."""
    return tuple(
        (section,)
        for section in group.sections
        if not require_open_sections or section.status is SectionStatus.OPEN
    )


def _dependencies_are_satisfied(selections: tuple[SectionChoice, ...]) -> bool:
    selected_ids = {choice.section.id for choice in selections}
    return all(
        set(choice.section.required_section_ids).issubset(selected_ids)
        for choice in selections
    )


def _linked_sections_are_satisfied(
    selections: tuple[SectionChoice, ...],
) -> bool:
    lecture_ids = {
        choice.section.id
        for choice in selections
        if choice.group_type is SectionType.LECTURE
    }
    return all(
        choice.section.parent_section_id in lecture_ids
        for choice in selections
        if choice.group_type in {SectionType.QUIZ, SectionType.LAB}
    )


def generate_course_combinations(
    course: Course,
    *,
    require_open_sections: bool = True,
    fixed_section_ids: set[str] | None = None,
) -> tuple[CourseCombination, ...]:
    """Generate valid combinations containing one section from every group."""
    fixed_ids = fixed_section_ids or set()
    eligible_sections = {
        group.type: tuple(
            section
            for section in group.sections
            if not require_open_sections or section.status is SectionStatus.OPEN
        )
        for group in course.groups
    }
    lecture_sections = eligible_sections.get(SectionType.LECTURE)
    lecture_choices: tuple[Section | None, ...] = (
        tuple(lecture_sections) if lecture_sections is not None else (None,)
    )
    candidates: list[CourseCombination] = []

    for lecture in lecture_choices:
        group_combinations: list[tuple[tuple[Section, ...], ...]] = []
        for group in course.groups:
            sections = eligible_sections[group.type]
            if group.type is SectionType.LECTURE:
                sections = (lecture,) if lecture is not None else ()
            elif group.type in {SectionType.QUIZ, SectionType.LAB}:
                sections = tuple(
                    section
                    for section in sections
                    if section.parent_section_id == lecture.id
                ) if lecture is not None else ()
            group_combinations.append(tuple((section,) for section in sections))

        for group_selection in product(*group_combinations):
            choices = tuple(
                SectionChoice(group.type, section)
                for group, selected_sections in zip(
                    course.groups,
                    group_selection,
                    strict=True,
                )
                for section in selected_sections
            )
            candidate = CourseCombination(course_code=course.code, selections=choices)
            if not course_combination_satisfies_hard_constraints(
                candidate,
                course,
                require_open_sections=require_open_sections,
                fixed_section_ids=fixed_ids,
            ):
                continue

            candidates.append(candidate)

    return tuple(candidates)


def sections_overlap(left: Section, right: Section) -> bool:
    return any(
        meetings_overlap(left_meeting, right_meeting)
        for left_meeting in left.meetings
        for right_meeting in right.meetings
    )


def course_combination_has_conflict(candidate: CourseCombination) -> bool:
    return any(
        sections_overlap(left.section, right.section)
        for left, right in combinations(candidate.selections, 2)
    )


def schedule_has_conflict(candidate: ScheduleCandidate) -> bool:
    selections = tuple(
        selection
        for course_combination in candidate.courses
        for selection in course_combination.selections
    )
    return any(
        sections_overlap(left.section, right.section)
        for left, right in combinations(selections, 2)
    )


def course_combination_satisfies_hard_constraints(
    candidate: CourseCombination,
    course: Course,
    *,
    require_open_sections: bool,
    fixed_section_ids: set[str],
) -> bool:
    """Validate one course selection against every course-level hard rule."""
    if candidate.course_code != course.code:
        return False
    if len(candidate.selections) != len(course.groups):
        return False

    for group, selection in zip(course.groups, candidate.selections, strict=True):
        sections_by_id = {section.id: section for section in group.sections}
        if selection.group_type is not group.type:
            return False
        if sections_by_id.get(selection.section.id) != selection.section:
            return False
        if (
            require_open_sections
            and selection.section.status is not SectionStatus.OPEN
        ):
            return False

    selected_ids = {choice.section.id for choice in candidate.selections}
    return (
        fixed_section_ids.issubset(selected_ids)
        and _dependencies_are_satisfied(candidate.selections)
        and _linked_sections_are_satisfied(candidate.selections)
        and not course_combination_has_conflict(candidate)
    )


def schedule_satisfies_hard_constraints(
    candidate: ScheduleCandidate,
    request: ScheduleRequest,
) -> bool:
    """Validate course coverage and every hard rule before returning a schedule."""
    if len(candidate.courses) != len(request.courses):
        return False

    if not all(
        course_combination_satisfies_hard_constraints(
            course_combination,
            course,
            require_open_sections=request.preferences.require_open_sections,
            fixed_section_ids=set(
                request.preferences.fixed_sections.get(course.code, [])
            ),
        )
        for course, course_combination in zip(
            request.courses,
            candidate.courses,
            strict=True,
        )
    ):
        return False

    required_days_off = set(request.preferences.required_days_off)
    meetings_by_day: dict[DayCode, list[tuple[int, int]]] = {}
    for course_combination in candidate.courses:
        for selection in course_combination.selections:
            for meeting in selection.section.meetings:
                for day in meeting.days:
                    meetings_by_day.setdefault(day, []).append(
                        (time_to_minutes(meeting.start_time), time_to_minutes(meeting.end_time))
                    )
                if required_days_off.intersection(meeting.days):
                    return False
                if (
                    request.preferences.earliest_start is not None
                    and not request.preferences.allow_earlier_if_only_option
                    and meeting.start_time < request.preferences.earliest_start
                ):
                    return False

    allowed_gap = request.preferences.allowed_gap_minutes
    minimum_long_gap = request.preferences.minimum_long_gap_minutes
    if allowed_gap is not None:
        for daily_meetings in meetings_by_day.values():
            ordered = sorted(daily_meetings)
            for before, after in zip(ordered, ordered[1:]):
                gap = after[0] - before[1]
                if gap <= allowed_gap:
                    continue
                if minimum_long_gap is not None and gap >= minimum_long_gap:
                    continue
                return False

    return not schedule_has_conflict(candidate)


def generate_schedule_candidates(request: ScheduleRequest) -> tuple[ScheduleCandidate, ...]:
    """Generate all conflict-free multi-course schedules for a validated request."""
    course_candidates = [
        generate_course_combinations(
            course,
            require_open_sections=request.preferences.require_open_sections,
            fixed_section_ids=set(request.preferences.fixed_sections.get(course.code, [])),
        )
        for course in request.courses
    ]

    schedules: list[ScheduleCandidate] = []
    for course_selection in product(*course_candidates):
        candidate = ScheduleCandidate(courses=tuple(course_selection))
        if schedule_satisfies_hard_constraints(candidate, request):
            schedules.append(candidate)

    return tuple(schedules)


def diagnose_no_schedules(request: ScheduleRequest) -> tuple[str, ...]:
    """Return concrete hard-constraint reasons for an empty solver result."""
    warnings: list[str] = []
    for course in request.courses:
        for group in course.groups:
            if not group.sections:
                warnings.append(
                    f"{course.code} {group.type.value} group has no sections."
                )
            elif request.preferences.require_open_sections and not any(
                section.status is SectionStatus.OPEN for section in group.sections
            ):
                warnings.append(
                    f"{course.code} {group.type.value} group has no open sections "
                    "while open-only is enabled."
                )

    sections_by_course = {
        course.code: {
            section.id: section
            for group in course.groups
            for section in group.sections
        }
        for course in request.courses
    }
    fixed = [
        (course_code, section_id, sections_by_course[course_code][section_id])
        for course_code, section_ids in request.preferences.fixed_sections.items()
        for section_id in section_ids
    ]
    for left, right in combinations(fixed, 2):
        if sections_overlap(left[2], right[2]):
            warnings.append(
                f"Fixed sections {left[0]} {left[1]} and {right[0]} {right[1]} "
                "have overlapping meeting times."
            )

    if not warnings:
        if request.preferences.allowed_gap_minutes is not None:
            warnings.append(
                "Hard gap constraints eliminate the remaining combinations."
            )
        elif (
            request.preferences.required_days_off
            or (
                request.preferences.earliest_start is not None
                and not request.preferences.allow_earlier_if_only_option
            )
        ):
            warnings.append(
                "Hard day-off or earliest-start constraints eliminate the "
                "remaining combinations."
            )
        warnings.append(
            "All remaining combinations have meeting conflicts or incompatible "
            "course-component requirements."
        )
    return tuple(dict.fromkeys(warnings))
