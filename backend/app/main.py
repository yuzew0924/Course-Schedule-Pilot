from fastapi import Body, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .ai.client import AIClientError, get_ai_client
from .ai.course_image_parser import CourseImageParser
from .ai.preference_parser import PreferenceParser
from .ai.reason_writer import ReasonWriter
from .generation import generate_ranked_schedules
from .models import (
    GenerateSchedulesApiRequest,
    GenerateSchedulesApiResponse,
    ExtractCoursesFromImageRequest,
    ExtractCoursesFromImageResponse,
    ParsePreferencesRequest,
    ParsedPreferences,
)

app = FastAPI(
    title="Course Schedule Pilot API",
    description="Backend service for generating and ranking course schedules.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AIClientError)
async def handle_ai_client_error(
    request: Request,
    error: AIClientError,
) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {"code": error.code, "message": str(error)}},
    )


@app.get("/")
def read_root() -> dict[str, str]:
    return {
        "service": "Course Schedule Pilot API",
        "status": "ok",
    }


@app.get("/health")
def read_health() -> dict[str, str]:
    return {"status": "ok"}


def get_preference_parser() -> PreferenceParser:
    return PreferenceParser(get_ai_client())


def get_course_image_parser() -> CourseImageParser:
    return CourseImageParser(get_ai_client())


@app.post(
    "/api/courses/extract-from-image",
    response_model=ExtractCoursesFromImageResponse,
)
async def extract_courses_from_image(
    payload: ExtractCoursesFromImageRequest = Body(),
    parser: CourseImageParser = Depends(get_course_image_parser),
) -> ExtractCoursesFromImageResponse:
    """Extract validated, editable course sections from a schedule image."""
    return await parser.parse(
        payload.imageBase64,
        payload.mediaType,
        payload.courseCodeHint,
        payload.courseTitleHint,
    )


@app.post("/parse-preferences", response_model=ParsedPreferences)
async def parse_preferences(
    payload: ParsePreferencesRequest = Body(),
    parser: PreferenceParser = Depends(get_preference_parser),
) -> ParsedPreferences:
    """Parse natural language into validated, course-grounded preferences."""
    return await parser.parse(payload.preferenceText, payload.courses)


@app.post(
    "/api/schedules/generate",
    response_model=GenerateSchedulesApiResponse,
)
async def generate_schedules(
    payload: GenerateSchedulesApiRequest = Body(),
) -> GenerateSchedulesApiResponse:
    parser = get_preference_parser() if payload.preferenceText is not None else None
    reason_writer = None
    if payload.enhanceReasons:
        try:
            reason_writer = ReasonWriter(get_ai_client())
        except AIClientError:
            reason_writer = None
    return await generate_ranked_schedules(
        payload,
        parser=parser,
        reason_writer=reason_writer,
    )
