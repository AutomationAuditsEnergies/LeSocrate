from pathlib import Path
import re


FUNCTION_APP = Path(__file__).resolve().parents[2] / "azure-function" / "function_app.py"


def test_reminders_are_not_triggered_by_the_azure_function():
    source = FUNCTION_APP.read_text(encoding="utf-8")

    auto_schedule_function = re.search(
        r'@app\.timer_trigger\(\s*schedule="0 \*/5 \* \* \* \*".*?'
        r'def course_automation_tick\(.*?\).*?'
        r'_call_backend_endpoint\("/api/internal/auto-schedule"\)',
        source,
        re.DOTALL,
    )

    assert auto_schedule_function
    assert "course_reminder_tick" not in source
    assert '"/api/internal/reminders/tick"' not in source
