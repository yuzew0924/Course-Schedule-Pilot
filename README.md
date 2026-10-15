# Course Schedule Pilot

Course Schedule Pilot is a course schedule planning assistant that helps students compare possible class schedules before registration. Users can enter courses, available lecture and quiz sections, fixed choices, and scheduling preferences. The app then generates ranked schedule options and displays each one as a weekly calendar.

## Description

Planning a course schedule is often messy because every course may have several lectures, quiz sections, labs, availability states, and registration constraints. Course Schedule Pilot is designed to turn that information into clear options.

The project focuses on three core problems:

- Finding conflict-free combinations across multiple courses.
- Ranking schedules based on personal preferences.
- Showing each result visually so the user can quickly judge whether the schedule feels too tight, too spread out, or acceptable.

The planned architecture uses a React frontend for the interactive calendar interface and a Python backend for schedule generation, scoring, and future AI-assisted input parsing.

## Features

- Upload a course-listing screenshot to extract editable lecture, quiz, and lab times.
- Enter courses with lectures, quiz sections, labs, and meeting times.
- Mark sections as fixed when the user has already chosen them.
- Filter by availability, such as open-only sections.
- Detect time conflicts across weekdays.
- Apply preferences such as avoiding early classes or avoiding awkward gaps.
- Generate multiple ranked schedule plans.
- Explain why each schedule is recommended or penalized.
- Return deterministic Top N recommendations through a single API.
- Visualize each schedule as a weekly calendar.
- Compare alternate course sets, such as `208 + 414 + 370 + 332` versus `351 + 414 + 370 + 332`.

## Tech Stack

- Frontend: React, TypeScript, Vite
- Backend: Python, FastAPI
- Scheduling Engine: Python service layer
- Testing: pytest for backend tests, Vitest for frontend tests
- AI Layer: validated screenshot extraction, preference parsing, and grounded reason rewriting

## Requirements

Planned development requirements:

- Node.js 20+
- Python 3.11+
- npm or pnpm
- pip
- Git

Manual course entry does not require an external API key. Screenshot extraction and natural-language preference parsing require an OpenAI API key and a configured model with image input support.

## Installation

Clone the repository:

```bash
git clone <repository-url>
cd calendar-agent
```

Install frontend dependencies:

```bash
cd frontend
npm install
```

Install backend dependencies:

```bash
cd ../backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The backend uses FastAPI and Uvicorn.

## Usage

Start the backend:

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

The backend runs at `http://127.0.0.1:8000` by default.

Start the frontend:

```bash
cd frontend
npm run dev
```

Open the local app:

```text
http://localhost:5173
```

Example workflow:

1. Queue one or more clear PNG, JPEG, or WebP screenshots for a course and
   manually extract their sections, or add the course manually.
2. Review and edit each extracted lecture and quiz section.
3. Lock fixed sections, such as `CSE 414 C` and `CSE 414 CD`.
4. Set preferences, such as no classes before `9:30 AM` unless unavoidable.
5. Generate schedule options.
6. Compare the ranked results in the weekly calendar view.

The implemented frontend presents this as a three-stage guided workflow:
**Course data**, **Confirm preferences**, and **Schedule options**. Users add
courses through a structured form with repeatable lecture, quiz, and lab rows;
the frontend converts those rows into the backend course schema internally. It
summarizes the resulting section groups, calls the AI preference parser, lets
the user confirm the validated interpretation, and then calls the ranked
schedule API. Candidate schedules can be switched directly in the results view,
with a weekly calendar, score, reasons, trade-offs, and score breakdown for each
option. See
[`docs/frontend-workflow.md`](docs/frontend-workflow.md) for the complete UI flow
and course-input behavior.

AI interpretation is always shown before generation. Users can return to edit
the original preference text, and unresolved hard conflicts disable schedule
generation. Validation, AI, connectivity, and no-result states provide specific
recovery information instead of a generic failure message.

Numeric hard gap rules are structured and enforced by the solver. For example,
“gaps must be 10 minutes or at least 2 hours” becomes
`allowedGapMinutes: 10` and `minimumLongGapMinutes: 120`; schedules with an
11–119 minute same-day gap are filtered out rather than merely ranked lower.

Preference text accepts English or Chinese. Blank preference text is handled as
an explicit default of open sections only, with no additional ranking
preferences.

### Screenshot Course Extraction

In the **Add a course** panel, focus the course screenshot area and paste images
from the clipboard, or select **Choose image** for one or more PNG, JPEG, or
WebP files up to 10 MB each. Screenshots are queued without being parsed. Select
**Extract sections** when all screenshots for that course are ready. Images may
be uploaded before entering the course code, but the code is required before
extraction so it can be sent as a recognition hint. Each image must contain
exactly one course, and all queued images must represent the same course. The
backend sends the images to the configured vision-capable model and
merges their validated results against the same `Course`, `SectionGroup`,
`Section`, and `Meeting` models used by manual entry. Recognition fills the
current course draft, where every course code, section ID, status, SLN, weekday,
time, location, and linked lecture can be corrected before selecting **Add
course**. The source image is discarded after the course is added; only the
validated, editable course data is retained.

The manual section area starts empty; the UI does not create or assume a default
lecture schedule, and its column labels stay hidden until a row exists. New rows
use muted examples for the section ID and 12-hour time fields rather than actual
values. If screenshots are queued without a course code, clicking the extraction
action explains that the code is required.

The extraction endpoint is `POST /api/courses/extract-from-image`. It accepts
`imageBase64`, `mediaType`, and optional `courseCodeHint` and `courseTitleHint`
fields. It returns `courses` and `warnings`, and never sends unvalidated AI
output to the scheduler. Supported media types are `image/png`, `image/jpeg`,
and `image/webp`.

## Example Input

```json
{
  "courses": [
    {
      "code": "CSE 373",
      "title": "Data Structures and Algorithms",
      "groups": [
        {
          "type": "lecture",
          "choose": 1,
          "sections": [
            {
              "id": "A",
              "status": "open",
              "sln": "12301",
              "meetings": [
                {
                  "days": ["M", "W", "F"],
                  "startTime": "09:30",
                  "endTime": "10:20",
                  "location": "KNE 120"
                }
              ]
            }
          ]
        }
      ]
    }
  ],
  "preferences": {
    "earliestStart": "09:30",
    "allowEarlierIfOnlyOption": true,
    "allowedGapMinutes": 90,
    "minimumLongGapMinutes": 120,
    "requireOpenSections": true,
    "fixedSections": {
      "CSE 373": ["A"]
    }
  }
}
```

This payload maps directly to `ScheduleRequest`. The canonical field
definitions, defaults, validation rules, object relationships, and response
example are documented in [`docs/input-format.md`](docs/input-format.md).
The complete development fixture includes lecture-only, lecture+lab, and
lecture+quiz+lab courses in
[`sample-data/courses.json`](sample-data/courses.json).

### Request Rules

- `courses` is required and must contain at least one course. `code` values
  must be unique within the request.
- JSON uses `camelCase`. Unknown fields are rejected by the backend models.
- `days` only accepts `M`, `T`, `W`, `Th`, and `F`.
- The UI displays and edits meeting times in 12-hour AM/PM format. API fields
  `startTime`, `endTime`, and `earliestStart` use strict 24-hour `HH:MM`, such
  as `09:30`. Every meeting must satisfy `startTime < endTime`.
- A section group's `choose` value is optional, defaults to `1`, and cannot use
  any other value. An empty declared group produces zero schedules.
- Course components are defined only by `groups`. A missing quiz or lab group is
  not inferred or added by the backend.
- Quiz and lab sections should provide `parentSectionId` referencing a lecture
  in the same course. When omitted, `AA`/`AB`/`AC` are inferred as children of
  lecture `A`, `BA`/`BB`/`BC` as children of lecture `B`, and so on.
- The scheduler selects a lecture first and only combines it with linked quiz
  and lab sections. An explicit parent overrides the section-ID prefix.
- `fixedSections` maps an existing course `code` to existing section IDs in that
  course. When `requireOpenSections` is `true`, every fixed section must also be
  `open`.
- `allowedGapMinutes` and `minimumLongGapMinutes` must be non-negative when set.

The source of truth is
[`backend/app/models.py`](backend/app/models.py), with the full field table in
[`docs/input-format.md`](docs/input-format.md).

### AI Preference Output

Natural-language preferences never enter the scheduler directly. An AI parser
must first return JSON that validates as `ParsedPreferences`:

```json
{
  "earliestStart": "10:00",
  "earliestStartIsHard": true,
  "preferredDaysOff": ["F"],
  "requiredDaysOff": [],
  "preferredTimeOfDay": "afternoon",
  "gapPreference": "compact",
  "fixedSections": ["CSE 373 A"],
  "requireOpenSections": true,
  "hardConstraints": ["Do not start before 10:00"],
  "softPreferences": ["Prefer compact schedules"],
  "conflicts": [],
  "needsClarification": false,
  "clarificationQuestions": []
}
```

The AI integration uses strict Structured Outputs and requests every field in
this fixed schema. It may not return Markdown, explanatory text, extra fields,
or course and section references absent from the supplied catalog. Vague
preferences remain soft; contradictions are reported through `conflicts` and
`clarificationQuestions` instead of being invented as scheduler constraints.
The backend parses the JSON through Pydantic before any conversion.

Before scheduler conversion, the backend builds a section index from the
validated request courses. A reference such as `CSE 373 A` must match both an
existing `CSE 373` course and section `A` owned by that course. Valid references
are converted to the scheduler format `{"CSE 373": ["A"]}`; invented references
are rejected and never reach the solver.

Ambiguous language is not promoted into a hard filter. For example, "not too
early" remains a soft preference with `earliestStart: null`, while "classes
must not start before 10:00" may set a hard `10:00` boundary. When a mandatory
meaning cannot be represented safely, the parser returns
`needsClarification: true` with a focused clarification question.

The backend independently checks obvious hard conflicts after parsing. It
rejects fixed sections that meet on a required day off, start before a hard
`earliestStart`, or select multiple alternatives from the same section group.
AI-reported conflicts are also blocking. These cases return an
`ai_preference_conflict` error and do not enter schedule generation.

AI failures are fail-closed. Timeout, authentication, rate-limit, network,
provider, empty-output, malformed-JSON, Markdown-wrapped JSON, and schema
validation failures return explicit API errors. The backend does not substitute
default preferences or generate a schedule after a parsing failure.

`to_scheduler_preferences()` converts recognized structured fields into the
Week 2/3 `Preferences` model. Fixed sections and open-only are hard scheduler
filters. A hard earliest start maps to the engine's earliest-start fields.
Preferred days off and free-text preference arrays are retained for future
ranking or explanation and are not executed as filtering rules.

## Example Response

```json
{
  "schedules": [],
  "count": 0,
  "warnings": []
}
```

## Parse Preferences API

`POST /parse-preferences` converts natural-language scheduling preferences into
validated, course-grounded `ParsedPreferences`. The request must include the
real course catalog because fixed sections are checked against it.

```json
{
  "courses": [
    {
      "code": "CSE 373",
      "title": "Data Structures and Algorithms",
      "groups": [
        {
          "type": "lecture",
          "choose": 1,
          "sections": [
            {
              "id": "A",
              "status": "open",
              "meetings": [
                {
                  "days": ["M", "W", "F"],
                  "startTime": "10:30",
                  "endTime": "11:20"
                }
              ]
            }
          ]
        }
      ]
    }
  ],
  "preferenceText": "Avoid early classes, prefer Friday off, and require CSE 373 A."
}
```

The response is the `ParsedPreferences` schema shown above. The endpoint never
returns raw model output. Pydantic validation, course/section grounding, and
hard-conflict checks complete before a response is returned. It does not invoke
schedule generation; callers explicitly pass converted preferences to the
scheduler in a later step.

Run all backend tests:

```bash
cd backend
source .venv/bin/activate
pytest
```

Run only AI parser and endpoint tests:

```bash
pytest tests/ai
```

## Generate Schedules API

`POST /api/schedules/generate` connects validated preferences, the conflict-free
scheduler, deterministic scoring, Top N ranking, and grounded explanations.
Send exactly one of `preferenceText` or a previously parsed `preferences`
object. `topN` defaults to `5`; `enhanceReasons` defaults to `true`.

```json
{
  "courses": [
    {
      "code": "CSE 373",
      "title": "Data Structures and Algorithms",
      "groups": [
        {
          "type": "lecture",
          "choose": 1,
          "sections": [
            {
              "id": "A",
              "status": "open",
              "meetings": [
                {
                  "days": ["M", "W", "F"],
                  "startTime": "10:30",
                  "endTime": "11:20"
                }
              ]
            }
          ]
        }
      ]
    }
  ],
  "preferenceText": "Prefer afternoon classes and require CSE 373 A.",
  "topN": 5,
  "enhanceReasons": true
}
```

Every returned schedule has `rank`, `score`, `sections`, `scoreBreakdown`,
`reasons`, and `tradeoffs`. Ranking is fully deterministic; AI never assigns a
score or rank. AI may only rewrite existing explanations, and an invalid or
unavailable rewrite falls back to deterministic text without failing schedule
generation. See [`docs/ranking-and-api.md`](docs/ranking-and-api.md) for the
complete response and scoring contract.

Scoring is preference-driven. In particular, gap length and compactness affect
scores only when the user supplies `gapPreference: "compact"`, `"balanced"`, or
`"breaks"`. With `gapPreference: "none"`, all schedules receive the same neutral
gap contribution and gap shape does not affect ranking.

### Reviewing and Editing Courses

After a course is added, the frontend displays its code, title, groups, section
IDs, status, SLN, meeting days and times, location, and linked lecture. Each
course has an edit action covering all of those fields.
Saving runs frontend structural validation again and clears stale preference and
schedule results before the next generation request.

Linked components follow the same rule in the frontend and backend: Lecture `A`
can only combine with `A`-prefixed quiz/lab sections such as `AA`, `AB`, and
`AC`, or a section whose explicit `parentSectionId` is `A`. It cannot combine
with `BA`, `BB`, or `BC`. Explicit parent links are shown as “Linked to Lecture
A” so incorrect course data can be spotted before generation.

Each score-breakdown rule includes its score delta, matched preference,
calculation details, reason and trade-off candidates, and affected sections and
meetings. The API validates that the total score equals the sum of these rule
contributions. `topN` defaults to 5, and preference-aware deterministic
tie-breakers produce stable ranks for identical input.

When no legal schedule exists, the endpoint still returns HTTP 200 with the
same stable response shape and actionable warnings:

```json
{
  "interpretedPreferences": {
    "earliestStart": null,
    "earliestStartIsHard": false,
    "preferredDaysOff": [],
    "requiredDaysOff": [],
    "preferredTimeOfDay": "none",
    "gapPreference": "none",
    "fixedSections": [],
    "requireOpenSections": true,
    "hardConstraints": [],
    "softPreferences": [],
    "conflicts": [],
    "needsClarification": false,
    "clarificationQuestions": []
  },
  "schedules": [],
  "count": 0,
  "warnings": [
    "All remaining combinations have meeting conflicts or incompatible course-component requirements."
  ]
}
```

## Project Structure

Current structure:

```text
calendar-agent/
├── README.md
├── .env.example
├── docs/
│   ├── agent-design.md
│   └── input-format.md
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── src/
│   │   ├── test/
│   │   │   └── setup.ts
│   │   ├── App.test.tsx
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── styles.css
│   │   └── vite-env.d.ts
│   ├── tsconfig.json
│   ├── tsconfig.node.json
│   └── vite.config.ts
├── backend/
│   ├── README.md
│   ├── pytest.ini
│   ├── requirements.txt
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── normalization.py
│   │   ├── ai/
│   │   │   ├── __init__.py
│   │   │   ├── client.py
│   │   │   ├── context.py
│   │   │   ├── preference_parser.py
│   │   │   └── prompts.py
│   │   └── scheduler/
│   │       ├── __init__.py
│   │       ├── time_utils.py
│   │       ├── solver.py
│   │       ├── scoring.py
│   │       └── explanations.py
│   └── tests/
│       ├── ai/
│       │   ├── test_client.py
│       │   ├── test_context.py
│       │   └── test_preference_parser.py
│       ├── scheduler/
│       │   ├── test_sample_data.py
│       │   ├── test_solver.py
│       │   └── test_time_utils.py
│       ├── test_health.py
│       ├── test_models.py
│       ├── test_normalization.py
│       ├── test_parsed_preferences.py
│       └── test_validation.py
└── sample-data/
    └── courses.json
```

Directory responsibilities:

- `frontend/`: React, TypeScript, and Vite application for course input, preference controls, schedule results, and calendar visualization.
- `backend/`: Python backend for schedule generation, scoring, API routes, and future AI-assisted extraction.
- `backend/app/scheduler/`: Framework-independent time, combination, conflict,
  scoring, and explanation logic that can be tested without FastAPI.
- `sample-data/`: Example course and preference payloads used for development and testing.
- `docs/`: Product notes, agent design, and input-format documentation.
- `.env.example`: Template for local configuration values.

## Configuration

Create a local environment file from the provided example:

```bash
cp .env.example .env
```

The example contains:

```bash
VITE_API_BASE_URL=http://localhost:8000
BACKEND_HOST=127.0.0.1
BACKEND_PORT=8000
OPENAI_API_KEY=
OPENAI_MODEL=
AI_PREFERENCE_TIMEOUT_SECONDS=20
```

`VITE_API_BASE_URL` tells the React app where to reach FastAPI. Vite is configured
to load `.env` from the repository root. `BACKEND_HOST` and `BACKEND_PORT` define
the intended local backend bind address. Keep secrets in `.env`; Git ignores that
file, while `.env.example` documents safe placeholder values.

`OPENAI_API_KEY` and `OPENAI_MODEL` are required only when an AI feature is
called. `AI_PREFERENCE_TIMEOUT_SECONDS` defaults to `20` and must be greater
than zero. The key is read at runtime by the backend AI client and must never be
committed or sent to the frontend.

To run Uvicorn with the configured backend values:

```bash
cd backend
source .venv/bin/activate
set -a
source ../.env
set +a
uvicorn app.main:app --reload --host "$BACKEND_HOST" --port "$BACKEND_PORT"
```

## Testing

Run backend tests:

```bash
cd backend
pytest
```

Run frontend tests:

```bash
cd frontend
npm run test
```

Run the frontend tests continuously while editing:

```bash
cd frontend
npm run test:watch
```

The current frontend verification commands are:

```bash
cd frontend
npm run build
npm run dev
```

Testing should cover:

- Time parsing.
- Conflict detection.
- Gap calculation.
- Fixed-section handling.
- Schedule ranking.
- API request and response validation.
- Calendar rendering behavior.

## Week 2 — Course Schema & Validation

**Dates:** 2026-08-17 to 2026-08-23

**Goal:** Accurately represent different course structures through explicit
section groups and reject invalid course data at the request boundary.

### Completion Standard

Week 2 is complete when all of the following remain true:

- `Meeting`, `Section`, `SectionGroup`, `Course`, `Preferences`,
  `ParsedPreferences`, and `ScheduleRequest` are implemented as
  Pydantic models.
- The README request and response JSON examples parse through those models.
- `sample-data/courses.json` contains lecture-only, lecture+lab, and
  lecture+quiz+lab examples with open and closed sections.
- Parsing a course preserves exactly its input groups and never adds absent
  components.
- Quiz and lab sections reference a valid parent lecture, explicitly through
  `parentSectionId` or through validated section-ID prefix inference.
- Course combinations contain only lecture-compatible quiz and lab sections.
- Invalid weekdays, time formats, time ranges, group selection counts, and fixed
  sections produce validation errors.
- Running `cd backend && pytest` passes the complete backend test suite.

## Known Issues / Limitations

- Screenshot extraction requires a configured vision-capable OpenAI model and
  users should review the editable result before adding a course.
- Seat availability refresh is planned but not implemented yet.
- The scheduler currently supports Monday through Friday schedules.

## Roadmap

- Add live seat availability refresh.
- Add import support for structured registration exports.
- Improve screenshot extraction confidence reporting and correction guidance.
- Expand scheduling support beyond weekday course meetings.
- Add export to `.ics` calendar files.
- Add saved schedule scenarios.

## Contributing

This is currently a personal planning and portfolio project. A future contribution workflow may use:

1. Fork the repository.
2. Create a feature branch.
3. Make changes.
4. Run backend and frontend tests.
5. Open a pull request with a clear description.

## Author

Yz Wang

## License

License to be decided.
