import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from flask import Flask

from repositories import pipeline_repository
from routes import admin_routes


class _SocketIOStub:
    def __init__(self):
        self.emit = Mock()

    def start_background_task(self, *args, **kwargs):
        raise AssertionError("background side effect must not run")


class AdminTenantScopeRouteTest(unittest.TestCase):
    def setUp(self):
        db_file = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.db_path = db_file.name
        db_file.close()
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE platform_config (
                id INTEGER PRIMARY KEY,
                center_account_id INTEGER,
                upload_locked INTEGER DEFAULT 0,
                updated_at TEXT
            );
            INSERT INTO platform_config (id, center_account_id) VALUES (1, 10);
            INSERT INTO platform_config (id, center_account_id) VALUES (2, 20);
            """
        )
        conn.commit()
        conn.close()

        self.socketio = _SocketIOStub()
        app = Flask(__name__)
        app.secret_key = "admin-tenant-scope"
        app.register_blueprint(admin_routes.create_admin_blueprint(self.socketio))
        self.client = app.test_client()

    def tearDown(self):
        os.unlink(self.db_path)

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _login(self, *, account_type="training_center", account_id=10, platform_id=None):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["is_admin"] = True
            if account_type is not None:
                sess["admin_account_type"] = account_type
            if account_id is not None:
                sess["admin_account_id"] = account_id
            if platform_id is not None:
                sess["platform_id"] = platform_id

    def _assert_hidden(self, response):
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json(),
            {"success": False, "error": "Ressource introuvable"},
        )

    def test_center_a_can_read_its_platform_and_center_b_cannot(self):
        course_time = datetime(2026, 7, 10, 9, 0, 0)
        with patch.object(pipeline_repository, "get_db_connection", side_effect=self._connect), patch.object(
            admin_routes,
            "get_heure_debut_cours",
            return_value=course_time,
        ) as get_time:
            self._login(account_id=10)
            allowed = self.client.get(
                "/api/admin/course-time",
                headers={"X-Platform-Id": "1"},
            )
            self._login(account_id=20)
            hidden = self.client.get(
                "/api/admin/course-time",
                headers={"X-Platform-Id": "1"},
            )

        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.get_json()["date_cours"], "2026-07-10")
        self._assert_hidden(hidden)
        get_time.assert_called_once_with(1)

    def test_forged_header_is_blocked_before_log_student_and_simulation_side_effects(self):
        self._login(account_id=10, platform_id=1)
        simulated_offsets = {1: "owned-state"}

        with patch.object(
            pipeline_repository,
            "get_db_connection",
            side_effect=self._connect,
        ) as get_connection, patch.object(
            admin_routes,
            "get_heure_debut_cours",
        ) as get_time, patch.object(
            admin_routes.http_requests,
            "post",
        ) as supabase_create, patch.object(
            admin_routes.state,
            "simulated_time_offsets",
            simulated_offsets,
        ):
            responses = [
                self.client.get("/api/admin/logs", headers={"X-Platform-Id": "2"}),
                self.client.get("/api/admin/student-accounts", headers={"X-Platform-Id": "2"}),
                self.client.post(
                    "/api/admin/student-accounts",
                    headers={"X-Platform-Id": "2"},
                    json={
                        "email": "foreign@example.test",
                        "password": "strong-password",
                        "nom": "Foreign",
                        "prenom": "Student",
                    },
                ),
                self.client.put(
                    "/api/admin/student-accounts/999",
                    headers={"X-Platform-Id": "2"},
                    json={"is_active": False},
                ),
                self.client.post(
                    "/api/admin/simulate-current-time",
                    headers={"X-Platform-Id": "2"},
                    json={"simulated_current_time": "2026-07-10T11:00:00"},
                ),
                self.client.post(
                    "/api/admin/reset-simulation",
                    headers={"X-Platform-Id": "2"},
                ),
                self.client.post(
                    "/api/admin/force-logout-finished-users",
                    headers={"X-Platform-Id": "2"},
                ),
            ]

        for response in responses:
            self._assert_hidden(response)
        # Exactly one ownership lookup per rejected request; no route-level DB
        # read or mutation was reached.
        self.assertEqual(get_connection.call_count, len(responses))
        get_time.assert_not_called()
        supabase_create.assert_not_called()
        self.socketio.emit.assert_not_called()
        self.assertEqual(simulated_offsets, {1: "owned-state"})

    def test_ai_order_body_platform_is_scoped_even_when_header_is_owned(self):
        self._login(account_id=10)
        with patch.object(pipeline_repository, "get_db_connection", side_effect=self._connect), patch.object(
            admin_routes,
            "postgres_enabled",
            return_value=True,
        ), patch.object(admin_routes, "create_ai_teacher_order") as create_order:
            response = self.client.post(
                "/api/admin/ai-teacher-orders",
                headers={"X-Platform-Id": "1"},
                json={
                    "platform_id": 2,
                    "training_title": "Formation étrangère",
                    "total_hours": 14,
                },
            )

        self._assert_hidden(response)
        create_order.assert_not_called()

    def test_missing_or_unknown_account_type_fails_closed_without_lookup(self):
        for account_type in (None, "", "admin", "unexpected"):
            with self.subTest(account_type=account_type), patch.object(
                admin_routes,
                "hr_resource_belongs_to_center",
            ) as belongs_to_center, patch.object(
                admin_routes,
                "get_heure_debut_cours",
            ) as get_time:
                self._login(account_type=account_type, account_id=10)
                response = self.client.get(
                    "/api/admin/course-time",
                    headers={"X-Platform-Id": "1"},
                )

            self._assert_hidden(response)
            belongs_to_center.assert_not_called()
            get_time.assert_not_called()

    def test_missing_platform_id_and_ownership_lookup_failure_fail_closed(self):
        self._login(account_id=10)
        with patch.object(
            admin_routes,
            "hr_resource_belongs_to_center",
        ) as belongs_to_center, patch.object(
            admin_routes,
            "get_heure_debut_cours",
        ) as get_time:
            missing = self.client.get("/api/admin/course-time")

        self._assert_hidden(missing)
        belongs_to_center.assert_not_called()
        get_time.assert_not_called()

        with patch.object(
            admin_routes,
            "hr_resource_belongs_to_center",
            side_effect=RuntimeError("database unavailable"),
        ), patch.object(admin_routes, "get_heure_debut_cours") as get_time:
            unavailable = self.client.get(
                "/api/admin/course-time",
                headers={"X-Platform-Id": "1"},
            )

        self._assert_hidden(unavailable)
        get_time.assert_not_called()

    def test_explicit_superadmin_types_are_global(self):
        course_time = datetime(2026, 7, 10, 9, 0, 0)
        for account_type in ("legacy_admin", "superadmin"):
            with self.subTest(account_type=account_type), patch.object(
                admin_routes,
                "hr_resource_belongs_to_center",
            ) as belongs_to_center, patch.object(
                admin_routes,
                "get_heure_debut_cours",
                return_value=course_time,
            ) as get_time:
                self._login(account_type=account_type, account_id=None)
                response = self.client.get(
                    "/api/admin/course-time",
                    headers={"X-Platform-Id": "2"},
                )

            self.assertEqual(response.status_code, 200)
            belongs_to_center.assert_not_called()
            get_time.assert_called_once_with(2)

    def test_internal_platform_key_endpoint_remains_a_separate_boundary(self):
        with patch.dict(os.environ, {"PLATFORM_API_KEY": "service-secret"}), patch.object(
            admin_routes,
            "get_db_connection",
            side_effect=self._connect,
        ):
            response = self.client.post(
                "/api/internal/set-lock",
                headers={"X-Platform-Key": "service-secret"},
                json={"platform_id": 2, "locked": True},
            )

        self.assertEqual(response.status_code, 200)
        conn = self._connect()
        locked = conn.execute(
            "SELECT upload_locked FROM platform_config WHERE id = 2"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(locked, 1)


if __name__ == "__main__":
    unittest.main()
