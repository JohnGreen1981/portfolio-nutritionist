from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ── LLM контракты ────────────────────────────────────────────────────────────

class Candidate(BaseModel):
    dish: str
    grams: int
    confidence: float = Field(ge=0, le=1)


class FoodItem(BaseModel):
    dish: str
    grams: int


class VisionResult(BaseModel):
    items: list[FoodItem] = Field(max_length=5)


class ParsedV(BaseModel):
    dish: str
    grams: int
    time: str | None = None   # "HH:MM" или None


class Macros(BaseModel):
    dish: str
    kcal: float
    prot: float
    fat: float
    carb: float


# ── Профиль ──────────────────────────────────────────────────────────────────

Sex = Literal["m", "f"]
Goal = Literal["lose", "maintain", "gain"]
ActivityLevel = Literal["sedentary", "light", "moderate", "high", "very_high"]
BodyType = Literal["slim", "medium", "solid"]
MealRegime = Literal["3x", "4_5x", "intermittent", "irregular"]
OnboardingStatus = Literal["pending", "in_progress", "done"]

ACTIVITY_LABELS: dict[str, str] = {
    "sedentary": "Сидячий",
    "light": "Лёгкий",
    "moderate": "Умеренный",
    "high": "Высокий",
    "very_high": "Очень высокий",
}

GOAL_LABELS: dict[str, str] = {
    "lose": "Снижение веса",
    "maintain": "Удержание",
    "gain": "Набор массы",
}

MEAL_REGIME_LABELS: dict[str, str] = {
    "3x": "3 раза в день",
    "4_5x": "4–5 раз в день",
    "intermittent": "Интервальное (16/8)",
    "irregular": "Нерегулярно",
}

BODY_TYPE_LABELS: dict[str, str] = {
    "slim": "Худощавое",
    "medium": "Среднее",
    "solid": "Плотное",
}

SEX_LABELS: dict[str, str] = {
    "m": "Мужской",
    "f": "Женский",
}


class Profile(BaseModel):
    id: int
    telegram_id: int
    first_name: str | None = None
    username: str | None = None
    locale: str | None = None

    sex: Sex | None = None
    birth_year: int | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    body_type: BodyType | None = None
    activity_level: ActivityLevel | None = None
    goal: Goal | None = None
    target_weight_kg: float | None = None
    meal_regime: MealRegime | None = None
    timezone: str | None = None
    allergies: str | None = None
    diet_restrictions: list[str] = Field(default_factory=list)
    foods_liked: str | None = None
    foods_disliked: str | None = None

    target_kcal: int | None = None
    target_prot_g: int | None = None
    target_fat_g: int | None = None
    target_carb_g: int | None = None
    weight_change_pct: float | None = None

    onboarding_status: OnboardingStatus = "pending"
    onboarding_step: str | None = None
    onboarded_at: datetime | None = None
    disclaimer_accepted_at: datetime | None = None
    last_weight_nudge_at: datetime | None = None


# ── Приёмы пищи ──────────────────────────────────────────────────────────────

class MealRecord(BaseModel):
    id: int
    chat_id: int
    dish: str
    grams: float
    kcal: float
    prot: float
    fat: float
    carb: float
    eaten_at: datetime
    deleted: bool = False


class MealDraft(BaseModel):
    id: int
    chat_id: int
    message_id: int
    photo_file_id: str | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    grams_pred: float | None = None
    chosen_name: str | None = None
    status: str = "await_dish"
