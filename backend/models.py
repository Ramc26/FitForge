"""Request and response models. Every Pydantic model lives in this file."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Exercise(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    sets: int | None = None
    reps: str | None = None
    rest_seconds: int | None = None
    anatomy_pov: str | None = None
    form: str | None = None
    machine_alternative: str | None = None
    duration_minutes: int | None = None


class WorkoutDay(BaseModel):
    plan: str
    plan_label: str
    day: str
    date: str
    focus: str
    is_rest_day: bool
    notes: str = ""
    exercises: list[Exercise] = Field(default_factory=list)
    optional_exercises: list[Exercise] = Field(default_factory=list)
    finisher: Exercise | None = None
    exercise_count: int
    estimated_minutes: int
    coach_nudge: str


class PlanInfo(BaseModel):
    key: str
    label: str


class ScheduleResponse(BaseModel):
    plan: str
    plan_label: str
    plans: list[PlanInfo]
    days: list[WorkoutDay]


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    age: int | None = Field(default=None, ge=10, le=100)
    height_cm: float | None = Field(default=None, ge=80, le=250)
    weight_kg: float | None = Field(default=None, ge=25, le=400)
    goal: str | None = Field(default=None, max_length=240)
    equipment: list[str] | None = None
    preferences: str | None = Field(default=None, max_length=240)


class UserProfile(BaseModel):
    user_id: str
    name: str
    age: int | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    goal: str
    created_at: str | None = None
    updated_at: str | None = None
    saved: bool = False
    equipment: list[str] = Field(default_factory=list)
    equipment_rules: list[str] = Field(default_factory=list)
    preferences: str = ""


class WorkoutLogCreate(BaseModel):
    exercise_name: str = Field(min_length=1, max_length=120)
    set_number: int = Field(ge=1, le=30)
    weight_kg: float | None = Field(default=None, ge=0, le=500)
    reps: int | None = Field(default=None, ge=0, le=500)
    rpe: float | None = Field(default=None, ge=1, le=10)
    notes: str = Field(default="", max_length=500)
    date: str | None = None
    day_of_week: str | None = None


class WorkoutLog(BaseModel):
    log_id: str
    user_id: str
    date: str
    day_of_week: str
    exercise_name: str
    set_number: int
    weight_kg: float | None = None
    reps: int | None = None
    rpe: float | None = None
    notes: str = ""
    created_at: str


class SetEntry(BaseModel):
    set_number: int
    weight_kg: float | None = None
    reps: int | None = None
    rpe: float | None = None
    notes: str = ""


class SessionSummary(BaseModel):
    date: str
    day_of_week: str = ""
    sets: list[SetEntry]


class ExerciseHistory(BaseModel):
    exercise_name: str
    sessions: list[SessionSummary]
    pr: dict | None = None
    suggestion: str


class HistoryResponse(BaseModel):
    logs: list[WorkoutLog]
    recent_sessions: list[dict]


class ProgressCreate(BaseModel):
    date: str | None = None
    weight_kg: float | None = Field(default=None, ge=25, le=400)
    waist_cm: float | None = Field(default=None, ge=40, le=200)
    notes: str = Field(default="", max_length=500)


class ProgressEntry(BaseModel):
    progress_id: str
    user_id: str
    date: str
    weight_kg: float | None = None
    waist_cm: float | None = None
    notes: str = ""


class ProgressOverview(BaseModel):
    entries: list[ProgressEntry]
    current_weight_kg: float | None = None
    weight_delta_kg: float | None = None
    consistency: dict
    prs: list[dict]
    recent_sessions: list[dict]
    strength: list[dict]


class CoachContext(BaseModel):
    current_exercise: str | None = None
    current_day: str | None = None
    plan: str | None = None
    screen: str | None = None
    equipment: list[str] | None = None


class ChatTurn(BaseModel):
    role: str = Field(max_length=20)
    message: str = Field(max_length=2000)


class RecentSet(BaseModel):
    exercise_name: str = Field(max_length=120)
    set_number: int = Field(ge=1, le=20)
    weight_kg: float | None = None
    reps: int | None = None
    date: str | None = None
    day_of_week: str | None = None


class CoachRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=80)
    context: CoachContext | None = None
    recent_messages: list[ChatTurn] = Field(default_factory=list, max_length=5)
    recent_logs: list[RecentSet] = Field(default_factory=list, max_length=40)


class CoachMessage(BaseModel):
    message_id: str
    user_id: str
    conversation_id: str
    role: str
    message: str
    created_at: str


class CoachResponse(BaseModel):
    message: str
    intent: str
    clarification_needed: bool = False
    suggested_actions: list[str] = Field(default_factory=list)
    conversation_id: str


class HanuResponse(BaseModel):
    """Structured shape Hanu returns from the model and from normal code."""

    message: str
    intent: str
    clarification_needed: bool = False
    suggested_actions: list[str] = Field(default_factory=list)
    memory: str = ""
