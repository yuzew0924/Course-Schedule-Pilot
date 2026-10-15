import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Bot,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronRight,
  ImageUp,
  LoaderCircle,
  Pencil,
  Plus,
  Sparkles,
  Trash2
} from "lucide-react";
import { useEffect, useMemo, useState, type ClipboardEvent as ReactClipboardEvent, type CSSProperties } from "react";

type DayCode = "M" | "T" | "W" | "Th" | "F";
type Stage = "input" | "review" | "results";
type BackendState = "checking" | "online" | "unavailable";

type Meeting = {
  days: DayCode[];
  startTime: string;
  endTime: string;
  location?: string | null;
};

type Section = {
  id: string;
  status: "open" | "closed" | "unknown";
  sln?: string | null;
  meetings: Meeting[];
  parentSectionId?: string | null;
};

type SectionGroup = {
  type: string;
  choose?: number;
  sections: Section[];
};

type Course = {
  code: string;
  title?: string | null;
  groups: SectionGroup[];
};

type ParsedPreferences = {
  earliestStart: string | null;
  earliestStartIsHard: boolean;
  preferredDaysOff: DayCode[];
  requiredDaysOff: DayCode[];
  preferredTimeOfDay: "morning" | "afternoon" | "evening" | "none";
  gapPreference: "compact" | "balanced" | "breaks" | "none";
  allowedGapMinutes: number | null;
  minimumLongGapMinutes: number | null;
  fixedSections: string[];
  requireOpenSections: boolean;
  hardConstraints: string[];
  softPreferences: string[];
  conflicts: string[];
  needsClarification: boolean;
  clarificationQuestions: string[];
};

type ScoreBreakdownItem = {
  score: number;
  maximum: number;
  scoreDelta: number;
  matchedPreference: string | null;
  details: string;
  reasonCandidate: string | null;
  tradeoffCandidate: string | null;
  affectedSections: string[];
  affectedMeetings: Array<{
    courseCode: string;
    sectionId: string;
    day: DayCode;
    startTime: string;
    endTime: string;
  }>;
};

type ScheduleSection = {
  courseCode: string;
  groupType: string;
  sectionId: string;
  status: string;
  sln?: string | null;
  meetings: Meeting[];
};

type RankedSchedule = {
  rank: number;
  score: number;
  sections: ScheduleSection[];
  scoreBreakdown: Record<string, ScoreBreakdownItem>;
  reasons: string[];
  tradeoffs: string[];
};

type GenerateResponse = {
  interpretedPreferences: ParsedPreferences;
  schedules: RankedSchedule[];
  count: number;
  warnings: string[];
};

type CourseImageExtraction = {
  courses: Course[];
  warnings: string[];
};

type CourseScreenshot = {
  id: string;
  name: string;
  mediaType: string;
  dataUrl: string;
};

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(
  /\/$/,
  ""
);

const defaultPreferences: ParsedPreferences = {
  earliestStart: null,
  earliestStartIsHard: false,
  preferredDaysOff: [],
  requiredDaysOff: [],
  preferredTimeOfDay: "none",
  gapPreference: "none",
  allowedGapMinutes: null,
  minimumLongGapMinutes: null,
  fixedSections: [],
  requireOpenSections: true,
  hardConstraints: [],
  softPreferences: [],
  conflicts: [],
  needsClarification: false,
  clarificationQuestions: []
};
const dayLabels: Record<DayCode, string> = {
  M: "Monday",
  T: "Tuesday",
  W: "Wednesday",
  Th: "Thursday",
  F: "Friday"
};
const days = Object.keys(dayLabels) as DayCode[];
const palette = ["violet", "green", "blue", "orange", "rose"];

type SectionDraft = {
  key: number;
  type: "lecture" | "quiz" | "lab";
  id: string;
  days: string;
  startTime: string;
  endTime: string;
  status: "open" | "closed" | "unknown";
  sln: string;
  location: string;
  parentSectionId: string;
};

const newSectionDraft = (key: number, id = "A"): SectionDraft => ({
  key,
  type: "lecture",
  id,
  days: "MWF",
  startTime: "09:30",
  endTime: "10:20",
  status: "open",
  sln: "",
  location: "",
  parentSectionId: ""
});

function formatTime12(value: string): string {
  const [hourText, minute = "00"] = value.split(":");
  const hour = Number(hourText);
  if (!Number.isInteger(hour) || hour < 0 || hour > 23) return value;
  return `${hour % 12 || 12}:${minute} ${hour < 12 ? "AM" : "PM"}`;
}

function Time12Input({
  label,
  value,
  onChange
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const [hourText = "09", minute = "00"] = value.split(":");
  const hour24 = Number(hourText);
  const period = hour24 >= 12 ? "PM" : "AM";
  const hour12 = hour24 % 12 || 12;
  const minuteOptions = Array.from(new Set(["00", "10", "20", "30", "40", "50", minute])).sort();
  const update = (nextHour: number, nextMinute: string, nextPeriod: string) => {
    const normalizedHour = nextHour % 12 + (nextPeriod === "PM" ? 12 : 0);
    onChange(`${String(normalizedHour).padStart(2, "0")}:${nextMinute}`);
  };
  return (
    <div className="time-12-input" role="group" aria-label={label}>
      <select aria-label={`${label} hour`} value={hour12} onChange={(event) => update(Number(event.target.value), minute, period)}>
        {Array.from({ length: 12 }, (_, index) => index + 1).map((hour) => <option key={hour} value={hour}>{hour}</option>)}
      </select>
      <span>:</span>
      <select aria-label={`${label} minute`} value={minute} onChange={(event) => update(hour12, event.target.value, period)}>
        {minuteOptions.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
      <select aria-label={`${label} period`} value={period} onChange={(event) => update(hour12, minute, event.target.value)}>
        <option value="AM">AM</option><option value="PM">PM</option>
      </select>
    </div>
  );
}

function mergeExtractedCourses(courses: Course[]): Course {
  if (!courses.length) throw new Error("No course data was found in the selected screenshots.");
  const codes = new Set(courses.map((course) => course.code));
  if (codes.size !== 1) throw new Error("All screenshots must show the same course.");
  const grouped = new Map<string, Map<string, Section>>();
  courses.forEach((course) => course.groups.forEach((group) => {
    const sections = grouped.get(group.type) ?? new Map<string, Section>();
    group.sections.forEach((section) => sections.set(section.id, section));
    grouped.set(group.type, sections);
  }));
  return {
    code: courses[0].code,
    title: courses.find((course) => course.title)?.title ?? null,
    groups: Array.from(grouped, ([type, sections]) => ({ type, choose: 1, sections: Array.from(sections.values()) }))
  };
}

function courseToDrafts(course: Course): SectionDraft[] {
  let key = 1;
  return course.groups.flatMap((group) => group.sections.map((section) => {
    const meeting = section.meetings[0];
    return {
      key: key++,
      type: group.type as SectionDraft["type"],
      id: section.id,
      days: meeting?.days.join("") ?? "",
      startTime: meeting?.startTime ?? "",
      endTime: meeting?.endTime ?? "",
      status: section.status,
      sln: section.sln ?? "",
      location: meeting?.location ?? "",
      parentSectionId: section.parentSectionId ?? ""
    };
  }));
}

function parseDayCodes(value: string): DayCode[] {
  const compact = value.replace(/[\s,/]+/g, "");
  const parsed: DayCode[] = [];
  for (let index = 0; index < compact.length;) {
    const token = compact.slice(index, index + 2).toLowerCase() === "th"
      ? "Th"
      : compact[index]?.toUpperCase();
    if (!(["M", "T", "W", "Th", "F"] as string[]).includes(token)) {
      throw new Error(`Use weekday codes M, T, W, Th, and F. "${value}" is invalid.`);
    }
    const day = token as DayCode;
    if (!parsed.includes(day)) parsed.push(day);
    index += token === "Th" ? 2 : 1;
  }
  if (!parsed.length) throw new Error("Every section needs at least one meeting day.");
  return parsed;
}

function buildCourse(codeInput: string, titleInput: string, drafts: SectionDraft[]): Course {
  const code = codeInput.trim().replace(/\s+/g, " ").toUpperCase();
  if (!code) throw new Error("Enter a course name.");
  if (!drafts.length) throw new Error("Add at least one section time.");

  const seen = new Set<string>();
  const lectureIds = new Set(
    drafts
      .filter((draft) => draft.type === "lecture")
      .map((draft) => draft.id.trim().toUpperCase())
  );
  const grouped = new Map<string, Section[]>();
  drafts.forEach((draft) => {
    const id = draft.id.trim().toUpperCase();
    if (!id) throw new Error("Every section needs a section ID.");
    if (!/^[A-Z][A-Z0-9]*$/.test(id)) {
      throw new Error(`Section ID ${id} must start with a letter and use only letters or numbers.`);
    }
    if (seen.has(id)) throw new Error(`Section ID ${id} is duplicated in ${code}.`);
    if (!draft.startTime || !draft.endTime || draft.startTime >= draft.endTime) {
      throw new Error(`${code} ${id} must end after it starts.`);
    }
    if (draft.type === "lecture" && draft.parentSectionId.trim()) {
      throw new Error(`Lecture ${id} cannot have a parent lecture.`);
    }
    const parentSectionId = draft.type === "lecture"
      ? null
      : (draft.parentSectionId.trim().toUpperCase() || id[0]);
    if (parentSectionId && !lectureIds.has(parentSectionId)) {
      throw new Error(
        `${draft.type} ${id} must link to an existing lecture; ${parentSectionId} was not found.`
      );
    }
    seen.add(id);
    const sections = grouped.get(draft.type) ?? [];
    sections.push({
      id,
      status: draft.status,
      sln: draft.sln.trim() || null,
      parentSectionId,
      meetings: [{
        days: parseDayCodes(draft.days),
        startTime: draft.startTime,
        endTime: draft.endTime,
        location: draft.location.trim() || null
      }]
    });
    grouped.set(draft.type, sections);
  });

  return {
    code,
    title: titleInput.trim() || null,
    groups: Array.from(grouped, ([type, sections]) => ({ type, choose: 1, sections }))
  };
}

async function apiRequest<T>(path: string, body: object): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
  } catch {
    throw new Error(
      `Backend unavailable at ${apiBaseUrl}. Start the FastAPI service and try again.`
    );
  }
  const payload = (await response.json().catch(() => ({}))) as {
    error?: { message?: string };
    detail?: string | Array<{ loc?: Array<string | number>; msg?: string }>;
  } & T;
  if (!response.ok) {
    const validationDetails = Array.isArray(payload.detail)
      ? payload.detail.map((item) => `${item.loc?.slice(1).join(".") || "request"}: ${item.msg || "invalid value"}`).join("; ")
      : payload.detail;
    throw new Error(
      payload.error?.message || validationDetails || `Request failed with status ${response.status}.`
    );
  }
  return payload;
}

function TopBar() {
  const [backendState, setBackendState] = useState<BackendState>("checking");

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${apiBaseUrl}/health`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Health check failed");
        const body = (await response.json()) as { status?: string };
        if (body.status !== "ok") throw new Error("Unexpected health response");
        setBackendState("online");
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setBackendState("unavailable");
      });
    return () => controller.abort();
  }, []);

  const label = {
    checking: "Checking backend",
    online: "Backend online",
    unavailable: "Backend unavailable"
  }[backendState];

  return (
    <header className="top-bar">
      <div className="brand">
        <CalendarDays size={23} aria-hidden="true" />
        <h1>Course Schedule Pilot</h1>
      </div>
      <div className={`backend-status ${backendState}`} role="status" aria-live="polite">
        <span aria-hidden="true" />
        {label}
      </div>
    </header>
  );
}

function Workflow({ stage }: { stage: Stage }) {
  const current = stage === "input" ? 1 : stage === "review" ? 2 : 3;
  return (
    <ol className="workflow" aria-label="Schedule planning progress">
      {["Course data", "Confirm preferences", "Schedule options"].map((label, index) => (
        <li className={current >= index + 1 ? "active" : ""} key={label}>
          <span>{current > index + 1 ? <Check size={14} /> : index + 1}</span>
          {label}
          {index < 2 && <ChevronRight size={15} aria-hidden="true" />}
        </li>
      ))}
    </ol>
  );
}

function CourseWorkspace({
  courses,
  onSave,
  onRemove
}: {
  courses: Course[];
  onSave: (originalCode: string, course: Course) => string | null;
  onRemove: (code: string) => void;
}) {
  return (
    <div className="course-workspace" aria-label="Entered courses">
      {courses.map((course) => (
        <EditableCourse key={course.code} course={course} onSave={onSave} onRemove={onRemove} />
      ))}
    </div>
  );
}

function EditableCourse({
  course,
  onSave,
  onRemove
}: {
  course: Course;
  onSave: (originalCode: string, course: Course) => string | null;
  onRemove: (code: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [code, setCode] = useState(course.code);
  const [title, setTitle] = useState(course.title ?? "");
  const [drafts, setDrafts] = useState(() => courseToDrafts(course));
  const [error, setError] = useState("");

  const reset = () => {
    setCode(course.code);
    setTitle(course.title ?? "");
    setDrafts(courseToDrafts(course));
    setError("");
  };
  const updateDraft = (key: number, field: keyof SectionDraft, value: string) => {
    setDrafts((current) => current.map((draft) =>
      draft.key === key ? { ...draft, [field]: value } : draft
    ));
    setError("");
  };
  const save = () => {
    try {
      const updated = buildCourse(code, title, drafts);
      const saveError = onSave(course.code, updated);
      if (saveError) throw new Error(saveError);
      setEditing(false);
      setError("");
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Invalid course data.");
    }
  };

  if (editing) {
    return (
      <article className="course-detail-card editing">
        <div className="course-edit-header">
          <label>Course code<input value={code} onChange={(event) => setCode(event.target.value)} /></label>
          <label>Title<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Optional title" /></label>
        </div>
        <div className="section-editor-list">
          {drafts.map((draft) => (
            <fieldset className="section-edit-card" key={draft.key}>
              <legend>{draft.type} {draft.id}</legend>
              <label>Type<select value={draft.type} onChange={(event) => updateDraft(draft.key, "type", event.target.value)}><option value="lecture">Lecture</option><option value="quiz">Quiz</option><option value="lab">Lab</option></select></label>
              <label>Section ID<input value={draft.id} onChange={(event) => updateDraft(draft.key, "id", event.target.value)} /></label>
              <label>Status<select value={draft.status} onChange={(event) => updateDraft(draft.key, "status", event.target.value)}><option value="open">Open</option><option value="closed">Closed</option><option value="unknown">Unknown</option></select></label>
              <label>SLN<input value={draft.sln} onChange={(event) => updateDraft(draft.key, "sln", event.target.value)} placeholder="Optional" /></label>
              <label>Days<input value={draft.days} onChange={(event) => updateDraft(draft.key, "days", event.target.value)} placeholder="MWF" /></label>
              <label>Start<Time12Input label={`${draft.id} start time`} value={draft.startTime} onChange={(value) => updateDraft(draft.key, "startTime", value)} /></label>
              <label>End<Time12Input label={`${draft.id} end time`} value={draft.endTime} onChange={(value) => updateDraft(draft.key, "endTime", value)} /></label>
              <label>Location<input value={draft.location} onChange={(event) => updateDraft(draft.key, "location", event.target.value)} placeholder="Optional" /></label>
              <label>Parent lecture<input value={draft.parentSectionId} onChange={(event) => updateDraft(draft.key, "parentSectionId", event.target.value)} placeholder={draft.type === "lecture" ? "Not applicable" : "A"} disabled={draft.type === "lecture"} /></label>
              <button className="icon-button remove-edit-row" type="button" aria-label={`Remove ${draft.id}`} disabled={drafts.length === 1} onClick={() => setDrafts((current) => current.filter((item) => item.key !== draft.key))}><Trash2 size={17} /></button>
            </fieldset>
          ))}
        </div>
        <button className="add-section-button" type="button" onClick={() => setDrafts((current) => [...current, newSectionDraft(Math.max(0, ...current.map((draft) => draft.key)) + 1)])}><Plus size={17} /> Add section</button>
        {error && <div className="error-message" role="alert"><AlertCircle size={17} /> {error}</div>}
        <div className="course-edit-actions">
          <button className="secondary-button" type="button" onClick={() => { reset(); setEditing(false); }}>Cancel</button>
          <button className="save-course-button" type="button" onClick={save}><Check size={17} /> Save changes</button>
        </div>
      </article>
    );
  }

  return (
    <article className="course-detail-card">
      <header className="course-detail-header">
        <div><h4>{course.code}</h4><p>{course.title || "Untitled course"}</p></div>
        <div className="course-card-actions">
          <button className="icon-button" type="button" title="Edit course" aria-label={`Edit ${course.code}`} onClick={() => { reset(); setEditing(true); }}><Pencil size={16} /></button>
          <button className="icon-button danger" type="button" title="Remove course" aria-label={`Remove ${course.code}`} onClick={() => onRemove(course.code)}><Trash2 size={16} /></button>
        </div>
      </header>
      {course.groups.map((group) => (
        <section className="course-group" key={group.type}>
          <h5>{group.type}</h5>
          {group.sections.map((section) => section.meetings.map((meeting, meetingIndex) => (
            <div className="section-detail-row" key={`${section.id}-${meetingIndex}`}>
              <strong>{section.id}</strong>
              <span className={`status-badge ${section.status}`}>{section.status}</span>
              <span>{meeting.days.join("")} · {formatTime12(meeting.startTime)}–{formatTime12(meeting.endTime)}</span>
              <span>{meeting.location || "Location not set"}</span>
              <span>{section.sln ? `SLN ${section.sln}` : "No SLN"}</span>
              {group.type !== "lecture" && <span className="parent-link">Linked to Lecture {section.parentSectionId || section.id[0]}</span>}
            </div>
          )))}
        </section>
      ))}
    </article>
  );
}

type InputViewProps = {
  courseCode: string;
  courseTitle: string;
  sectionDrafts: SectionDraft[];
  courses: Course[];
  preferenceText: string;
  courseError: string;
  requestError: string;
  loading: boolean;
  imageLoading: boolean;
  screenshots: CourseScreenshot[];
  imageWarnings: string[];
  onCourseCodeChange: (value: string) => void;
  onCourseTitleChange: (value: string) => void;
  onSectionChange: (key: number, field: keyof SectionDraft, value: string) => void;
  onAddSection: () => void;
  onRemoveSection: (key: number) => void;
  onAddCourse: () => void;
  onRemoveCourse: (code: string) => void;
  onSaveCourse: (originalCode: string, course: Course) => string | null;
  onImageSelect: (file: File) => void;
  onRemoveImage: (id: string) => void;
  onExtractImages: () => void;
  onPreferenceChange: (value: string) => void;
  onInterpret: () => void;
};

function InputView(props: InputViewProps) {
  return (
    <main className="input-layout">
      <section className="panel course-input-panel">
        <div className="panel-heading"><div><span className="eyebrow">Step 1</span><h2>Add a course</h2></div></div>

        <div className="course-basics">
          <label className="field-label" htmlFor="course-code">
            Course code
            <input id="course-code" className="course-name-input" value={props.courseCode} onChange={(event) => props.onCourseCodeChange(event.target.value)} placeholder="CSE 414" />
          </label>
          <label className="field-label" htmlFor="course-title">
            Title
            <input id="course-title" className="course-name-input" value={props.courseTitle} onChange={(event) => props.onCourseTitleChange(event.target.value)} placeholder="Optional course title" />
          </label>
        </div>

        <div
          className="image-import"
          tabIndex={0}
          onPaste={(event: ReactClipboardEvent<HTMLDivElement>) => {
            const image = Array.from(event.clipboardData.files).find((file) => file.type.startsWith("image/"));
            if (image) {
              event.preventDefault();
              props.onImageSelect(image);
            }
          }}
          aria-label="Course screenshot paste area"
        >
          <div className="image-import-copy">
            <span className="image-import-icon"><ImageUp size={20} aria-hidden="true" /></span>
            <div>
              <strong>Course screenshot</strong>
              <p>Paste or upload one or more screenshots for this course. Images are only read when you select Extract sections.</p>
            </div>
          </div>
          <label className={`image-upload-button ${props.imageLoading ? "disabled" : ""}`}>
            {props.imageLoading ? <LoaderCircle className="spin" size={17} /> : <ImageUp size={17} />}
            {props.imageLoading ? "Reading image" : "Choose image"}
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              disabled={props.imageLoading}
              multiple
              onChange={(event) => {
                Array.from(event.target.files ?? []).forEach(props.onImageSelect);
                event.target.value = "";
              }}
            />
          </label>
          {props.screenshots.length > 0 && <div className="image-preview-grid">
            {props.screenshots.map((screenshot, index) => <div className="image-preview-wrap" key={screenshot.id}>
              <img className="image-preview" src={screenshot.dataUrl} alt={`Course screenshot preview ${index + 1}`} />
              <button className="icon-button danger" type="button" aria-label={`Remove screenshot ${index + 1}`} title="Remove screenshot" onClick={() => props.onRemoveImage(screenshot.id)}><Trash2 size={16} /></button>
              <span className="image-file-name">{screenshot.name}</span>
            </div>)}
          </div>}
          {props.screenshots.length > 0 && <button className="extract-images-button" type="button" disabled={props.imageLoading} onClick={props.onExtractImages}>
            {props.imageLoading ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}
            {props.imageLoading ? `Reading ${props.screenshots.length} screenshot${props.screenshots.length === 1 ? "" : "s"}` : `Extract sections from ${props.screenshots.length} screenshot${props.screenshots.length === 1 ? "" : "s"}`}
          </button>}
          {props.imageWarnings.length > 0 && (
            <div className="image-warning" role="status">
              <strong>Check the extracted data</strong>
              <ul>{props.imageWarnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
            </div>
          )}
        </div>

        <fieldset className="section-builder">
          <legend>Possible sections</legend>
          <div className="section-column-labels" aria-hidden="true">
            <span>Type</span><span>Section</span><span>Days</span><span>Start</span><span>End</span><span />
          </div>
          {props.sectionDrafts.map((section) => (
            <div className="section-input-row" key={section.key}>
              <select
                aria-label={`Section ${section.key} type`}
                value={section.type}
                onChange={(event) => props.onSectionChange(section.key, "type", event.target.value)}
              >
                <option value="lecture">Lecture</option>
                <option value="quiz">Quiz</option>
                <option value="lab">Lab</option>
              </select>
              <input
                aria-label={`Section ${section.key} ID`}
                value={section.id}
                onChange={(event) => props.onSectionChange(section.key, "id", event.target.value)}
                placeholder="A"
              />
              <input
                aria-label={`Section ${section.key} days`}
                value={section.days}
                onChange={(event) => props.onSectionChange(section.key, "days", event.target.value)}
                placeholder="MWF"
              />
              <Time12Input label={`Section ${section.key} start time`} value={section.startTime} onChange={(value) => props.onSectionChange(section.key, "startTime", value)} />
              <Time12Input label={`Section ${section.key} end time`} value={section.endTime} onChange={(value) => props.onSectionChange(section.key, "endTime", value)} />
              <button
                className="icon-button"
                type="button"
                aria-label={`Remove section ${section.id || section.key}`}
                title="Remove section"
                disabled={props.sectionDrafts.length === 1}
                onClick={() => props.onRemoveSection(section.key)}
              >
                <Trash2 size={18} />
              </button>
            </div>
          ))}
          <button className="add-section-button" type="button" onClick={props.onAddSection}>
            <Plus size={18} /> Add section time
          </button>
        </fieldset>

        {props.courseError && (
          <div className="error-message" role="alert">
            <AlertCircle size={17} /> {props.courseError}
          </div>
        )}
        <button className="add-course-button" type="button" onClick={props.onAddCourse}>
          <Plus size={18} /> Add course
        </button>

        {props.courses.length > 0 && (
          <div className="added-courses">
            <div className="added-courses-heading">
              <h3>Added courses</h3>
              <span>{props.courses.length}</span>
            </div>
            <CourseWorkspace courses={props.courses} onSave={props.onSaveCourse} onRemove={props.onRemoveCourse} />
          </div>
        )}
      </section>

      <aside className="panel preference-input-panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Step 2</span>
            <h2>Schedule preferences</h2>
          </div>
          <Bot size={22} aria-hidden="true" />
        </div>
        <label className="field-label" htmlFor="preference-text">
          Describe your ideal schedule
        </label>
        <textarea
          id="preference-text"
          className="preference-editor"
          value={props.preferenceText}
          onChange={(event) => props.onPreferenceChange(event.target.value)}
          placeholder="Example: No classes before 10:00, prefer Friday off, and require CSE 373 A."
        />
        <p className="field-help">
          English and Chinese are supported. Leave this blank to use open sections with no additional preferences.
        </p>
        <div className="preference-examples">
          <span>Later starts</span>
          <span>Compact days</span>
          <span>Fixed sections</span>
          <span>Days off</span>
        </div>
        {props.requestError && (
          <div className="error-message" role="alert">
            <AlertCircle size={17} /> {props.requestError}
          </div>
        )}
        <div className="preference-spacer" />
        <button
          className="primary-button"
          type="button"
          disabled={!props.courses.length || props.loading}
          onClick={props.onInterpret}
        >
          {props.loading ? <LoaderCircle className="spin" size={19} /> : <Sparkles size={19} />}
          {props.loading ? "Interpreting preferences" : "Interpret preferences"}
          {!props.loading && <ArrowRight size={19} />}
        </button>
      </aside>
    </main>
  );
}

function PreferenceList({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return (
    <div className="preference-list">
      <h3>{title}</h3>
      {items.length ? (
        <ul>
          {items.map((item) => (
            <li key={item}>
              <CheckCircle2 size={16} /> {item}
            </li>
          ))}
        </ul>
      ) : (
        <p>{empty}</p>
      )}
    </div>
  );
}

function ReviewView({
  preferences,
  loading,
  error,
  onBack,
  onGenerate
}: {
  preferences: ParsedPreferences;
  loading: boolean;
  error: string;
  onBack: () => void;
  onGenerate: () => void;
}) {
  const hardItems = [
    ...preferences.fixedSections.map((item) => `Required section: ${item}`),
    ...preferences.requiredDaysOff.map((day) => `${dayLabels[day]} must remain free`),
    ...(preferences.earliestStartIsHard && preferences.earliestStart
      ? [`No classes before ${preferences.earliestStart}`]
      : []),
    ...(preferences.requireOpenSections ? ["Open sections only"] : []),
    ...(preferences.allowedGapMinutes != null
      ? [preferences.minimumLongGapMinutes != null
        ? `Class gaps must be ${preferences.allowedGapMinutes} minutes or less, or at least ${preferences.minimumLongGapMinutes} minutes`
        : `Class gaps must be ${preferences.allowedGapMinutes} minutes or less`]
      : []),
    ...preferences.hardConstraints
  ];
  const softItems = [
    ...preferences.preferredDaysOff.map((day) => `Prefer ${dayLabels[day]} off`),
    ...(preferences.preferredTimeOfDay !== "none"
      ? [`Prefer ${preferences.preferredTimeOfDay} classes`]
      : []),
    ...(preferences.gapPreference !== "none"
      ? [`Gap preference: ${preferences.gapPreference}`]
      : []),
    ...(!preferences.earliestStartIsHard && preferences.earliestStart
      ? [`Prefer classes at or after ${preferences.earliestStart}`]
      : []),
    ...preferences.softPreferences
  ];

  return (
    <main className="review-layout">
      <button className="back-button" type="button" onClick={onBack}>
        <ArrowLeft size={18} /> Edit input
      </button>
      <section className="panel review-card">
        <div className="review-title">
          <span className="review-icon"><Bot size={24} /></span>
          <div>
            <span className="eyebrow">AI interpretation</span>
            <h2>Confirm your schedule requirements</h2>
          </div>
        </div>
        <div className="review-grid">
          <PreferenceList title="Hard constraints" items={hardItems} empty="No hard constraints" />
          <PreferenceList title="Soft preferences" items={softItems} empty="No soft preferences" />
        </div>
        {preferences.needsClarification && (
          <div className="clarification-box" role="alert">
            <strong>Clarification needed</strong>
            {preferences.clarificationQuestions.map((question) => <p key={question}>{question}</p>)}
          </div>
        )}
        {preferences.conflicts.length > 0 && (
          <div className="conflict-box" role="alert">
            <strong>Hard-constraint conflicts</strong>
            <ul>{preferences.conflicts.map((conflict) => <li key={conflict}>{conflict}</li>)}</ul>
            <p>Revise the preference text before generating a schedule.</p>
          </div>
        )}
        {error && <div className="error-message" role="alert"><AlertCircle size={17} /> {error}</div>}
        <div className="review-actions">
          <button className="secondary-button" type="button" onClick={onBack}>Revise preferences</button>
          <button
            className="primary-button compact"
            type="button"
            disabled={preferences.needsClarification || preferences.conflicts.length > 0 || loading}
            onClick={onGenerate}
          >
            {loading ? <LoaderCircle className="spin" size={19} /> : <Sparkles size={19} />}
            {loading ? "Generating schedules" : "Confirm and generate"}
          </button>
        </div>
      </section>
    </main>
  );
}

function toMinutes(value: string) {
  const [hour, minute] = value.split(":").map(Number);
  return hour * 60 + minute;
}

function Calendar({ schedule }: { schedule: RankedSchedule }) {
  const startMinute = 8 * 60;
  const endMinute = 18 * 60;
  const hours = Array.from({ length: 11 }, (_, index) => index + 8);
  const courseColors = new Map<string, string>();
  schedule.sections.forEach((section) => {
    if (!courseColors.has(section.courseCode)) {
      courseColors.set(section.courseCode, palette[courseColors.size % palette.length]);
    }
  });
  const events = schedule.sections.flatMap((section) =>
    section.meetings.flatMap((meeting) =>
      meeting.days.map((day) => ({ section, meeting, day }))
    )
  );

  return (
    <div className="calendar" aria-label="Weekly schedule">
      <div className="calendar-header"><span />{days.map((day) => <strong key={day}>{dayLabels[day]}</strong>)}</div>
      <div className="calendar-content">
        <div className="time-axis">{hours.map((hour) => <span key={hour}>{hour <= 12 ? hour : hour - 12} {hour < 12 ? "AM" : "PM"}</span>)}</div>
        <div className="calendar-days">
          {days.map((day) => <div className="day-column" key={day} />)}
          <div className="time-lines">{hours.map((hour) => <span key={hour} />)}</div>
          {events.map(({ section, meeting, day }, index) => {
            const style = {
              "--day": days.indexOf(day),
              "--top": `${((toMinutes(meeting.startTime) - startMinute) / (endMinute - startMinute)) * 100}%`,
              "--height": `${((toMinutes(meeting.endTime) - toMinutes(meeting.startTime)) / (endMinute - startMinute)) * 100}%`
            } as CSSProperties;
            return (
              <article className={`calendar-event ${courseColors.get(section.courseCode)}`} style={style} key={`${section.courseCode}-${section.sectionId}-${day}-${index}`}>
                <strong>{section.courseCode} {section.sectionId}</strong>
                <span>{formatTime12(meeting.startTime)} - {formatTime12(meeting.endTime)}</span>
                {meeting.location && <span>{meeting.location}</span>}
              </article>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function ResultsView({ response, onBack }: { response: GenerateResponse; onBack: () => void }) {
  const [selectedRank, setSelectedRank] = useState(response.schedules[0]?.rank ?? 0);
  const selected = response.schedules.find((item) => item.rank === selectedRank);
  return (
    <main className="results-layout">
      <aside className="results-sidebar">
        <button className="back-button" type="button" onClick={onBack}><ArrowLeft size={18} /> Edit courses &amp; preferences</button>
        <div className="results-heading"><h2>Schedule options</h2><p>{response.count} ranked schedules</p></div>
        {response.schedules.map((schedule) => (
          <button className={`schedule-card ${selectedRank === schedule.rank ? "selected" : ""}`} type="button" key={schedule.rank} onClick={() => setSelectedRank(schedule.rank)}>
            <div className="schedule-card-heading"><h3>Option {schedule.rank}</h3><strong>{schedule.score}</strong></div>
            <span className="score-label">Score</span>
            <p>{schedule.reasons[0] || "Conflict-free schedule"}</p>
          </button>
        ))}
        {!response.schedules.length && <div className="empty-state"><AlertCircle size={22} /><h3>No legal schedules</h3><ul>{response.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
      </aside>
      <section className="schedule-detail">
        {selected ? (
          <>
            <div className="detail-heading"><div><span className="eyebrow">Option {selected.rank}</span><h2>Weekly schedule</h2></div><div className="large-score"><span>Score</span><strong>{selected.score}</strong></div></div>
            <Calendar schedule={selected} />
            <div className="insight-grid">
              <section className="panel insight-panel"><h3>Why this works</h3><ul>{selected.reasons.map((reason) => <li key={reason}><CheckCircle2 size={16} />{reason}</li>)}</ul></section>
              <section className="panel insight-panel tradeoffs"><h3>Trade-offs</h3>{selected.tradeoffs.length ? <ul>{selected.tradeoffs.map((tradeoff) => <li key={tradeoff}><AlertCircle size={16} />{tradeoff}</li>)}</ul> : <p>No preference trade-offs.</p>}</section>
              <section className="panel score-panel"><h3>Score breakdown</h3>{Object.entries(selected.scoreBreakdown).map(([rule, item]) => <div className="score-row" key={rule}><div><strong>{rule.replace(/([A-Z])/g, " $1")}</strong><span>{item.details}</span>{item.matchedPreference && <small>Matched: {item.matchedPreference} · Delta: {item.scoreDelta}</small>}</div><b>{item.score}/{item.maximum}</b></div>)}</section>
            </div>
          </>
        ) : <div className="empty-detail"><CalendarDays size={34} /><h3>No schedule can satisfy the current input</h3><p>Return to the input screen to revise fixed sections, availability rules, meeting times, or empty section groups.</p></div>}
      </section>
    </main>
  );
}

function App() {
  const [stage, setStage] = useState<Stage>("input");
  const [courseCode, setCourseCode] = useState("");
  const [courseTitle, setCourseTitle] = useState("");
  const [sectionDrafts, setSectionDrafts] = useState<SectionDraft[]>([
    newSectionDraft(1)
  ]);
  const [nextSectionKey, setNextSectionKey] = useState(2);
  const [courses, setCourses] = useState<Course[]>([]);
  const [preferenceText, setPreferenceText] = useState("");
  const [preferences, setPreferences] = useState<ParsedPreferences | null>(null);
  const [response, setResponse] = useState<GenerateResponse | null>(null);
  const [courseError, setCourseError] = useState("");
  const [requestError, setRequestError] = useState("");
  const [loading, setLoading] = useState(false);
  const [imageLoading, setImageLoading] = useState(false);
  const [screenshots, setScreenshots] = useState<CourseScreenshot[]>([]);
  const [imageWarnings, setImageWarnings] = useState<string[]>([]);

  const canOpenResults = useMemo(() => response !== null, [response]);

  const addCourse = () => {
    try {
      const course = buildCourse(courseCode, courseTitle, sectionDrafts);
      if (courses.some((item) => item.code === course.code)) {
        throw new Error(`${course.code} has already been added.`);
      }
      setCourses((current) => [...current, course]);
      setCourseCode("");
      setCourseTitle("");
      setSectionDrafts([newSectionDraft(nextSectionKey)]);
      setNextSectionKey((current) => current + 1);
      setScreenshots([]);
      setImageWarnings([]);
      setCourseError("");
      setResponse(null);
    } catch (error) {
      setCourseError(error instanceof Error ? error.message : "Invalid course data.");
    }
  };

  const updateSection = (key: number, field: keyof SectionDraft, value: string) => {
    setSectionDrafts((current) => current.map((section) =>
      section.key === key ? { ...section, [field]: value } : section
    ));
    setCourseError("");
  };

  const addSection = () => {
    const usedLectureIds = new Set(
      sectionDrafts
        .filter((section) => section.type === "lecture")
        .map((section) => section.id.toUpperCase())
    );
    const nextId = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("").find(
      (id) => !usedLectureIds.has(id)
    ) ?? `A${nextSectionKey}`;
    setSectionDrafts((current) => [
      ...current,
      newSectionDraft(nextSectionKey, nextId)
    ]);
    setNextSectionKey((current) => current + 1);
  };

  const queueCourseImage = async (file: File) => {
    const supportedTypes = ["image/png", "image/jpeg", "image/webp"];
    if (!supportedTypes.includes(file.type)) {
      setCourseError("Upload a PNG, JPEG, or WebP image.");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setCourseError("The image must be 10 MB or smaller.");
      return;
    }

    setImageWarnings([]);
    setCourseError("");
    try {
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(new Error("The selected image could not be read."));
        reader.readAsDataURL(file);
      });
      setScreenshots((current) => [...current, { id: `${Date.now()}-${current.length}-${file.name}`, name: file.name, mediaType: file.type, dataUrl }]);
    } catch (error) {
      setCourseError(error instanceof Error ? error.message : "Could not add the image.");
    }
  };

  const extractCourseImages = async () => {
    if (!screenshots.length) return;
    setImageLoading(true);
    setImageWarnings([]);
    setCourseError("");
    try {
      const results = await Promise.all(screenshots.map((screenshot) => {
        const imageBase64 = screenshot.dataUrl.split(",", 2)[1];
        if (!imageBase64) throw new Error(`${screenshot.name} could not be read.`);
        return apiRequest<CourseImageExtraction>("/api/courses/extract-from-image", {
          imageBase64,
          mediaType: screenshot.mediaType,
          courseCodeHint: courseCode.trim() || null,
          courseTitleHint: courseTitle.trim() || null
        });
      }));
      const extractedCourses = results.flatMap((result) => result.courses);
      if (results.some((result) => result.courses.length !== 1)) {
        throw new Error("Each screenshot must contain exactly one course.");
      }
      const extractedCourse = mergeExtractedCourses(extractedCourses);
      setCourseCode(extractedCourse.code);
      setCourseTitle(extractedCourse.title ?? "");
      const drafts = courseToDrafts(extractedCourse);
      setSectionDrafts(drafts);
      setNextSectionKey(Math.max(0, ...drafts.map((draft) => draft.key)) + 1);
      setImageWarnings(results.flatMap((result, index) => result.warnings.map((warning) => `Screenshot ${index + 1}: ${warning}`)));
      setPreferences(null);
      setResponse(null);
      setRequestError("");
    } catch (error) {
      setCourseError(error instanceof Error ? error.message : "Could not extract courses from the screenshots.");
    } finally {
      setImageLoading(false);
    }
  };

  const saveCourse = (originalCode: string, updatedCourse: Course) => {
    if (courses.some((course) => course.code === updatedCourse.code && course.code !== originalCode)) {
      return `${updatedCourse.code} has already been added.`;
    }
    setCourses((current) => current.map((course) =>
      course.code === originalCode ? updatedCourse : course
    ));
    setPreferences(null);
    setResponse(null);
    setRequestError("");
    return null;
  };

  const interpretPreferences = async () => {
    if (!courses.length) {
      setRequestError("Add or load at least one course before continuing.");
      return;
    }
    if (!preferenceText.trim()) {
      setPreferences(defaultPreferences);
      setRequestError("");
      setStage("review");
      return;
    }
    setLoading(true);
    setRequestError("");
    try {
      const parsed = await apiRequest<ParsedPreferences>("/parse-preferences", {
        courses,
        preferenceText
      });
      setPreferences(parsed);
      setStage("review");
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : "Could not interpret preferences.");
    } finally {
      setLoading(false);
    }
  };

  const generateSchedules = async () => {
    if (!preferences) return;
    setLoading(true);
    setRequestError("");
    try {
      const generated = await apiRequest<GenerateResponse>("/api/schedules/generate", {
        courses,
        preferences,
        topN: 5,
        enhanceReasons: true
      });
      setResponse(generated);
      setStage("results");
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : "Could not generate schedules.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app">
      <TopBar />
      <div className="subnav">
        <button className={stage !== "results" ? "active" : ""} type="button" onClick={() => setStage("input")}>Courses &amp; Preferences</button>
        <button className={stage === "results" ? "active" : ""} type="button" disabled={!canOpenResults} onClick={() => setStage("results")}>Schedule Options</button>
        <Workflow stage={stage} />
      </div>
      {stage === "input" && <InputView
        courseCode={courseCode}
        courseTitle={courseTitle}
        sectionDrafts={sectionDrafts}
        courses={courses}
        preferenceText={preferenceText}
        courseError={courseError}
        requestError={requestError}
        loading={loading}
        imageLoading={imageLoading}
        screenshots={screenshots}
        imageWarnings={imageWarnings}
        onCourseCodeChange={(value) => { setCourseCode(value); setCourseError(""); }}
        onCourseTitleChange={(value) => { setCourseTitle(value); setCourseError(""); }}
        onSectionChange={updateSection}
        onAddSection={addSection}
        onRemoveSection={(key) => setSectionDrafts((current) => current.filter((section) => section.key !== key))}
        onAddCourse={addCourse}
        onRemoveCourse={(code) => { setCourses((current) => current.filter((course) => course.code !== code)); setResponse(null); }}
        onSaveCourse={saveCourse}
        onImageSelect={queueCourseImage}
        onRemoveImage={(id) => { setScreenshots((current) => current.filter((screenshot) => screenshot.id !== id)); setImageWarnings([]); }}
        onExtractImages={extractCourseImages}
        onPreferenceChange={setPreferenceText}
        onInterpret={interpretPreferences}
      />}
      {stage === "review" && preferences && <ReviewView preferences={preferences} loading={loading} error={requestError} onBack={() => setStage("input")} onGenerate={generateSchedules} />}
      {stage === "results" && response && <ResultsView response={response} onBack={() => setStage("input")} />}
    </div>
  );
}

export default App;
