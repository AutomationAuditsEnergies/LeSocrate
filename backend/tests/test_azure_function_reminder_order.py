from pathlib import Path
import re


FUNCTION_APP = Path(__file__).resolve().parents[2] / "azure-function" / "function_app.py"


def test_reminders_have_an_independent_every_minute_trigger():
    source = FUNCTION_APP.read_text(encoding="utf-8")

    reminder_function = re.search(
        r'@app\.timer_trigger\(\s*schedule="0 \* \* \* \* \*".*?'
        r'def course_reminder_tick\(.*?\).*?'
        r'_call_backend_endpoint\("/api/internal/reminders/tick"\)',
        source,
        re.DOTALL,
    )
    auto_schedule_function = re.search(
        r'@app\.timer_trigger\(\s*schedule="0 \*/5 \* \* \* \*".*?'
        r'def course_automation_tick\(.*?\).*?'
        r'_call_backend_endpoint\("/api/internal/auto-schedule"\)',
        source,
        re.DOTALL,
    )

    assert reminder_function
    assert auto_schedule_function
