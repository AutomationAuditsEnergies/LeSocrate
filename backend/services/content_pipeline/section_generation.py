from __future__ import annotations

from .prompts import load_prompt_file


def load_section_prompt_parts() -> dict:
    return {
        "base_style": load_prompt_file("generation", "base-course-style.md"),
        "section_contract": load_prompt_file("generation", "structured-section.md"),
    }

