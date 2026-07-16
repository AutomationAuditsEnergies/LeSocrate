import unittest
import time
from datetime import datetime, timedelta
from unittest.mock import patch

from flask import Flask

from config import FRANCE_TZ
from routes import chat_routes, slides_routes, video_routes
from utils.auth_tokens import issue_auth_token


class _StorageResponse:
    def __init__(self, body=b"audio-bytes", status_code=200, headers=None):
        self.body = body
        self.status_code = status_code
        self.headers = headers or {"Content-Length": str(len(body))}
        self.closed = False

    def iter_content(self, chunk_size=8192):
        yield self.body

    def close(self):
        self.closed = True


class _ChatResponse:
    status_code = 200
    text = ""

    @staticmethod
    def json():
        return {"choices": [{"message": {"content": "Réponse [doc1]"}}]}


class StudentCourseAccessTest(unittest.TestCase):
    PLATFORM_ID = 7
    SESSION_J1 = 701
    SESSION_J2 = 702

    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="student-course-access-test")
        app.register_blueprint(video_routes.video_bp)
        app.register_blueprint(slides_routes.slides_bp)
        app.register_blueprint(chat_routes.chat_bp)
        self.client = app.test_client()
        self.j1_at = FRANCE_TZ.localize(datetime(2026, 7, 16, 9, 0, 0))
        self.j2_at = self.j1_at + timedelta(days=7)
        self.occurrences = {
            (self.PLATFORM_ID, self.SESSION_J1): {
                "id": self.SESSION_J1,
                "platform_id": self.PLATFORM_ID,
                "status": "active",
                "scheduled_at": self.j1_at,
                "audio_storage_prefix": f"course-sessions/{self.SESSION_J1}",
            },
            (self.PLATFORM_ID, self.SESSION_J2): {
                "id": self.SESSION_J2,
                "platform_id": self.PLATFORM_ID,
                "status": "planned",
                "scheduled_at": self.j2_at,
                "audio_storage_prefix": f"course-sessions/{self.SESSION_J2}",
            },
        }
        self.occurrence_patcher = patch.object(
            video_routes,
            "get_audio_generation_session",
            side_effect=lambda platform_id, session_id: self.occurrences.get(
                (int(platform_id), int(session_id))
            ),
        )
        self.get_occurrence = self.occurrence_patcher.start()
        self.addCleanup(self.occurrence_patcher.stop)
        self.delivery_mode_patcher = patch.dict(
            video_routes.os.environ,
            {"STUDENT_AUDIO_DELIVERY_MODE": "proxy"},
        )
        self.delivery_mode_patcher.start()
        self.addCleanup(self.delivery_mode_patcher.stop)
        self.sas_url_patcher = patch.object(
            video_routes,
            "issue_platform_audio_read_url",
            return_value=self._audio()["filename"],
        )
        self.issue_audio_url = self.sas_url_patcher.start()
        self.addCleanup(self.sas_url_patcher.stop)

    def _set_student_session(self, *, platform_id=None, course_session_id=None, log_id=91):
        with self.client.session_transaction() as student_session:
            student_session.update(
                {
                    "nom": "Martin",
                    "prenom": "Lina",
                    "log_id": log_id,
                    "platform_id": platform_id or self.PLATFORM_ID,
                    "course_session_id": course_session_id or self.SESSION_J1,
                }
            )

    @staticmethod
    def _audio(filename="https://private.blob.core.windows.net/p7/cours_01.mp3?sig=secret"):
        return {
            "id": 1,
            "filename": filename,
            "duration": 3600,
            "title": "Cours 1",
            "type": "cours",
        }

    def test_sensitive_student_routes_require_an_occurrence_bound_session(self):
        with patch.object(video_routes, "get_course_session_audio_info") as audio_info, patch.object(
            video_routes.http_requests, "get"
        ) as storage_get, patch.object(
            video_routes, "get_latest_script_slide_deck_for_audio"
        ) as get_deck:
            for path in ("/api/video/status", "/api/video/slides", "/api/audio/stream"):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 401, (path, response.get_json()))

        audio_info.assert_not_called()
        storage_get.assert_not_called()
        get_deck.assert_not_called()

    def test_platform_hint_and_signed_token_cannot_switch_tenant_or_occurrence(self):
        self._set_student_session()
        with patch.object(video_routes, "get_course_session_audio_info") as audio_info:
            response = self.client.get(
                "/api/audio/stream?platform_id=8",
                headers={"X-Platform-Id": "8"},
            )
            self.assertEqual(response.status_code, 403, response.get_json())

            other_occurrence_token = issue_auth_token(
                "student",
                {
                    "nom": "Martin",
                    "prenom": "Lina",
                    "log_id": 91,
                    "platform_id": self.PLATFORM_ID,
                    "course_session_id": self.SESSION_J2,
                },
            )
            response = self.client.get(
                "/api/video/status",
                headers={
                    "X-Platform-Id": str(self.PLATFORM_ID),
                    "X-Auth-Token": other_occurrence_token,
                },
            )
            self.assertEqual(response.status_code, 403, response.get_json())

        audio_info.assert_not_called()

    def test_matching_signed_token_keeps_occurrence_access(self):
        self._set_student_session()
        token = issue_auth_token(
            "student",
            {
                "nom": "Martin",
                "prenom": "Lina",
                "log_id": 91,
                "platform_id": self.PLATFORM_ID,
                "course_session_id": self.SESSION_J1,
            },
        )
        with patch.object(
            video_routes,
            "get_course_session_audio_info",
            return_value=(None, 0, 60),
        ):
            response = self.client.get(
                "/api/video/status",
                headers={
                    "X-Platform-Id": str(self.PLATFORM_ID),
                    "X-Auth-Token": token,
                },
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["status"], "waiting")

    def test_before_course_only_occurrence_countdown_is_available(self):
        self._set_student_session(course_session_id=self.SESSION_J2)
        with patch.object(
            video_routes,
            "get_course_session_audio_info",
            return_value=(None, 0, 3600),
        ) as audio_info, patch.object(
            video_routes.http_requests, "get"
        ) as storage_get, patch.object(
            video_routes, "get_latest_script_slide_deck_for_audio"
        ) as get_deck:
            status = self.client.get("/api/video/status")
            stream = self.client.get("/api/audio/stream")
            slides = self.client.get("/api/video/slides")

        self.assertEqual(status.status_code, 200, status.get_json())
        self.assertEqual(status.get_json()["status"], "waiting")
        self.assertEqual(status.get_json()["temps_restant"], 3600)
        self.assertEqual(stream.status_code, 425, stream.get_json())
        self.assertEqual(slides.status_code, 425, slides.get_json())
        self.assertTrue(all(call.args[1] == self.j2_at for call in audio_info.call_args_list))
        storage_get.assert_not_called()
        get_deck.assert_not_called()

    def test_during_course_only_server_selected_audio_and_deck_are_exposed(self):
        self._set_student_session()
        audio = self._audio()
        storage_response = _StorageResponse(status_code=206, headers={
            "Content-Length": "11",
            "Content-Range": "bytes 0-10/11",
        })
        deck = {
            "deck_id": 999,
            "folder_id": 888,
            "audio_sync": {
                "timings": [{"audio_filename": audio["filename"], "start_time": 0}],
            },
            "slides": [{"slide_id": "s1", "audio_filename": audio["filename"]}],
        }
        with patch.object(
            video_routes,
            "get_course_session_audio_info",
            return_value=(audio, 120, 0),
        ), patch.object(
            video_routes, "get_playlist", return_value=[audio]
        ), patch.object(
            video_routes,
            "get_latest_script_slide_deck_for_audio",
            return_value=deck,
        ) as get_deck, patch.object(
            video_routes.http_requests,
            "get",
            return_value=storage_response,
        ) as storage_get:
            status = self.client.get("/api/video/status")
            slides = self.client.get(
                "/api/video/slides?audio_filename=https://evil.example/other-tenant.mp3"
            )
            stream = self.client.get(
                "/api/audio/stream",
                headers={"Range": "bytes=0-10"},
            )

        status_payload = status.get_json()
        self.assertEqual(status_payload["status"], "playing")
        self.assertEqual(status_payload["audio_key"], "cours_01.mp3")
        self.assertNotIn("audio_filename", status_payload)
        self.assertTrue(status_payload.get("audio_stream_token"))
        self.assertNotIn("blob.core.windows.net", status.get_data(as_text=True))

        self.assertEqual(slides.status_code, 200, slides.get_json())
        self.assertNotIn("deck_id", slides.get_json())
        self.assertNotIn("folder_id", slides.get_json())
        self.assertNotIn("blob.core.windows.net", slides.get_data(as_text=True))
        self.assertEqual(
            slides.get_json()["audio_sync"]["timings"][0]["audio_filename"],
            "cours_01.mp3",
        )
        get_deck.assert_called_once_with(audio["filename"], platform_id=self.PLATFORM_ID)

        self.assertEqual(stream.status_code, 206)
        self.assertEqual(stream.data, b"audio-bytes")
        storage_get.assert_called_once_with(
            audio["filename"],
            headers={"Range": "bytes=0-10"},
            stream=True,
            timeout=(5, 30),
            allow_redirects=False,
        )
        self.assertTrue(storage_response.closed)
        self.assertEqual(stream.headers["Cache-Control"], "private, no-store")

    def test_current_audio_ticket_streams_without_a_third_party_cookie(self):
        self._set_student_session()
        audio = self._audio()
        storage_response = _StorageResponse()
        with patch.object(
            video_routes,
            "get_course_session_audio_info",
            return_value=(audio, 120, 0),
        ), patch.object(
            video_routes, "get_playlist", return_value=[audio]
        ), patch.object(
            video_routes.http_requests,
            "get",
            return_value=storage_response,
        ) as storage_get:
            status = self.client.get("/api/video/status")
            stream_ticket = status.get_json()["audio_stream_token"]
            with self.client.session_transaction() as student_session:
                student_session.clear()
            stream = self.client.get(
                "/api/audio/stream",
                query_string={"stream_token": stream_ticket},
            )

        self.assertEqual(stream.status_code, 200, stream.get_json(silent=True))
        self.assertEqual(stream.data, b"audio-bytes")
        storage_get.assert_called_once()

    def test_redirect_sas_offloads_authorized_audio_without_student_cookie(self):
        self._set_student_session()
        audio = self._audio()
        signed_url = (
            "https://storage.blob.core.windows.net/formationaudio-p7/"
            "cours_01.mp3?sp=r&se=short&sig=blob-only"
        )
        with patch.object(
            video_routes,
            "get_course_session_audio_info",
            return_value=(audio, 120, 0),
        ), patch.object(
            video_routes, "get_playlist", return_value=[audio]
        ), patch.dict(
            video_routes.os.environ,
            {"STUDENT_AUDIO_DELIVERY_MODE": "redirect_sas"},
        ), patch.object(
            video_routes,
            "issue_platform_audio_read_url",
            return_value=signed_url,
        ) as issue_url, patch.object(
            video_routes.http_requests, "get"
        ) as storage_get:
            status = self.client.get("/api/video/status")
            stream_ticket = status.get_json()["audio_stream_token"]
            with self.client.session_transaction() as student_session:
                student_session.clear()
            stream = self.client.get(
                "/api/audio/stream",
                query_string={"stream_token": stream_ticket},
                follow_redirects=False,
            )

        self.assertEqual(stream.status_code, 302)
        self.assertEqual(stream.headers["Location"], signed_url)
        self.assertEqual(stream.headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(stream.headers["Cache-Control"], "private, no-store")
        self.assertNotIn("sig=blob-only", status.get_data(as_text=True))
        issue_call = issue_url.call_args
        self.assertEqual(
            issue_call.args,
            (
                self.PLATFORM_ID,
                f"course-sessions/{self.SESSION_J1}/cours_01.mp3",
            ),
        )
        self.assertGreater(issue_call.kwargs["expires_at"], int(time.time()))
        storage_get.assert_not_called()

    def test_audio_ticket_rejects_wrong_audio_occurrence_and_expiration(self):
        audio = self._audio()
        valid_until = int(time.time()) + 300
        base_payload = {
            "platform_id": self.PLATFORM_ID,
            "course_session_id": self.SESSION_J1,
            "log_id": 91,
            "audio_id": audio["id"],
            "audio_key": f"course-sessions/{self.SESSION_J1}/cours_01.mp3",
            "boundary": valid_until,
            "exp": valid_until,
        }
        wrong_audio = issue_auth_token("audio_stream", {**base_payload, "audio_id": 999})
        wrong_occurrence = issue_auth_token(
            "audio_stream",
            {**base_payload, "course_session_id": 999},
        )
        expired_at = int(time.time()) - 1
        expired = issue_auth_token(
            "audio_stream",
            {**base_payload, "boundary": expired_at, "exp": expired_at},
        )

        with patch.object(
            video_routes,
            "get_course_session_audio_info",
            return_value=(audio, 120, 0),
        ), patch.object(video_routes.http_requests, "get") as storage_get:
            wrong_audio_response = self.client.get(
                "/api/audio/stream", query_string={"stream_token": wrong_audio}
            )
            wrong_occurrence_response = self.client.get(
                "/api/audio/stream", query_string={"stream_token": wrong_occurrence}
            )
            expired_response = self.client.get(
                "/api/audio/stream", query_string={"stream_token": expired}
            )

        self.assertEqual(wrong_audio_response.status_code, 403)
        self.assertEqual(wrong_occurrence_response.status_code, 403)
        self.assertEqual(expired_response.status_code, 401)
        storage_get.assert_not_called()

    def test_break_status_never_issues_or_downloads_audio(self):
        self._set_student_session()
        pause_audio = {**self._audio(), "id": 2, "type": "pause", "title": "Pause"}
        with patch.object(
            video_routes,
            "get_course_session_audio_info",
            return_value=(pause_audio, 30, 0),
        ), patch.object(
            video_routes, "get_playlist", return_value=[pause_audio]
        ), patch.object(video_routes.http_requests, "get") as storage_get:
            status = self.client.get("/api/video/status")
            stream = self.client.get("/api/audio/stream")

        self.assertNotIn("audio_stream_token", status.get_json())
        self.assertEqual(stream.status_code, 204)
        storage_get.assert_not_called()

    def test_after_course_audio_and_deck_are_closed(self):
        self._set_student_session()
        with patch.object(
            video_routes,
            "get_course_session_audio_info",
            return_value=(None, 0, 0),
        ), patch.object(
            video_routes.http_requests, "get"
        ) as storage_get, patch.object(
            video_routes, "get_latest_script_slide_deck_for_audio"
        ) as get_deck:
            status = self.client.get("/api/video/status")
            stream = self.client.get("/api/audio/stream")
            slides = self.client.get("/api/video/slides")

        self.assertEqual(status.get_json()["status"], "finished")
        self.assertEqual(stream.status_code, 410, stream.get_json())
        self.assertEqual(slides.status_code, 410, slides.get_json())
        storage_get.assert_not_called()
        get_deck.assert_not_called()

    def test_j2_link_during_j1_never_opens_j1_audio(self):
        self._set_student_session(course_session_id=self.SESSION_J2)
        j1_audio = self._audio()
        with patch.object(
            video_routes,
            "get_course_session_audio_info",
            return_value=(None, 0, 7 * 24 * 3600),
        ) as occurrence_audio, patch.object(
            video_routes,
            "get_current_audio_info",
            return_value=(j1_audio, 300, 0),
        ) as platform_audio, patch.object(
            video_routes.http_requests, "get"
        ) as storage_get:
            status = self.client.get("/api/video/status")
            stream = self.client.get("/api/audio/stream")

        self.assertEqual(status.get_json()["status"], "waiting")
        self.assertEqual(stream.status_code, 425, stream.get_json())
        self.assertTrue(all(call.args[1] == self.j2_at for call in occurrence_audio.call_args_list))
        platform_audio.assert_not_called()
        storage_get.assert_not_called()

    def test_public_status_never_discloses_audio_metadata(self):
        audio = self._audio()
        with patch.object(
            video_routes,
            "get_current_audio_info",
            return_value=(audio, 300, 0),
        ):
            response = self.client.get(
                "/api/cours-status",
                headers={"X-Platform-Id": str(self.PLATFORM_ID)},
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json(), {"status": "playing"})
        self.assertNotIn("blob.core.windows.net", response.get_data(as_text=True))

    def test_admin_slide_workbench_is_not_a_student_deck_backdoor(self):
        self._set_student_session()
        response = self.client.get("/api/slides/data")
        self.assertEqual(response.status_code, 403, response.get_json())

    def test_chat_requires_the_same_active_occurrence_as_audio(self):
        with patch.object(chat_routes.requests, "post") as azure_post:
            unauthenticated = self.client.post("/api/chat", json={"question": "Bonjour"})
        self.assertEqual(unauthenticated.status_code, 401)
        azure_post.assert_not_called()

        self._set_student_session(course_session_id=self.SESSION_J2)
        with patch.object(
            video_routes,
            "get_course_session_audio_info",
            return_value=(None, 0, 3600),
        ), patch.object(chat_routes.requests, "post") as azure_post:
            before = self.client.post("/api/chat", json={"question": "Bonjour"})
        self.assertEqual(before.status_code, 425)
        azure_post.assert_not_called()

        with patch.object(
            video_routes,
            "get_course_session_audio_info",
            return_value=(None, 0, 0),
        ), patch.object(chat_routes.requests, "post") as azure_post:
            after = self.client.post("/api/chat", json={"question": "Bonjour"})
        self.assertEqual(after.status_code, 410)
        azure_post.assert_not_called()

        self._set_student_session(course_session_id=self.SESSION_J1)
        with patch.dict(chat_routes.os.environ, {}, clear=True), patch.object(
            video_routes,
            "get_course_session_audio_info",
            return_value=(self._audio(), 120, 0),
        ), patch.object(
            chat_routes.requests,
            "post",
            return_value=_ChatResponse(),
        ) as azure_post:
            during = self.client.post("/api/chat", json={"question": "Bonjour"})
        self.assertEqual(during.status_code, 200, during.get_json())
        self.assertEqual(during.get_json()["answer"], "Réponse")
        azure_post.assert_called_once()
        search_parameters = azure_post.call_args.kwargs["json"]["data_sources"][0]["parameters"]
        self.assertEqual(search_parameters["index_name"], "rag-p7")

        with patch.dict(
            chat_routes.os.environ,
            {"PLATFORM_7_AZURE_SEARCH_INDEX_NAME": "rag-centre-7"},
        ), patch.object(
            video_routes,
            "get_course_session_audio_info",
            return_value=(self._audio(), 120, 0),
        ), patch.object(
            chat_routes.requests,
            "post",
            return_value=_ChatResponse(),
        ) as overridden_post:
            overridden = self.client.post("/api/chat", json={"question": "Bonjour"})
        self.assertEqual(overridden.status_code, 200)
        overridden_parameters = overridden_post.call_args.kwargs["json"]["data_sources"][0]["parameters"]
        self.assertEqual(overridden_parameters["index_name"], "rag-centre-7")


class CourseSessionAudioTimingTest(unittest.TestCase):
    def test_occurrence_timing_is_before_during_and_after_on_server_clock(self):
        from services import audio_service

        start = FRANCE_TZ.localize(datetime(2026, 7, 16, 9, 0, 0))
        audio = {
            "id": 1,
            "filename": "https://private.blob/audio.mp3",
            "duration": 60,
            "title": "Cours",
            "type": "cours",
        }
        with patch.object(audio_service, "get_playlist", return_value=[audio]):
            before = audio_service.get_course_session_audio_info(
                7, start, now=start - timedelta(seconds=30)
            )
            during = audio_service.get_course_session_audio_info(
                7, start, now=start + timedelta(seconds=12)
            )
            after = audio_service.get_course_session_audio_info(
                7, start, now=start + timedelta(seconds=60)
            )

        self.assertEqual(before, (None, 0, 30))
        self.assertEqual(during, (audio, 12, 0))
        self.assertEqual(after, (None, 0, 0))


if __name__ == "__main__":
    unittest.main()
