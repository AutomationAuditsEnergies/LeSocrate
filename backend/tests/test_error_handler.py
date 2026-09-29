"""Gestionnaire d'erreurs central (tâche 1.16) et chemin des logs (tâche 1.32)."""

import io
import logging
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from flask import Flask
from werkzeug.security import generate_password_hash

from routes import admin_routes, auth_routes
from utils import logger as logger_module
from utils.errors import register_api_error_handler
from utils.rate_limit import RATE_LIMIT_ERROR, apply_auth_rate_limits, init_rate_limiter


class ApiErrorHandlerTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        # TESTING propage les exceptions non gérées : on voit ainsi que seules
        # les routes hors /api/ gardent le comportement Flask par défaut.
        app.config.update(TESTING=True, SECRET_KEY="error-handler-test")
        limiter = init_rate_limiter(app)
        register_api_error_handler(app)
        app.register_blueprint(auth_routes.create_auth_blueprint())
        app.register_blueprint(admin_routes.create_admin_blueprint())
        apply_auth_rate_limits(app, limiter)

        @app.get("/api/test/boom")
        def api_boom():
            raise RuntimeError("secret table xyz")

        @app.get("/page/boom")
        def page_boom():
            raise RuntimeError("secret page xyz")

        self.client = app.test_client()

    def test_unexpected_api_error_hides_the_detail_but_logs_it(self):
        with self.assertLogs("utils.errors", level="ERROR") as logs:
            response = self.client.get("/api/test/boom")

        self.assertEqual(response.status_code, 500)
        payload = response.get_json()
        self.assertFalse(payload["success"])
        self.assertRegex(payload["error_id"], r"^[0-9a-f]{8}$")
        self.assertIn(f"réf. {payload['error_id']}", payload["error"])
        self.assertNotIn("secret table xyz", response.get_data(as_text=True))

        record = logs.records[0]
        logged = logging.Formatter().format(record)
        self.assertIn(payload["error_id"], logged)
        self.assertIn("GET /api/test/boom", logged)
        self.assertIn("secret table xyz", logged)

    def test_unknown_api_route_is_still_404(self):
        response = self.client.get("/api/route-inconnue")

        self.assertEqual(response.status_code, 404)

    def test_wrong_method_is_still_405(self):
        response = self.client.delete("/api/auth/login")

        self.assertEqual(response.status_code, 405)

    def test_non_api_route_keeps_default_flask_behaviour(self):
        with self.assertRaisesRegex(RuntimeError, "secret page xyz"):
            self.client.get("/page/boom")

    def test_eleventh_login_attempt_is_still_429(self):
        account = {
            "id": 8,
            "username": "lina",
            "password_hash": generate_password_hash("correct-password"),
            "nom": "Martin",
            "prenom": "Lina",
            "is_active": True,
        }
        with patch.multiple(
            auth_routes,
            DATABASE_BACKEND="postgres",
            get_db_connection=Mock(side_effect=AssertionError("SQLite must not be opened")),
        ), patch.object(auth_routes, "get_student_account", return_value=account):
            statuses = [
                self.client.post(
                    "/api/auth/login",
                    json={"platform_id": 4, "username": "lina", "password": "faux"},
                )
                for _ in range(11)
            ]

        self.assertNotIn(429, [response.status_code for response in statuses[:10]])
        self.assertEqual(statuses[10].status_code, 429)
        self.assertEqual(
            statuses[10].get_json(), {"success": False, "error": RATE_LIMIT_ERROR}
        )


class LogFilePathTest(unittest.TestCase):
    def setUp(self):
        root = logging.getLogger()
        self._saved_handlers = root.handlers[:]
        self._saved_level = root.level

    def tearDown(self):
        root = logging.getLogger()
        for handler in root.handlers:
            if handler not in self._saved_handlers:
                handler.close()
        root.handlers[:] = self._saved_handlers
        root.setLevel(self._saved_level)

    def test_log_file_env_var_wins(self):
        with patch.dict(os.environ, {"LOG_FILE": "D:/logs/cadrenza.log"}):
            self.assertEqual(logger_module.log_file_path(), "D:/logs/cadrenza.log")

    def test_default_is_app_log_in_the_system_temp_dir(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LOG_FILE", None)
            self.assertEqual(
                logger_module.log_file_path(),
                os.path.join(tempfile.gettempdir(), "app.log"),
            )

    def test_unwritable_log_file_keeps_console_only(self):
        with tempfile.TemporaryDirectory() as missing_parent:
            unwritable = os.path.join(missing_parent, "absent", "app.log")
            console = io.StringIO()
            with patch.dict(os.environ, {"LOG_FILE": unwritable}), patch("sys.stdout", console):
                logger_module.configure_logging()

            handlers = logging.getLogger().handlers
            self.assertFalse(any(isinstance(h, logging.FileHandler) for h in handlers))
            self.assertTrue(any(isinstance(h, logging.StreamHandler) for h in handlers))
            self.assertIn("LOG_FILE_UNAVAILABLE", console.getvalue())

    def test_writable_log_file_is_used(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "app.log")
            with patch.dict(os.environ, {"LOG_FILE": path}), patch("sys.stdout", io.StringIO()):
                logger_module.configure_logging()
                logging.getLogger("test.log_file").warning("ligne de test")

            file_handlers = [
                h for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler)
            ]
            self.assertEqual([h.baseFilename for h in file_handlers], [os.path.abspath(path)])
            for handler in file_handlers:
                handler.close()
            with open(path, encoding="utf-8") as log_file:
                self.assertIn("ligne de test", log_file.read())


if __name__ == "__main__":
    unittest.main()
