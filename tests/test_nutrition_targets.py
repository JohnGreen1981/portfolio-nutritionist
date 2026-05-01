from nutri_bot.nutrition import calc_targets
from nutri_bot.schemas import Profile


def _profile(goal: str = "maintain", weight_change_pct: float | None = None) -> Profile:
    return Profile(
        id=1,
        telegram_id=123456789,
        sex="m",
        birth_year=1990,
        height_cm=180,
        weight_kg=80,
        body_type="medium",
        activity_level="moderate",
        goal=goal,
        meal_regime="3x",
        timezone="Europe/Belgrade",
        weight_change_pct=weight_change_pct,
        onboarding_status="done",
    )


def test_calc_targets_returns_positive_macros():
    kcal, prot, fat, carb = calc_targets(_profile())

    assert kcal > 0
    assert prot > 0
    assert fat > 0
    assert carb > 0


def test_weight_change_pct_overrides_goal_factor():
    baseline, *_ = calc_targets(_profile(goal="maintain"))
    reduced, *_ = calc_targets(_profile(goal="maintain", weight_change_pct=0.85))

    assert reduced < baseline
