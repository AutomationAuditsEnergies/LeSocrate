from __future__ import annotations

from .prompts import load_prompt_file


def load_planning_prompt_parts() -> dict:
    return {
        "base_style": load_prompt_file("generation", "base-course-style.md"),
        "plan_contract": load_prompt_file("generation", "structured-plan.md"),
    }

