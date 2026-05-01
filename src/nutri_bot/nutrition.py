from __future__ import annotations

from datetime import date

from .schemas import Profile

ACTIVITY_COEFF = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "high": 1.725,
    "very_high": 1.9,
}

GOAL_FACTOR = {"lose": 0.85, "maintain": 1.0, "gain": 1.10}

MACRO_SPLIT = {
    "lose":     {"prot": 0.25, "fat": 0.30, "carb": 0.45},
    "maintain": {"prot": 0.20, "fat": 0.30, "carb": 0.50},
    "gain":     {"prot": 0.25, "fat": 0.25, "carb": 0.50},
}


def calc_targets(p: Profile) -> tuple[int, int, int, int]:
    """Returns (target_kcal, prot_g, fat_g, carb_g)."""
    age = date.today().year - p.birth_year
    if p.sex == "m":
        bmr = 10 * p.weight_kg + 6.25 * p.height_cm - 5 * age + 5
    else:
        bmr = 10 * p.weight_kg + 6.25 * p.height_cm - 5 * age - 161

    tdee = bmr * ACTIVITY_COEFF[p.activity_level]
    factor = p.weight_change_pct if p.weight_change_pct is not None else GOAL_FACTOR[p.goal]
    target_kcal = round(tdee * factor)

    split = MACRO_SPLIT[p.goal]
    prot_g = round(target_kcal * split["prot"] / 4)
    fat_g  = round(target_kcal * split["fat"]  / 9)
    carb_g = round(target_kcal * split["carb"] / 4)

    return target_kcal, prot_g, fat_g, carb_g
