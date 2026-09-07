from __future__ import annotations


def validate_structured_course_plan(plan: dict, *, expected_courses: int = 7) -> dict:
    errors = []
    warnings = []
    courses = plan.get("courses") if isinstance(plan, dict) else None
    if not isinstance(courses, list):
        errors.append("courses_absent_or_not_list")
        courses = []
    if len(courses) != expected_courses:
        errors.append(f"courses_count_{len(courses)}")

    is_first_day = int(plan.get("day_number") or 0) == 1
    for expected_number in range(1, expected_courses + 1):
        course = next(
            (item for item in courses if int(item.get("course_number") or 0) == expected_number),
            None,
        )
        if not course:
            errors.append(f"course_{expected_number}_missing")
            continue
        parts = course.get("parts") if isinstance(course.get("parts"), list) else []
        if not 2 <= len(parts) <= 4:
            errors.append(f"course_{expected_number}_parts_count_{len(parts)}")
        course_anchor_count = 0
        for idx, part in enumerate(parts, start=1):
            beats = part.get("teaching_beats") if isinstance(part.get("teaching_beats"), list) else []
            if not beats:
                warnings.append(f"course_{expected_number}_part_{idx}_teaching_beats_missing")
                continue
            for beat in beats:
                anchor = beat.get("slide_anchor") if isinstance(beat, dict) and isinstance(beat.get("slide_anchor"), dict) else {}
                if anchor.get("enabled"):
                    course_anchor_count += 1
                    if not anchor.get("template_type"):
                        warnings.append(f"course_{expected_number}_part_{idx}_slide_anchor_template_missing")
        if course_anchor_count == 0:
            warnings.append(f"course_{expected_number}_slide_anchors_missing")
        expected_budget = int(course.get("target_words") or 0)
        section_budget = int((course.get("opening") or {}).get("target_words") or 0)
        section_budget += sum(int((part or {}).get("target_words") or 0) for part in parts)
        section_budget += int((course.get("course_conclusion") or {}).get("target_words") or 0)
        section_budget += int((course.get("day_conclusion") or {}).get("target_words") or 0)
        if expected_budget and section_budget != expected_budget:
            errors.append(
                f"course_{expected_number}_budget_sum_{section_budget}_expected_{expected_budget}"
            )
        if expected_number == expected_courses and not course.get("day_conclusion"):
            errors.append(f"course_{expected_courses}_day_conclusion_missing")
        if expected_number == 1 and not is_first_day:
            opening_terms = " ".join((course.get("opening") or {}).get("must_include") or []).lower()
            if "programme annuel" in opening_terms or "parcours annuel" in opening_terms:
                warnings.append("course_1_non_first_day_mentions_annual_program")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "courses_count": len(courses),
        "slide_anchors_count": sum(
            1
            for course in courses
            for part in (course.get("parts") if isinstance(course.get("parts"), list) else [])
            for beat in (part.get("teaching_beats") if isinstance(part.get("teaching_beats"), list) else [])
            if isinstance(beat, dict)
            and isinstance(beat.get("slide_anchor"), dict)
            and beat["slide_anchor"].get("enabled")
        ),
    }
