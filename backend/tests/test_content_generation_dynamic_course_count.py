import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from flask import Flask

from routes.hr_routes import create_hr_blueprint
from services import content_generation_service as cgs


def _playlist(course_count):
    items = []
    for index in range(1, course_count + 1):
        items.extend([
            (f"course_{index:02d}.mp3", 2700, "cours", index),
            (f"qa_{index:02d}.mp3", 900, "qa", index),
        ])
    return items


class ExtractSubPartsDynamicCountTest(unittest.TestCase):
    def test_extracts_exact_requested_count_and_builds_dynamic_prompt(self):
        response = json.dumps({
            "title": "TP Test",
            "sub_parts": [
                f"Cours {index} — Thème {index}"
                for index in range(1, 9)
            ],
        })
        with patch.object(cgs, "_deepseek_post", return_value=response) as post:
            result = cgs.extract_sub_parts(
                "Programme suffisamment détaillé",
                course_count=5,
            )

        self.assertEqual(len(result["sub_parts"]), 5)
        prompt = post.call_args.kwargs["messages"][0]["content"]
        self.assertIn("identifier exactement 5 cours", prompt)
        self.assertIn('"Cours 5 — Nom précis du thème"', prompt)
        self.assertNotIn('"Cours 6 — Nom précis du thème"', prompt)

    def test_pads_to_exact_requested_count(self):
        response = json.dumps({
            "title": "TP Test",
            "sub_parts": ["Cours 1 — Introduction"],
        })
        with patch.object(cgs, "_deepseek_post", return_value=response):
            result = cgs.extract_sub_parts("Programme", course_count=4)

        self.assertEqual(
            result["sub_parts"],
            ["Introduction", "Sous-partie 2", "Sous-partie 3", "Sous-partie 4"],
        )

    def test_v1_default_remains_seven(self):
        response = json.dumps({
            "title": "TP Test",
            "sub_parts": [
                f"Cours {index} — Thème {index}"
                for index in range(1, 8)
            ],
        })
        with patch.object(cgs, "_deepseek_post", return_value=response):
            result = cgs.extract_sub_parts("Programme")

        self.assertEqual(len(result["sub_parts"]), 7)

    def test_rejects_counts_outside_v2_contract(self):
        with patch.object(cgs, "_deepseek_post") as post:
            with self.assertRaisesRegex(ValueError, "entre 4 et 10"):
                cgs.extract_sub_parts("Programme", course_count=3)
            with self.assertRaisesRegex(ValueError, "entre 4 et 10"):
                cgs.extract_sub_parts("Programme", course_count=11)
        post.assert_not_called()


class PipelineContentRetryOwnershipTest(unittest.TestCase):
    def test_content_wrapper_disables_hidden_http_retries(self):
        with patch.object(cgs, "_llm_post", return_value="ok") as post:
            self.assertEqual(
                cgs._deepseek_post(
                    [{"role": "user", "content": "test"}],
                    max_tokens=100,
                    model="deepseek-v4-pro",
                ),
                "ok",
            )

        self.assertEqual(post.call_args.kwargs["http_max_attempts"], 1)

    def test_structured_plan_failure_calls_generator_once(self):
        with patch.object(
            cgs,
            "_structured_plan_two_stage_enabled",
            return_value=True,
        ), patch.object(
            cgs,
            "_generate_structured_course_plan_two_stage",
            side_effect=RuntimeError("provider indisponible"),
        ) as generate:
            with self.assertRaisesRegex(RuntimeError, "provider indisponible"):
                cgs._generate_structured_course_plan(
                    {"id": 1},
                    [],
                    [],
                    {},
                    model="deepseek-v4-pro",
                )

        generate.assert_called_once()

    def test_legacy_segment_failure_calls_model_once(self):
        with patch.object(
            cgs,
            "_deepseek_post",
            side_effect=RuntimeError("provider indisponible"),
        ) as post:
            with self.assertRaisesRegex(RuntimeError, "provider indisponible"):
                cgs._generate_segment_text(
                    1,
                    "Thème",
                    "Titre",
                    "Programme",
                    "",
                    from_scratch=True,
                    module_content="Contenu source",
                )

        post.assert_called_once()

    def test_review_failure_calls_model_once_and_propagates(self):
        with patch.object(
            cgs,
            "_deepseek_post",
            side_effect=RuntimeError("provider indisponible"),
        ) as post:
            with self.assertRaisesRegex(RuntimeError, "provider indisponible"):
                cgs._review_chunk_once("prompt", "groupe", 1)

        post.assert_called_once()


class FolderCourseCountWiringTest(unittest.TestCase):
    def test_resolves_count_from_exact_folder_playlist(self):
        with patch(
            "services.day_playlist_service.resolve_folder_playlist",
            return_value={
                "schema_version": 2,
                "playlist_items": _playlist(6),
            },
        ):
            self.assertEqual(
                cgs.resolve_folder_content_course_count(42),
                6,
            )

    def test_rejects_corrupt_manifest_count(self):
        with patch(
            "services.day_playlist_service.resolve_folder_playlist",
            return_value={
                "schema_version": 2,
                "playlist_items": _playlist(3),
            },
        ):
            with self.assertRaisesRegex(ValueError, "entre 4 et 10"):
                cgs.resolve_folder_content_course_count(42)

    def test_start_job_passes_manifest_count_to_extractor(self):
        extracted = {
            "title": "TP dynamique",
            "sub_parts": [f"Thème {index}" for index in range(1, 6)],
        }
        with patch.object(
            cgs,
            "resolve_folder_content_course_count",
            return_value=5,
        ), patch.object(
            cgs,
            "extract_sub_parts",
            return_value=extracted,
        ) as extract, patch.object(
            cgs,
            "reset_and_upsert_content_generation_job",
        ) as upsert, patch(
            "threading.Thread",
        ) as thread:
            cgs.start_generation_job(
                folder_id=9,
                platform_id=12,
                program_text="Programme source",
                program_title="Titre fourni",
            )

        extract.assert_called_once_with(
            "Programme source",
            course_count=5,
        )
        saved_parts = json.loads(
            upsert.call_args.kwargs["sub_parts_json"]
        )
        self.assertEqual(saved_parts, extracted["sub_parts"])
        thread.return_value.start.assert_called_once_with()


class HrContentJobDynamicCountTest(unittest.TestCase):
    def test_route_extracts_the_manifest_course_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp, "hr.sqlite"))
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE cours_folders (
                    id INTEGER PRIMARY KEY,
                    platform_id INTEGER NOT NULL
                );
                CREATE TABLE content_generation_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder_id INTEGER UNIQUE,
                    platform_id INTEGER,
                    program_text TEXT,
                    program_title TEXT,
                    sub_parts TEXT,
                    status TEXT,
                    current_sub_part INTEGER,
                    current_passe INTEGER,
                    total_words INTEGER,
                    error_message TEXT
                );
                CREATE TABLE content_generation_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER
                );
                INSERT INTO cours_folders (id, platform_id) VALUES (9, 12);
                """
            )
            conn.commit()
            conn.close()

            app = Flask(__name__)
            app.secret_key = "dynamic-content-count"
            app.register_blueprint(create_hr_blueprint(None))
            client = app.test_client()
            with client.session_transaction() as session:
                session["is_admin"] = True
                session["admin_account_type"] = "legacy_admin"

            extracted = {
                "title": "TP dynamique",
                "sub_parts": [f"Thème {index}" for index in range(1, 7)],
            }
            with patch(
                "routes.hr_routes.HR_ENABLED",
                True,
            ), patch(
                "routes.hr_routes.get_db_connection",
                side_effect=lambda: sqlite3.connect(db_path),
            ), patch.object(
                cgs,
                "resolve_folder_content_course_count",
                return_value=6,
            ) as resolve_count, patch.object(
                cgs,
                "extract_sub_parts",
                return_value=extracted,
            ) as extract:
                response = client.post(
                    "/api/hr/cours-folders/9/content-job",
                    json={"program_text": "Programme " * 10},
                )

            self.assertEqual(response.status_code, 200, response.get_json())
            resolve_count.assert_called_once_with(9)
            extract.assert_called_once_with(
                ("Programme " * 10).strip(),
                course_count=6,
            )

            conn = sqlite3.connect(db_path)
            saved = conn.execute(
                "SELECT sub_parts FROM content_generation_jobs WHERE folder_id = 9"
            ).fetchone()
            conn.close()
            self.assertEqual(json.loads(saved[0]), extracted["sub_parts"])


class DynamicCourseProgressAndContextTest(unittest.TestCase):
    def test_position_context_uses_explicit_or_playlist_total(self):
        explicit = cgs._build_course_position_context(
            sub_part_index=4,
            passe=1,
            total_courses=6,
        )
        inferred = cgs._build_course_position_context(
            sub_part_index=3,
            passe=2,
            playlist_spec=_playlist(5),
        )

        self.assertIn("Cours de la journée : 5/6.", explicit)
        self.assertIn("Cours de la journée : 4/5.", inferred)

    def test_editorial_profile_maps_relative_final_course(self):
        final_profile = cgs._course_slot_prompt_profile(
            5,
            1,
            total_courses=5,
        )
        late_profile = cgs._course_slot_prompt_profile(
            8,
            2,
            total_courses=10,
        )

        self.assertIn("Cours 5 — consolidation et clôture", final_profile)
        self.assertTrue(late_profile)
        self.assertIn("Cours 8", late_profile)

    def test_mock_generation_reports_manifest_course_count(self):
        progress = Mock()
        job = {
            "id": 1,
            "formation_job_id": None,
            "platform_id": 8,
            "program_text": "Programme",
            "program_title": "TP Test",
            "sub_parts": [f"Thème {index}" for index in range(1, 6)],
            "from_scratch": False,
            "module_contents": {},
            "total_words": 0,
        }
        with patch.object(
            cgs,
            "get_job_from_db",
            return_value=job,
        ), patch.object(
            cgs,
            "_playlist_items_for_platform",
            return_value=_playlist(5),
        ), patch.object(
            cgs,
            "_get_completed_segments",
            return_value=set(),
        ), patch.object(
            cgs,
            "_content_parallel_subpart_workers",
            return_value=1,
        ), patch.object(
            cgs,
            "_update_job_db",
        ), patch.object(
            cgs,
            "_save_segment_db",
        ), patch.object(
            cgs,
            "_assemble_and_upload",
            return_value=(123, "cours.txt"),
        ), patch.object(
            cgs.time,
            "sleep",
        ):
            cgs.run_content_generation(
                folder_id=9,
                on_progress=progress,
                mode="mock",
            )

        self.assertTrue(progress.called)
        self.assertEqual(
            {call.args[1] for call in progress.call_args_list},
            {5},
        )
        messages = [call.args[4] for call in progress.call_args_list]
        self.assertTrue(
            any("Sous-partie 5/5" in message for message in messages),
            messages,
        )


if __name__ == "__main__":
    unittest.main()
