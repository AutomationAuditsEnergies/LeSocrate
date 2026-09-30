import unittest
from unittest.mock import patch

from repositories import hr_read_repository as repo


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=()):
        self.executions.append((query, params))

    def fetchall(self):
        return self.rows


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class _FakeConnectionContext:
    def __init__(self, cursor):
        self._connection = _FakeConnection(cursor)

    def __enter__(self):
        return self._connection

    def __exit__(self, *_args):
        return False


class HrReadRepositoryTest(unittest.TestCase):
    def test_modules_are_tenant_scoped_and_schedule_configs_are_batch_loaded(self):
        cursor = _FakeCursor([{
            "id": 8,
            "rncp_code": "RNCP37099",
            "tp_name": "Employé commercial",
            "version": "v2",
            "status": "validated",
            "source_pipeline_job_id": 71,
            "source_platform_id": 12,
            "created_at": "2026-07-10 08:00:00",
            "nb_folders": 4,
            "source_platform_name": "Promo juillet",
            "voice_type": "azure",
            "voice_updated_at": None,
        }])
        with patch.object(
            repo,
            "get_postgres_connection",
            return_value=_FakeConnectionContext(cursor),
        ), patch.object(
            repo,
            "list_postgres_course_schedule_configs",
            return_value={
                12: {
                    "total_training_days": 4,
                    "weekly_course_count": 2,
                    "weekdays_json": "[1, 3]",
                    "start_time": "09:00",
                },
            },
        ) as list_schedules:
            rows = repo.list_formation_modules(42, scope_to_center=True)

        query, params = cursor.executions[0]
        self.assertIn("m.center_account_id = %s", query)
        self.assertEqual(params, (42,))
        list_schedules.assert_called_once_with([12])
        self.assertEqual(rows[0]["schedule"]["weekdays"], [1, 3])

    def test_tenant_scope_fails_closed_when_session_has_no_center_id(self):
        cursor = _FakeCursor([])
        with patch.object(
            repo,
            "get_postgres_connection",
            return_value=_FakeConnectionContext(cursor),
        ):
            rows = repo.list_platforms(None, scope_to_center=True)

        query, params = cursor.executions[0]
        self.assertEqual(rows, [])
        self.assertIn("AND FALSE", query)
        self.assertEqual(params, ())


if __name__ == "__main__":
    unittest.main()
