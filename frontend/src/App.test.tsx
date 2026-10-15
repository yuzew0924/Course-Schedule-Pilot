import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

function defaultParsedPreferences() {
  return {
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
}

function mockApiResponse(payload: object) {
  return vi.fn().mockImplementation((_input: string, init?: RequestInit) =>
    Promise.resolve(
      new Response(
        JSON.stringify(init?.method ? payload : { status: "ok" }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    )
  );
}

function setMeeting(section: number, days = "MWF") {
  fireEvent.change(screen.getByLabelText(`Section ${section} days`), { target: { value: days } });
  fireEvent.change(screen.getByLabelText(`Section ${section} start time hour`), { target: { value: "9" } });
  fireEvent.change(screen.getByLabelText(`Section ${section} start time minute`), { target: { value: "30" } });
  fireEvent.change(screen.getByLabelText(`Section ${section} end time hour`), { target: { value: "10" } });
  fireEvent.change(screen.getByLabelText(`Section ${section} end time minute`), { target: { value: "20" } });
}

function addBasicCourse(code = "CSE 373") {
  fireEvent.change(screen.getByLabelText("Course code"), { target: { value: code } });
  fireEvent.click(screen.getByRole("button", { name: "Add section time" }));
  fireEvent.change(screen.getByLabelText("Section 1 ID"), { target: { value: "A" } });
  setMeeting(1);
  fireEvent.click(screen.getByRole("button", { name: "Add course" }));
}

function addEditableCourse() {
  fireEvent.change(screen.getByLabelText("Course code"), { target: { value: "CSE 373" } });
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Data Structures and Algorithms" } });
  fireEvent.click(screen.getByRole("button", { name: "Add section time" }));
  fireEvent.change(screen.getByLabelText("Section 1 ID"), { target: { value: "A" } });
  setMeeting(1);
  fireEvent.click(screen.getByRole("button", { name: "Add section time" }));
  fireEvent.change(screen.getByLabelText("Section 2 ID"), { target: { value: "B" } });
  setMeeting(2);
  fireEvent.click(screen.getByRole("button", { name: "Add section time" }));
  fireEvent.change(screen.getByLabelText("Section 3 type"), { target: { value: "quiz" } });
  fireEvent.change(screen.getByLabelText("Section 3 ID"), { target: { value: "AA" } });
  setMeeting(3, "Th");
  fireEvent.click(screen.getByRole("button", { name: "Add course" }));
}

describe("App", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("renders the project name and backend status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        })
      )
    );

    render(<App />);

    expect(screen.getByRole("heading", { name: "Course Schedule Pilot" })).toBeInTheDocument();
    expect(screen.getByLabelText("Describe your ideal schedule")).toHaveValue("");
    expect(screen.queryByRole("button", { name: "Load sample data" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Section 1 days")).not.toBeInTheDocument();
    expect(screen.queryByText("Type")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add section time" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Checking backend");
    expect(await screen.findByText("Backend online")).toBeInTheDocument();
  });

  it("adds a course from section rows and groups its components", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        })
      )
    );
    render(<App />);

    fireEvent.change(screen.getByLabelText("Course code"), {
      target: { value: "CSE 414" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Add section time" }));
    expect(screen.getByLabelText("Section 1 ID")).toHaveValue("");
    expect(screen.getByLabelText("Section 1 ID")).toHaveAttribute("placeholder", "A");
    expect(screen.getByLabelText("Section 1 start time hour")).toHaveClass("placeholder-value");
    expect(screen.getByText("Type")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Section 1 ID"), { target: { value: "A" } });
    setMeeting(1);
    fireEvent.click(screen.getByRole("button", { name: "Add section time" }));
    fireEvent.change(screen.getByLabelText("Section 2 type"), {
      target: { value: "quiz" }
    });
    fireEvent.change(screen.getByLabelText("Section 2 ID"), {
      target: { value: "AA" }
    });
    setMeeting(2, "Th");
    fireEvent.click(screen.getByRole("button", { name: "Add course" }));

    expect(await screen.findByText("CSE 414")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "lecture" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "quiz" })).toBeInTheDocument();
    expect(screen.getByText("Linked to Lecture A")).toBeInTheDocument();
  });

  it("queues multiple course screenshots and extracts only after manual confirmation", async () => {
    const fetchMock = vi.fn().mockImplementation((input: string, init?: RequestInit) => {
      if (!init?.method) {
        return Promise.resolve(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
      }
      expect(input).toMatch(/\/api\/courses\/extract-from-image$/);
      return Promise.resolve(new Response(JSON.stringify({
        courses: [{
          code: "CSE 414",
          title: "Database Systems",
          groups: [
            { type: "lecture", choose: 1, sections: [{ id: "A", status: "open", sln: "12345", meetings: [{ days: ["M", "W", "F"], startTime: "09:30", endTime: "10:20", location: "KNE 120" }] }] },
            { type: "quiz", choose: 1, sections: [{ id: "AA", status: "open", sln: "12346", parentSectionId: "A", meetings: [{ days: ["Th"], startTime: "12:30", endTime: "13:20", location: "LOW 101" }] }] }
          ]
        }],
        warnings: ["Verify the room number."]
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    const firstFile = new File(["image-one"], "lectures.png", { type: "image/png" });
    const secondFile = new File(["image-two"], "quizzes.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText(/Choose image/), { target: { files: [firstFile, secondFile] } });

    expect(await screen.findByAltText("Course screenshot preview 1")).toBeInTheDocument();
    expect(screen.getByAltText("Course screenshot preview 2")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Enter course code to extract" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter the course code before extracting");

    fireEvent.change(screen.getByLabelText("Course code"), { target: { value: "CSE 414" } });
    fireEvent.click(screen.getByRole("button", { name: "Extract sections from 2 screenshots" }));

    expect(await screen.findByDisplayValue("CSE 414")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("group", { name: "Section 1 start time" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Section 2 start time period" })).toHaveValue("PM");
    expect(screen.getAllByText(/Verify the room number\./)).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Add course" }));

    expect(await screen.findByText("CSE 414")).toBeInTheDocument();
    expect(screen.getByText("Linked to Lecture A")).toBeInTheDocument();
    expect(screen.getByText("Th · 12:30 PM–1:20 PM")).toBeInTheDocument();
    expect(screen.queryByAltText(/Course screenshot preview/)).not.toBeInTheDocument();
  });

  it("accepts a pasted screenshot without parsing it automatically", async () => {
    const fetchMock = vi.fn().mockImplementation((_input: string, init?: RequestInit) => {
      if (!init?.method) return Promise.resolve(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify({
        courses: [{ code: "MATH 208", title: "Linear Algebra", groups: [{ type: "lecture", choose: 1, sections: [{ id: "A", status: "open", meetings: [{ days: ["M", "W", "F"], startTime: "10:30", endTime: "11:20", location: "KNE 110" }] }] }] }],
        warnings: []
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    const pastedImage = new File(["image"], "clipboard.png", { type: "image/png" });
    fireEvent.paste(screen.getByLabelText("Course screenshot paste area"), {
      clipboardData: { files: [pastedImage] }
    });

    expect(await screen.findByAltText("Course screenshot preview 1")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Enter course code to extract" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter the course code before extracting");
    fireEvent.change(screen.getByLabelText("Course code"), { target: { value: "MATH 208" } });
    fireEvent.click(screen.getByRole("button", { name: "Extract sections from 1 screenshot" }));
    expect(await screen.findByDisplayValue("MATH 208")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Section 1 start time hour" })).toHaveValue("10");
    expect(screen.getByRole("combobox", { name: "Section 1 start time period" })).toHaveValue("AM");
  });

  it("uses safe defaults when preference text is blank", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    addBasicCourse();
    fireEvent.change(screen.getByLabelText("Describe your ideal schedule"), {
      target: { value: "   " }
    });
    fireEvent.click(screen.getByRole("button", { name: /Interpret preferences/ }));

    expect(await screen.findByRole("heading", { name: "Confirm your schedule requirements" })).toBeInTheDocument();
    expect(screen.getByText("Open sections only")).toBeInTheDocument();
    expect(screen.getByText("No soft preferences")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows a clear error for invalid section days", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        })
      )
    );
    render(<App />);

    fireEvent.change(screen.getByLabelText("Course code"), { target: { value: "CSE 414" } });
    fireEvent.click(screen.getByRole("button", { name: "Add section time" }));
    fireEvent.change(screen.getByLabelText("Section 1 ID"), { target: { value: "A" } });
    setMeeting(1);
    fireEvent.change(screen.getByLabelText("Section 1 days"), { target: { value: "Sunday" } });
    fireEvent.click(screen.getByRole("button", { name: "Add course" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Use weekday codes");
    expect(screen.queryByText("Added courses")).not.toBeInTheDocument();
  });

  it("supports the parse, confirm, generate, and option review flow", async () => {
    const parsedPreferences = {
      earliestStart: "10:00",
      earliestStartIsHard: false,
      preferredDaysOff: ["F"],
      requiredDaysOff: [],
      preferredTimeOfDay: "afternoon",
      gapPreference: "compact",
      fixedSections: [],
      requireOpenSections: true,
      hardConstraints: [],
      softPreferences: ["Prefer compact schedules"],
      conflicts: [],
      needsClarification: false,
      clarificationQuestions: []
    };
    const fetchMock = vi.fn().mockImplementation((input: string, init?: RequestInit) => {
      if (!init?.method) {
        return Promise.resolve(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
      }
      if (input.endsWith("/parse-preferences")) {
        return Promise.resolve(new Response(JSON.stringify(parsedPreferences), { status: 200 }));
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({
            interpretedPreferences: parsedPreferences,
            count: 1,
            warnings: [],
            schedules: [
              {
                rank: 1,
                score: 87,
                sections: [
                  {
                    courseCode: "CSE 373",
                    groupType: "lecture",
                    sectionId: "B",
                    status: "open",
                    sln: null,
                    meetings: [
                      { days: ["M", "W"], startTime: "13:30", endTime: "14:20" }
                    ]
                  }
                ],
                scoreBreakdown: {
                  earliestStart: { score: 25, maximum: 25, details: "Starts later", affectedSections: [] },
                  preferredTimeOfDay: { score: 20, maximum: 20, details: "Afternoon", affectedSections: [] },
                  gaps: {
                    score: 23,
                    maximum: 30,
                    scoreDelta: -7,
                    matchedPreference: "compact",
                    details: "One 70-minute gap",
                    reasonCandidate: null,
                    tradeoffCandidate: "One gap is at least 30 minutes",
                    affectedSections: ["CSE 373 B"],
                    affectedMeetings: []
                  },
                  preferredDaysOff: { score: 19, maximum: 25, details: "Friday free", affectedSections: [] }
                },
                reasons: ["Classes are concentrated in the afternoon"],
                tradeoffs: []
              }
            ]
          }),
          { status: 200 }
        )
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    addBasicCourse();
    fireEvent.change(screen.getByLabelText("Describe your ideal schedule"), { target: { value: "Prefer afternoon classes" } });
    fireEvent.click(screen.getByRole("button", { name: /Interpret preferences/ }));

    expect(await screen.findByRole("heading", { name: "Confirm your schedule requirements" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Confirm and generate/ }));

    expect(await screen.findByRole("heading", { name: "Weekly schedule" })).toBeInTheDocument();
    expect(screen.getByText("1 ranked schedules")).toBeInTheDocument();
    expect(screen.getAllByText("CSE 373 B")).toHaveLength(2);
    expect(screen.getByText("Matched: compact · Delta: -7")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  });

  it("shows hard conflicts, blocks generation, and preserves text for revision", async () => {
    const conflictPreferences = {
      ...defaultParsedPreferences(),
      conflicts: ["CSE 373 A conflicts with the required Friday off"],
      needsClarification: true,
      clarificationQuestions: ["Should the fixed section override Friday off?"]
    };
    vi.stubGlobal("fetch", mockApiResponse(conflictPreferences));
    render(<App />);

    addBasicCourse();
    fireEvent.change(screen.getByLabelText("Describe your ideal schedule"), {
      target: { value: "Keep Friday free and require CSE 373 A" }
    });
    fireEvent.click(screen.getByRole("button", { name: /Interpret preferences/ }));

    expect(await screen.findByText("Hard-constraint conflicts")).toBeInTheDocument();
    expect(screen.getByText(/CSE 373 A conflicts/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Confirm and generate/ })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Revise preferences" }));
    expect(screen.getByLabelText("Describe your ideal schedule")).toHaveValue(
      "Keep Friday free and require CSE 373 A"
    );
  });

  it("renders FastAPI validation details and AI parsing failures", async () => {
    const fetchMock = vi.fn().mockImplementation((input: string, init?: RequestInit) => {
      if (!init?.method) return Promise.resolve(new Response('{"status":"ok"}', { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify({ detail: [{ loc: ["body", "courses", 0, "code"], msg: "Field required" }] }), { status: 422 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    addBasicCourse();
    fireEvent.change(screen.getByLabelText("Describe your ideal schedule"), { target: { value: "Prefer later classes" } });
    fireEvent.click(screen.getByRole("button", { name: /Interpret preferences/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("courses.0.code: Field required");

    cleanup();
    vi.stubGlobal("fetch", vi.fn().mockImplementation((input: string, init?: RequestInit) => {
      if (!init?.method) return Promise.resolve(new Response('{"status":"ok"}', { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify({ error: { message: "AI preference parsing timed out" } }), { status: 504 }));
    }));
    render(<App />);
    addBasicCourse();
    fireEvent.change(screen.getByLabelText("Describe your ideal schedule"), { target: { value: "Prefer later classes" } });
    fireEvent.click(screen.getByRole("button", { name: /Interpret preferences/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("AI preference parsing timed out");
  });

  it("shows a specific backend-unavailable message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    render(<App />);
    addBasicCourse();
    fireEvent.change(screen.getByLabelText("Describe your ideal schedule"), { target: { value: "Prefer later classes" } });
    fireEvent.click(screen.getByRole("button", { name: /Interpret preferences/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Backend unavailable at");
    expect(screen.getByRole("status")).toHaveTextContent("Backend unavailable");
  });

  it("shows every no-result diagnostic and a recovery action", async () => {
    const fetchMock = vi.fn().mockImplementation((_input: string, init?: RequestInit) => {
      if (!init?.method) return Promise.resolve(new Response('{"status":"ok"}', { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify({
        interpretedPreferences: defaultParsedPreferences(),
        schedules: [],
        count: 0,
        warnings: [
          "CSE 373 quiz group has no open sections while open-only is enabled.",
          "All remaining combinations have meeting conflicts."
        ]
      }), { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    addBasicCourse();
    fireEvent.change(screen.getByLabelText("Describe your ideal schedule"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /Interpret preferences/ }));
    fireEvent.click(screen.getByRole("button", { name: /Confirm and generate/ }));

    expect(await screen.findByRole("heading", { name: "No legal schedules" })).toBeInTheDocument();
    expect(screen.getByText(/quiz group has no open sections/)).toBeInTheDocument();
    expect(screen.getByText(/All remaining combinations/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Edit courses/ })).toBeInTheDocument();
  });

  it("supports lecture and lab groups without inventing other components", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok" }), { status: 200 }))
    );
    render(<App />);

    fireEvent.change(screen.getByLabelText("Course code"), {
      target: { value: "CHEM 142" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Add section time" }));
    fireEvent.change(screen.getByLabelText("Section 1 ID"), { target: { value: "A" } });
    setMeeting(1);
    fireEvent.click(screen.getByRole("button", { name: "Add section time" }));
    fireEvent.change(screen.getByLabelText("Section 2 type"), {
      target: { value: "lab" }
    });
    fireEvent.change(screen.getByLabelText("Section 2 ID"), {
      target: { value: "AL" }
    });
    setMeeting(2);
    fireEvent.click(screen.getByRole("button", { name: "Add course" }));

    expect(await screen.findByText("CHEM 142")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "lecture" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "lab" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "quiz" })).not.toBeInTheDocument();
  });

  it("edits course and section metadata, then validates linked lectures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok" }), { status: 200 }))
    );
    render(<App />);
    addEditableCourse();
    fireEvent.click(screen.getByRole("button", { name: "Edit CSE 373" }));

    fireEvent.change(screen.getAllByLabelText("Course code").at(-1)!, { target: { value: "CSE 374" } });
    fireEvent.change(screen.getAllByLabelText("Title").at(-1)!, { target: { value: "Intermediate Programming" } });
    const statuses = screen.getAllByLabelText("Status");
    fireEvent.change(statuses[0], { target: { value: "closed" } });
    fireEvent.change(screen.getAllByLabelText("SLN")[0], { target: { value: "99999" } });
    fireEvent.change(screen.getAllByLabelText("Location")[0], { target: { value: "MEB 238" } });
    const linkedParents = screen.getAllByLabelText("Parent lecture").filter(
      (input) => !(input as HTMLInputElement).disabled
    );
    fireEvent.change(linkedParents[0], { target: { value: "B" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText("CSE 374")).toBeInTheDocument();
    expect(screen.getByText("Intermediate Programming")).toBeInTheDocument();
    expect(screen.getByText("SLN 99999")).toBeInTheDocument();
    expect(screen.getByText("MEB 238")).toBeInTheDocument();
    expect(screen.getByText("Linked to Lecture B")).toBeInTheDocument();
    expect(screen.getAllByText("closed").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Edit CSE 374" }));
    const editedParents = screen.getAllByLabelText("Parent lecture").filter(
      (input) => !(input as HTMLInputElement).disabled
    );
    fireEvent.change(editedParents[0], { target: { value: "Z" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("must link to an existing lecture");
  });
});
