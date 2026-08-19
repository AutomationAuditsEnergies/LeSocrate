import io
import unittest
from unittest.mock import patch

from flask import Flask

from routes.hr_routes import create_hr_blueprint


class AIVoiceRoutesTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="ai-voice-routes")
        app.register_blueprint(create_hr_blueprint())
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["is_admin"] = True
            session["admin_account_type"] = "training_center"
            session["admin_account_id"] = 42

    def test_list_is_scoped_to_center(self):
        voices = [{"id": 3, "center_account_id": 42, "name": "Sophie"}]
        with patch("routes.hr_routes.HR_ENABLED", True), patch(
            "repositories.ai_voice_repository.list_voices",
            return_value=voices,
        ) as list_voices:
            response = self.client.get("/api/hr/ai-voices")

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["voices"], voices)
        list_voices.assert_called_once_with(42)

    def test_clone_requires_vocal_consent(self):
        with patch("routes.hr_routes.HR_ENABLED", True):
            response = self.client.post(
                "/api/hr/ai-voices/clone",
                data={
                    "name": "Sophie",
                    "voice_sample": (io.BytesIO(b"voice"), "voice.wav"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(response.get_json()["code"], "voice_consent_required")

    def test_clone_persists_hashes_not_raw_biometric_audio(self):
        created = {
            "id": 8,
            "center_account_id": 42,
            "name": "Sophie",
            "fish_reference_id": "fish-reference-8",
        }
        with (
            patch("routes.hr_routes.HR_ENABLED", True),
            patch(
                "services.fish_voice_service.validate_audio",
                side_effect=[4.0, 32.0],
            ) as validate_audio,
            patch(
                "services.fish_voice_service.create_instant_clone",
                return_value={"reference_id": "fish-reference-8", "state": "created"},
            ),
            patch(
                "repositories.ai_voice_repository.create_voice",
                return_value=created,
            ) as create_voice,
        ):
            response = self.client.post(
                "/api/hr/ai-voices/clone",
                data={
                    "name": "Sophie",
                    "consent_confirmed": "true",
                    "consent_sample": (io.BytesIO(b"consent-audio"), "consent.wav"),
                    "consent_sample_duration_sec": "4.0",
                    "voice_sample": (io.BytesIO(b"voice-audio"), "voice.wav"),
                    "voice_sample_duration_sec": "32.0",
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 201, response.get_json())
        kwargs = create_voice.call_args.kwargs
        self.assertEqual(len(kwargs["consent_recording_sha256"]), 64)
        self.assertEqual(len(kwargs["sample_sha256"]), 64)
        self.assertNotIn("consent-audio", repr(kwargs))
        self.assertNotIn("voice-audio", repr(kwargs))
        self.assertEqual(
            validate_audio.call_args_list[0].kwargs["duration_hint"],
            "4.0",
        )
        self.assertEqual(
            validate_audio.call_args_list[1].kwargs["duration_hint"],
            "32.0",
        )


if __name__ == "__main__":
    unittest.main()
