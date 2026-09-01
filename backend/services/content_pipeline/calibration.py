from __future__ import annotations

from .prompts import load_prompt_file


def load_budget_rewrite_contract() -> str:
    return load_prompt_file("generation", "budget-rewrite.md")


def course_section_budget_defaults(
    course_number: int,
    target_words: int,
    parts_count: int,
    *,
    words_per_minute: float,
    is_last_day: bool,
    is_last_course: bool | None = None,
    total_courses: int | None = None,
) -> dict:
    """Split one course word budget into opening, parts, and conclusions."""
    target_words = max(900, int(target_words or 0))
    parts_count = max(2, min(4, int(parts_count or 3)))
    if is_last_course is None:
        is_last_course = int(course_number or 0) == 7
    single_course_day = int(total_courses or 0) == 1
    if single_course_day:
        opening = min(900, max(520, int(target_words * 0.11)))
        conclusion = min(260, max(180, int(target_words * 0.04)))
        day_conclusion = (
            min(80, max(45, int(round(float(words_per_minute or 0) * 0.3))))
            if is_last_course
            else 0
        )
    elif course_number == 1:
        opening = min(900, max(520, int(target_words * 0.11)))
        conclusion = min(780, max(560, int(target_words * 0.09)))
        day_conclusion = 0
    elif is_last_course:
        opening = min(520, max(300, int(target_words * 0.06)))
        day_conclusion = int(round(float(words_per_minute or 0) * 2.0))
        conclusion = min(650, max(430, int(target_words * 0.08)))
    else:
        opening = min(520, max(340, int(target_words * 0.07)))
        conclusion = min(700, max(520, int(target_words * 0.08)))
        day_conclusion = 0

    min_part_words = min(300, max(120, target_words // (parts_count + 3)))
    reserved = opening + conclusion + day_conclusion
    reserved_cap = min(int(target_words * 0.42), target_words - parts_count * min_part_words)
    if reserved > reserved_cap:
        scale = max(0.2, reserved_cap / max(1, reserved))
        if single_course_day:
            opening = max(220, int(opening * scale))
            conclusion = max(110, int(conclusion * scale))
            day_conclusion = (
                max(25, int(day_conclusion * scale))
                if day_conclusion
                else 0
            )
        else:
            opening = max(240, int(opening * scale))
            conclusion = max(320, int(conclusion * scale))
            day_conclusion = max(0, int(day_conclusion * scale))
        reserved = opening + conclusion + day_conclusion
    remaining = max(parts_count * min_part_words, target_words - reserved)
    if reserved + remaining > target_words:
        remaining = max(0, target_words - reserved)
    base = remaining // parts_count
    part_budgets = [base for _ in range(parts_count)]
    part_budgets[-1] += remaining - sum(part_budgets)
    return {
        "opening": int(opening),
        "parts": [int(v) for v in part_budgets],
        "course_conclusion": int(conclusion),
        "day_conclusion": int(day_conclusion),
    }


def structured_generation_max_tokens(target_words: int) -> int:
    return min(16000, max(1200, int(int(target_words or 600) * 2.4) + 700))
