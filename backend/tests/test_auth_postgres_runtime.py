import unittest
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from flask import Flask
from werkzeug.security import generate_password_hash

from routes import auth_routes
from config import FRANCE_TZ
from utils.auth_tokens import (
    issue_course_invitation_token,
    verify_auth_token,
    verify_course_invitation_token,
)


class AuthPostgresRuntimeTest(unittest.TestCase):
    def test_course_invitation_timestamp_remains_valid_for_a_j365_rule(self):
        now = datetime.now(FRANCE_TZ)
        issued_at = now - timedelta(days=300)
        scheduled_at = now + timedelta(days=65)
        with patch("itsdangerous.timed.time.time", return_value=issued_at.timestamp()):
            token = issue_course_invitation_token(
                platform_id=5,
                session_id=42,
                scheduled_at=scheduled_at,
                recipient_email="eleve@example.test",
                expires_at=scheduled_at + timedelta(hours=12),
            )

        with patch("itsdangerous.timed.time.time", return_value=time.time()):
            payload = verify_course_invitation_token(token)

        self.assertIsNotNone(payload)
        self.assertEqual(payload["session_id"], 42)

    def setUp(self):
        self.socketio = Mock()
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="auth-postgres-test")
        app.register_blueprint(auth_routes.create_auth_blueprint(self.socketio))
        self.client = app.test_client()

    def _postgres_only(self):
        return patch.multiple(
            auth_routes,
            DATABASE_BACKEND="postgres",
            get_db_connection=Mock(side_effect=AssertionError("SQLite must not be opened")),
        )

    def test_account_login_uses_only_postgres(self):
        account = {
            "id": 8,
            "username": "lina",
            "password_hash": generate_password_hash("correct-password"),
            "nom": "Martin",
            "prenom": "Lina",
            "is_active": True,
        }
        with self._postgres_only(), patch.object(
            auth_routes, "get_student_account", return_value=account
        ) as get_account, patch.object(
            auth_routes, "create_log", return_value=91
        ) as create_log:
            response = self.client.post(
                "/api/auth/login",
                json={"platform_id": 4, "username": "LINA", "password": "correct-password"},
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["log_id"], 91)
        get_account.assert_called_once_with(4, "lina")
        self.assertEqual(create_log.call_args.args[0]["platform_id"], 4)

    def test_legacy_session_password_is_read_from_postgres(self):
        with self._postgres_only(), patch.object(
            auth_routes, "get_student_account", return_value=None
        ), patch.object(
            auth_routes, "count_student_accounts", return_value=0
        ), patch.object(
            auth_routes,
            "list_course_session_credentials_for_window",
            return_value=[{
                "id": 51,
                "platform_id": 5,
                "scheduled_at": datetime.now(FRANCE_TZ) + timedelta(days=1),
                "status": "planned",
                "session_password": "session-secret",
            }],
        ) as list_credentials, patch.object(
            auth_routes, "create_log", return_value=92
        ):
            response = self.client.post(
                "/api/auth/login",
                json={
                    "platform_id": 5,
                    "nom": "Martin",
                    "prenom": "Lina",
                    "password": "session-secret",
                },
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["log_id"], 92)
        self.assertEqual(response.get_json()["course_session_id"], 51)
        self.assertEqual(list_credentials.call_args.args[0], 5)
        self.assertNotIn("sqlite_cursor", list_credentials.call_args.kwargs)

    def test_session_code_allows_guest_when_legacy_fallback_is_disabled(self):
        with self._postgres_only(), patch.multiple(
            auth_routes,
            STUDENT_AUTH_LEGACY_FALLBACK=False,
        ), patch.object(
            auth_routes,
            "list_course_session_credentials_for_window",
            return_value=[{
                "id": 52,
                "platform_id": 5,
                "scheduled_at": datetime.now(FRANCE_TZ) + timedelta(days=1),
                "status": "planned",
                "session_password": "session-secret",
            }],
        ), patch.object(
            auth_routes, "count_student_accounts", side_effect=AssertionError("not required")
        ), patch.object(
            auth_routes, "create_log", return_value=97
        ):
            response = self.client.post(
                "/api/auth/login",
                json={
                    "platform_id": 5,
                    "nom": "Martin",
                    "prenom": "Lina",
                    "password": "session-secret",
                },
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["log_id"], 97)
        self.assertEqual(response.get_json()["course_session_id"], 52)

    def test_session_code_window_covers_a_reminder_sent_two_days_before(self):
        captured = {}

        def credentials(platform_id, *, lower_bound, upper_bound):
            captured.update({
                "platform_id": platform_id,
                "lower_bound": lower_bound,
                "upper_bound": upper_bound,
            })
            return [{
                "id": 53,
                "platform_id": platform_id,
                "scheduled_at": datetime.now(FRANCE_TZ) + timedelta(days=2),
                "status": "planned",
                "session_password": "J2-CODE",
            }]

        with self._postgres_only(), patch.multiple(
            auth_routes,
            STUDENT_AUTH_LEGACY_FALLBACK=False,
        ), patch.dict(
            auth_routes.os.environ,
            {"COURSE_SESSION_PASSWORD_EARLY_HOURS": "72"},
        ), patch.object(
            auth_routes,
            "list_course_session_credentials_for_window",
            side_effect=credentials,
        ), patch.object(
            auth_routes, "create_log", return_value=99
        ):
            response = self.client.post(
                "/api/auth/login",
                json={
                    "platform_id": 5,
                    "nom": "Martin",
                    "prenom": "Lina",
                    "password": "J2-CODE",
                },
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["course_session_id"], 53)
        self.assertGreater(
            captured["upper_bound"] - datetime.now(FRANCE_TZ),
            timedelta(hours=71),
        )

    def test_signed_invitation_allows_name_only_and_is_bound_to_occurrence(self):
        scheduled_at = datetime.now(FRANCE_TZ) + timedelta(days=2)
        invitation = issue_course_invitation_token(
            platform_id=5,
            session_id=42,
            scheduled_at=scheduled_at,
            recipient_email="lina@example.test",
            expires_at=scheduled_at + timedelta(hours=12),
        )
        course_session = {
            "id": 42,
            "platform_id": 5,
            "status": "planned",
            "scheduled_at": scheduled_at,
        }
        with self._postgres_only(), patch.multiple(
            auth_routes,
            STUDENT_AUTH_LEGACY_FALLBACK=False,
        ), patch.object(
            auth_routes, "get_audio_generation_session", return_value=course_session
        ), patch.object(
            auth_routes, "count_student_accounts", side_effect=AssertionError("not required")
        ), patch.object(
            auth_routes, "create_log", return_value=98
        ):
            response = self.client.post(
                "/api/auth/login",
                json={
                    "platform_id": 5,
                    "nom": "Martin",
                    "prenom": "Lina",
                    "invitation_token": invitation,
                },
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["log_id"], 98)
        self.assertEqual(response.get_json()["course_session_id"], 42)
        token_payload = verify_auth_token("student", response.get_json()["token"])
        self.assertEqual(token_payload["course_session_id"], 42)

        course_session["scheduled_at"] = scheduled_at + timedelta(days=1)
        with self._postgres_only(), patch.object(
            auth_routes, "get_audio_generation_session", return_value=course_session
        ), patch.object(auth_routes, "create_log") as create_log:
            response = self.client.post(
                "/api/auth/login",
                json={
                    "platform_id": 5,
                    "nom": "Martin",
                    "prenom": "Lina",
                    "invitation_token": invitation,
                },
            )

        self.assertEqual(response.status_code, 401, response.get_json())
        create_log.assert_not_called()

    def test_supabase_session_uses_postgres_profile_and_log(self):
        supabase_user = {
            "id": "18f88e6a-7c83-4a45-a3d7-320e7300929a",
            "email": "lina@example.test",
            "user_metadata": {},
        }
        profile = {
            "nom": "Martin",
            "prenom": "Lina",
            "platform_id": 6,
            "is_active": True,
            "role": "student",
            "email": "lina@example.test",
        }
        with self._postgres_only(), patch.object(
            auth_routes, "_get_supabase_user", return_value=supabase_user
        ), patch.object(
            auth_routes, "get_student_profile", return_value=profile
        ) as get_profile, patch.object(
            auth_routes, "create_log", return_value=93
        ):
            response = self.client.post(
                "/api/auth/supabase-session",
                json={"platform_id": 6, "access_token": "valid-access-token"},
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["log_id"], 93)
        get_profile.assert_called_once_with(supabase_user["id"])

    def test_supabase_session_rejects_untrusted_metadata_without_server_profile(self):
        supabase_user = {
            "id": "639752ef-4d20-4806-9462-d9e935571eb4",
            "email": "sam@example.test",
            "user_metadata": {"nom": "Petit", "prenom": "Sam", "platform_id": 9},
        }
        with self._postgres_only(), patch.object(
            auth_routes, "_get_supabase_user", return_value=supabase_user
        ), patch.object(
            auth_routes, "get_student_profile", return_value=None
        ), patch.object(auth_routes, "upsert_student_profile") as upsert_profile, patch.object(
            auth_routes, "create_log", return_value=96
        ) as create_log:
            response = self.client.post(
                "/api/auth/supabase-session",
                json={"platform_id": 9, "access_token": "valid-access-token"},
            )

        self.assertEqual(response.status_code, 403, response.get_json())
        upsert_profile.assert_not_called()
        create_log.assert_not_called()

    def test_logout_routes_close_postgres_logs_without_sqlite(self):
        with self.client.session_transaction() as student_session:
            student_session.update({"nom": "Martin", "prenom": "Lina", "log_id": 94})

        with self._postgres_only(), patch.object(
            auth_routes, "update_log_depart", return_value=True
        ) as close_one:
            response = self.client.post("/api/auth/logout")

        self.assertEqual(response.status_code, 200, response.get_json())
        close_one.assert_called_once()

        with self.client.session_transaction() as student_session:
            student_session.update({"nom": "Martin", "prenom": "Lina", "log_id": 95})
        with self._postgres_only(), patch.object(
            auth_routes, "update_log_depart", return_value=True
        ) as close_auto:
            response = self.client.post("/deconnexion-auto")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(close_auto.call_args.args[0], 95)

        with self._postgres_only(), patch.object(
            auth_routes, "close_open_logs", return_value=7
        ) as close_all:
            response = self.client.post("/deconnexion-auto-tous")

        self.assertEqual(response.status_code, 403, response.get_json())
        close_all.assert_not_called()

        with self._postgres_only(), patch.dict(
            auth_routes.os.environ, {"AUTO_LOGOUT_WEBHOOK_SECRET": "logic-app-secret"}
        ), patch.object(auth_routes, "close_open_logs", return_value=7) as close_all:
            response = self.client.post(
                "/deconnexion-auto-tous",
                headers={"X-Internal-Secret": "logic-app-secret"},
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["users_disconnected"], 7)
        close_all.assert_called_once()
        self.socketio.emit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
