# Frontend Workflow

The frontend provides one guided path from course availability to ranked schedule
options. Users do not need to call backend endpoints manually.

## Main Flow

1. Queue one or more course screenshots and manually extract their data, or
   enter section rows manually.
2. Add the course and review the course count and generated section groups.
3. Inspect or edit course metadata, section details, and linked lectures.
4. Enter schedule preferences in natural language.
5. Send the preferences to `POST /parse-preferences`.
6. Review the validated hard constraints, soft preferences, conflicts, and any
   clarification questions returned by the backend.
7. Confirm the interpretation or return to edit the preference text.
8. Send the confirmed request to `POST /api/schedules/generate`.
9. Review the ranked, conflict-free schedule candidates.
10. Switch between candidates and compare their weekly calendars, scores,
    reasons, trade-offs, and score breakdowns.

## Confirmation and Revision

The interpretation screen separates hard constraints from soft preferences and
shows clarification questions and hard conflicts without reducing them to a
generic warning. **Confirm and generate** is disabled while either condition is
unresolved. **Revise preferences** returns to the input screen with the original
`preferenceText` intact, so the user can edit it and run parsing again.

Explicit numeric gap requirements are displayed as hard constraints and sent to
the solver as `allowedGapMinutes` and `minimumLongGapMinutes`. Free-form
`hardConstraints` are explanatory only; executable rules must have a structured
field so the UI never claims that an unenforced rule has been applied.

## Application States

The UI provides feedback for initial input, preference parsing, schedule
generation, successful results, course-form errors, FastAPI validation errors, AI
parsing failures, backend unavailability, and empty schedule results. An empty
result renders every backend diagnostic and a route back to edit the input.

No-result diagnostics distinguish an empty declared group, open-only section
exhaustion, overlapping fixed sections, hard time/day filters, and conflicts
among all remaining combinations.

## Course Input Rules

The per-course screenshot importer accepts multiple clipboard-pasted or uploaded
PNG, JPEG, and WebP images up to 10 MB each. Adding an image only queues its
preview; recognition starts only after the user selects **Extract sections**.
Each image is sent to `POST /api/courses/extract-from-image`, and the validated
results are merged into the current editable course draft. Every screenshot
must contain exactly one course and all screenshots must represent the same
course. After **Add course**, the source screenshots are discarded and only the
validated course data remains. AI output cannot bypass the backend `Course`
validation rules. Users should verify recognized section status, times,
locations, and linked lectures before continuing.

The course builder accepts a course code and repeatable section rows. Each row
contains a component type, section ID, weekday codes, start time, and end time.
Time controls use a 12-hour AM/PM format and convert to the API's `HH:MM` format
before validation and submission.
All entered sections are treated as available (`open`). The frontend groups rows
by component type and sends the resulting schema to the backend; users never
need to write JSON.

- A lecture-only course is valid.
- Quiz and lab groups are created only when the user adds those row types.
- The frontend never invents a missing component.
- Section IDs must be unique within a course and use uppercase letters or
  numbers beginning with a letter.
- Weekdays use `M`, `T`, `W`, `Th`, and `F`; compact values such as `MWF` work.
- Start time must be earlier than end time.
- Invalid rows are shown as form errors before an API request is made.

## Course Review and Editing

Every added course renders a detailed view grouped by lecture, quiz, and lab.
It shows course code and title plus each section's ID, status, SLN, meeting days,
time, location, and linked lecture. For example, quiz `AA` displays “Linked to
Lecture A.”

The edit action supports course code, title, section ID/type/status, SLN, days,
start/end time, location, and `parentSectionId`. Saving rebuilds the same course
schema used for new input and reruns validation. Invalid weekdays, time ranges,
duplicate IDs, duplicate course codes, and nonexistent parent lectures remain
visible in edit mode and are not saved. A successful save invalidates previously
parsed preferences and generated schedules so the next result uses current data.

Lecture `A` only pairs with an `A`-prefixed quiz/lab (`AA`, `AB`, `AC`, etc.) or
one explicitly configured with `parentSectionId: "A"`. The system never combines
Lecture `A` with a `B`-linked section such as `BA`, `BB`, or `BC`.

The backend still supports and validates empty declared groups when requests are
sent directly through the API. The Pydantic models remain the authority for
complete schema validation.

## Preference Input

The preference editor accepts natural-language English and Chinese text. A
nonblank value is sent to `POST /parse-preferences` with the parsed courses. If
the field is blank, the frontend skips the AI call and presents explicit safe
defaults for confirmation: open sections only, with no additional hard or soft
preferences. This keeps the workflow usable without inventing user intent.
