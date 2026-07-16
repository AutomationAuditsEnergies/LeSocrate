"""Tests du runtime fit Edge TTS dans `_synthesize_course_audio_synced_to_slides`.

On mocke `convert_to_speech_basic`, `_mp3_duration_seconds_no_ffprobe` et
`_synthesize_short_conclusion_audio` pour piloter de manière déterministe les
durées et éviter les appels réseau Edge TTS pendant les tests.
"""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from services import basic_tts_service as bts
from services import break_transition_service as bks
from services import content_generation_service as cgs
from repositories import pipeline_repository as pipeline_repo


def _id3_header(payload: bytes) -> bytes:
    """Construit un header ID3v2 minimal valide encapsulant `payload`."""
    size = len(payload)
    return bytes([
        0x49, 0x44, 0x33, 0x04, 0x00, 0x00,
        (size >> 21) & 0x7F,
        (size >> 14) & 0x7F,
        (size >> 7) & 0x7F,
        size & 0x7F,
    ]) + payload


def _mp3_chunk(label: str) -> bytes:
    """MP3 fictif avec ID3 + une « frame » MPEG bidon, pour tracer la concat."""
    return _id3_header(label.encode()[:8]) + b"\xff\xfbDATA-" + label.encode()


def _make_bloc(text, target_sec=2700, bloc_number=1):
    return {
        "bloc_number": bloc_number,
        "target_sec": target_sec,
        "text": text,
        "word_count": len(text.split()),
        "start_w": 0,
        "end_w": len(text.split()),
    }


def _phrases_text(n_phrases: int, words_per_phrase: int = 7) -> str:
    """Texte composé de `n_phrases` phrases courtes terminées par un point."""
    sentence = " ".join(["mot"] * words_per_phrase) + "."
    return " ".join([sentence] * n_phrases)


class RuntimeFitStopsBeforeOverflowTest(unittest.TestCase):
    def test_runtime_fit_flag_keeps_full_text_without_carryover(self):
        # Le runtime-fit est volontairement neutralisé : le TTS doit toujours
        # lire le texte canonique complet, sans couper ni reporter des chunks.
        text = _phrases_text(n_phrases=200, words_per_phrase=7)
        bloc = _make_bloc(text, target_sec=2700)
        tts = Mock(return_value=_mp3_chunk("VOICE"))

        with patch(
            "services.basic_tts_service.convert_to_speech_basic",
            tts,
        ), patch.object(
            cgs, "_mp3_duration_seconds_no_ffprobe", return_value=1500.0,
        ), patch.object(
            cgs, "_edge_muted_padding_audio",
            return_value=(_mp3_chunk("PAD"), 1200.0),
        ):
            (
                audio_bytes, voice_duration, fit_method,
                attempts, timings, unconsumed, consumed,
            ) = cgs._synthesize_course_audio_synced_to_slides(
                bloc, [], "cours.mp3",
                mock=False, basic_tts=True,
                runtime_fit=True,
                conclusion_margin_sec=90,
            )

        self.assertEqual(fit_method, "slide_sync_edge_no_padding")
        self.assertEqual(voice_duration, 1500.0)
        self.assertEqual(unconsumed, [])
        self.assertEqual(consumed, [])
        tts.assert_called_once()
        self.assertEqual(tts.call_args.args[0], text)


class FishAudioWordBudgetCalibrationTest(unittest.TestCase):
    def test_default_fish_audio_wpm_uses_measured_aggregate(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertAlmostEqual(cgs._course_words_per_minute(), 165.7)

    def test_default_course_budget_uses_bloc_calibration_from_fish_audio_samples(self):
        playlist = [
            ("cours_9h00_9h45.mp3", 2700, "cours", 1),
            ("cours_16h00_17h00.mp3", 3600, "cours", 6),
        ]

        with patch.dict(os.environ, {}, clear=True), patch.object(
            cgs, "_course_preflight_safety", return_value=1.0
        ), patch.object(cgs, "_course_final_silence_sec", return_value=120.0):
            budget = cgs.get_course_day_word_budget(playlist)

        expected_c1 = int(((2700 - 120 - 17) / 60) * 199.9)
        expected_c6 = int(((3600 - 120 - 17) / 60) * 213.9)
        self.assertEqual(budget["target_words"], expected_c1 + expected_c6)
        self.assertEqual(budget["course_items"][0]["target_words"], expected_c1)
        self.assertEqual(budget["course_items"][1]["target_words"], expected_c6)

    def test_actual_reading_summary_exposes_wpm_and_text_read(self):
        meta = {
            "provider": "fish_audio",
            "endpoint": "stream_with_timestamp",
            "model": "s2-pro",
            "format": "mp3",
            "speed": 0.9,
            "audio_duration_sec": 30,
            "spoken_word_count": 90,
            "words_per_minute": 180,
            "text_read": "Bonjour tout le monde",
            "timeline": [{"text": "Bonjour", "start": 0, "end": 0.3}],
            "chunks": [{"chunk_seq": 0}],
        }

        summary = cgs._fish_actual_reading_summary(
            meta,
            input_text="Bonjour [pause] tout le monde",
        )

        self.assertEqual(summary["input_spoken_word_count"], 4)
        self.assertEqual(summary["fish_segment_word_count"], 90)
        self.assertEqual(summary["words_per_minute"], 180)
        self.assertEqual(summary["words_per_hour"], 10800)
        self.assertEqual(summary["text_read"], "Bonjour tout le monde")

    def test_actual_reading_from_attempts_aggregates_slide_chunks(self):
        attempts = [
            {
                "kind": "fish_audio_timestamped_speed=0.9",
                "actual_reading": {
                    "audio_duration_sec": 10,
                    "input_spoken_word_count": 20,
                    "fish_segment_word_count": 20,
                    "words_per_minute": 120,
                    "text_read": "premier chunk",
                    "timeline": [{"text": "premier", "start": 0, "end": 0.5}],
                    "audio_start_sec": 17,
                },
            },
            {
                "kind": "fish_audio_timestamped_speed=0.9",
                "actual_reading": {
                    "audio_duration_sec": 20,
                    "input_spoken_word_count": 40,
                    "fish_segment_word_count": 40,
                    "words_per_minute": 120,
                    "text_read": "deuxième chunk",
                    "timeline": [{"text": "deuxième", "start": 0, "end": 0.5}],
                    "audio_start_sec": 27,
                },
            },
        ]

        actual = cgs._actual_reading_from_attempts(attempts)

        self.assertEqual(actual["input_spoken_word_count"], 60)
        self.assertEqual(actual["fish_segment_word_count"], 60)
        self.assertEqual(actual["audio_duration_sec"], 30)
        self.assertEqual(actual["words_per_minute"], 120)
        self.assertEqual(actual["timeline"][0]["start"], 17)
        self.assertEqual(actual["timeline"][1]["start"], 27)

    def test_audio_block_markers_are_not_counted_as_spoken_words(self):
        text = "<<<BLOC_AUDIO_1>>>\n\nBonjour [pause] à tous."

        self.assertEqual(cgs.count_tts_spoken_words(text), 3)

    def test_marked_audio_blocks_bypass_proportional_split(self):
        segments = [
            {
                "sub_idx": i,
                "passe": 1,
                "text": f"<<<BLOC_AUDIO_{i + 1}>>>\n\ntexte bloc {i + 1}",
                "word_count": 3,
                "dirty": i == 0,
            }
            for i in range(7)
        ]
        playlist = [
            (f"cours_{i}.mp3", 2700, "cours", i)
            for i in range(1, 8)
        ]
        durations = {i: 45 for i in range(1, 8)}

        blocs, total_words, carryover = cgs._build_course_blocs_from_segments(
            segments,
            durations,
            playlist,
            preview=True,
        )

        self.assertEqual(len(blocs), 7)
        self.assertEqual(total_words, 21)
        self.assertEqual(carryover, "")
        self.assertEqual(blocs[0]["text"], "texte bloc 1")
        self.assertNotIn("<<<BLOC_AUDIO_", blocs[0]["text"])
        self.assertTrue(blocs[0]["audio_block_marked"])

    def test_block_calibration_fallback_keeps_text_untrimmed(self):
        overlong = " ".join(["mot"] * 120) + "."
        block = {
            "bloc_number": 1,
            "filename": "cours.mp3",
            "min_words": 40,
            "max_words": 80,
            "target_words": 80,
            "duration_min": 45,
            "role": "test",
        }

        with patch.object(cgs, "_anthropic_post", return_value=overlong):
            calibrated, result = cgs._calibrate_single_audio_block(
                block=block,
                text=overlong,
                max_iterations=1,
            )

        self.assertEqual(calibrated, overlong)
        self.assertGreater(cgs.count_tts_spoken_words(calibrated), block["max_words"])
        self.assertEqual(result["status"], "over_budget")
        self.assertEqual(result["fallback"], "llm_only_over_budget_kept_untrimmed")

    def test_45_minute_budget_uses_single_canonical_block_budget(self):
        # 192 mots/min, 17s de silence initial et la marge finale courante.
        # Plus de réserve conclusion runtime : budget principal = budget total.
        with patch.object(cgs, "_course_words_per_minute", return_value=192.0), patch.object(
            cgs, "_course_preflight_safety", return_value=1.0
        ):
            main_budget = cgs._estimated_main_words_budget_for_course(2700, api_speed=0.95)
            total_budget = cgs._estimated_words_budget_for_course(2700, api_speed=0.95)

        expected = int(((2700 - cgs._course_final_silence_sec() - 17) / 60) * 192)
        self.assertEqual(main_budget, expected)
        self.assertEqual(total_budget, expected)

    def test_day_budget_uses_only_course_playlist_items(self):
        playlist = [
            ("cours_1.mp3", 2700, "cours", 1),
            ("qa_1.mp3", 900, "qa", 1),
            ("pause_1.mp3", 600, "pause", 1),
        ]

        with patch.object(cgs, "_course_words_per_minute", return_value=192.0), patch.object(
            cgs, "_course_preflight_safety", return_value=1.0
        ), patch.object(cgs, "_course_final_silence_sec", return_value=120.0):
            budget = cgs.get_course_day_word_budget(playlist)

        expected = int(((2700 - 120 - 17) / 60) * 192)
        self.assertEqual(budget["target_words"], expected)
        self.assertEqual(budget["course_seconds"], 2700)
        self.assertEqual(len(budget["course_items"]), 1)

    def test_final_day_word_budget_guard_rejects_overflow(self):
        text = " ".join(["mot"] * 112)
        small_budget = {
            "target_words": 100,
            "min_words": 90,
            "max_words": 110,
            "words_per_minute": 192.0,
            "course_seconds": 60,
            "speakable_seconds": 50,
            "start_silence_sec": 17,
            "final_silence_sec": 120,
            "course_items": [],
        }

        completed_rows = [{
            "id": 1,
            "sub_part_index": 0,
            "sub_part_name": "Intro",
            "passe": 1,
            "text_content": text,
            "word_count": len(text.split()),
            "dirty": 0,
        }]
        with patch.object(
            cgs, "list_completed_content_segment_rows", return_value=completed_rows
        ), patch.object(
            cgs, "get_job_from_db", return_value={"id": 20, "carryover_in_text": ""}
        ), patch.object(
            cgs, "get_course_day_word_budget", return_value=small_budget
        ):
            audit = cgs.compute_course_day_word_budget_audit(
                10,
                job={"id": 20, "carryover_in_text": ""},
            )
            self.assertFalse(audit["ok"])
            self.assertEqual(audit["status"], "over_budget")
            with self.assertRaisesRegex(ValueError, "dépasse"):
                cgs.assert_course_day_word_budget(10, context="test")


class CourseSpeechDeadlineTest(unittest.TestCase):
    def test_fish_audio_rejects_voice_after_final_silence_deadline(self):
        bloc = _make_bloc("texte court pour fish audio.", target_sec=2700)
        raw_voice_duration = cgs._course_voice_window_sec(2700) + 1.0
        pad = Mock()

        with self.assertRaisesRegex(ValueError, "silence final"):
            cgs._synthesize_course_audio_to_fit(
                bloc,
                convert_to_speech=lambda text, speed: b"MP3",
                measure_duration_ms=lambda audio: raw_voice_duration * 1000,
                pad_audio_to_duration=pad,
            )

        pad.assert_not_called()

    def test_review_budget_guard_rolls_back_oversized_humanization_patch(self):
        original = " ".join(["mot"] * 100)
        candidate = " ".join(["mot"] * 500)
        applied = [{
            "original": "mot mot mot",
            "replacement": "long remplacement",
            "rule_violated": "#101",
            "reason": "Trop brusque.",
        }]

        guarded_text, guarded_applied, rejected = cgs._apply_review_budget_guard(
            original,
            candidate,
            applied,
            "humanization",
        )

        self.assertEqual(guarded_text, original)
        self.assertEqual(guarded_applied, [])
        self.assertEqual(rejected[0]["reject_reason"], "budget_guard")
        self.assertGreater(rejected[0]["words_after"], rejected[0]["max_words"])


class HumanizationReviewRulesTest(unittest.TestCase):
    def test_review_includes_humanization_rule_group(self):
        group = next(
            (g for g in cgs._HUMANIZATION_REVIEW_RULE_GROUPS if g["id"] == "humanisation_polish"),
            None,
        )
        self.assertIsNotNone(group)
        self.assertIn(101, group["rules"])
        self.assertIn(111, group["rules"])
        rules_text = cgs._load_review_rules()
        self.assertIn("RÈGLE #101", rules_text)
        self.assertIn("RÈGLE #111", rules_text)

    def test_each_review_group_extracts_rules(self):
        rules_text = cgs._load_review_rules()
        for group in cgs._COMPLIANCE_REVIEW_RULE_GROUPS + cgs._HUMANIZATION_REVIEW_RULE_GROUPS:
            with self.subTest(group=group["id"]):
                extracted = cgs._extract_rules_for_group(rules_text, group["rules"])
                self.assertIn(f"RÈGLE #{group['rules'][0]}", extracted)

    def test_humanization_prompt_can_propose_rhythm_corrections(self):
        rules_text = cgs._extract_rules_for_group(
            cgs._load_review_rules(),
            [101, 102, 103],
        )
        prompt = cgs._build_review_prompt_focused(
            "Bonjour à tous. On entre maintenant dans le vif du sujet.",
            rules_text,
            "Humanisation et rythme pédagogique",
            "Intros plus douces, respirations et transitions",
            [101, 102, 103],
        )

        self.assertIn("finition orale légère", prompt)
        self.assertIn("micro-interaction", prompt)
        self.assertIn("Pas de réécriture complète", prompt)

    def test_review_group_fails_when_rules_are_missing(self):
        group = {
            "id": "missing",
            "label": "Règles absentes",
            "rules": [999],
            "description": "test",
        }

        with patch.object(cgs, "_review_chunk_with_retries") as reviewer:
            updated, applied, rejected, error, proposed = cgs._review_group_chunks(
                "Bonjour. On commence directement.",
                "",
                group,
            )

        self.assertEqual(updated, "Bonjour. On commence directement.")
        self.assertEqual(applied, [])
        self.assertEqual(rejected, [])
        self.assertEqual(proposed, 0)
        self.assertIn("Règles introuvables", error)
        reviewer.assert_not_called()

    def test_review_signature_depends_on_rules_text(self):
        sig_a = cgs._review_rules_signature("RÈGLE #1")
        sig_b = cgs._review_rules_signature("RÈGLE #1 modifiée")

        self.assertNotEqual(sig_a, sig_b)
        self.assertEqual(len(sig_a), 64)


class ContentReviewSignatureSelectionTest(unittest.TestCase):
    def _make_db(self, signature):
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.close()
        conn = sqlite3.connect(tmp.name)
        conn.execute(
            """
            CREATE TABLE content_generation_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                sub_part_index INTEGER NOT NULL,
                sub_part_name TEXT NOT NULL,
                passe INTEGER NOT NULL,
                status TEXT DEFAULT 'completed',
                text_content TEXT DEFAULT '',
                word_count INTEGER DEFAULT 0,
                dirty INTEGER DEFAULT 0,
                reviewed INTEGER DEFAULT 0,
                review_error TEXT,
                review_signature TEXT,
                humanized INTEGER DEFAULT 0,
                humanization_error TEXT,
                humanization_signature TEXT,
                text_content_pre_review TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO content_generation_segments
                (job_id, sub_part_index, sub_part_name, passe, status,
                 text_content, word_count, dirty, reviewed, review_signature)
            VALUES (1, 0, 'Intro', 1, 'completed',
                    'Bonjour. On commence directement.', 4, 0, 1, ?)
            """,
            (signature,),
        )
        conn.commit()
        conn.close()
        return tmp.name

    def _run_review_on_db(self, db_path, rules_text):
        calls = []

        def connect():
            return sqlite3.connect(db_path)

        def fake_group_review(current_text, _rules_text, group, model=None):
            calls.append(group["id"])
            return current_text, [], [], None, 0

        with patch.object(cgs, "get_job_from_db", return_value={"id": 1, "formation_job_id": 9}), patch.object(
            pipeline_repo, "get_db_connection", side_effect=connect
        ), patch.object(cgs, "_load_review_rules", return_value=rules_text), patch.object(
            cgs, "_ensure_review_state_columns"
        ), patch.object(
            cgs, "_save_reviewed_scripts_artifact"
        ), patch.object(cgs, "_review_group_chunks", side_effect=fake_group_review):
            result = cgs.run_content_review(123)

        return result, calls

    def test_stale_reviewed_segment_is_reprocessed_and_signed(self):
        db_path = self._make_db("old-signature")
        try:
            result, calls = self._run_review_on_db(db_path, "RÈGLE #1 — test")

            conn = sqlite3.connect(db_path)
            reviewed, signature = conn.execute(
                "SELECT reviewed, review_signature FROM content_generation_segments WHERE id = 1"
            ).fetchone()
            conn.close()

            self.assertEqual(result["segments_reviewed"], 1)
            self.assertEqual(calls, [g["id"] for g in cgs._COMPLIANCE_REVIEW_RULE_GROUPS])
            self.assertEqual(reviewed, 1)
            self.assertEqual(signature, result["review_signature"])
        finally:
            os.unlink(db_path)

    def test_current_review_signature_skips_segment(self):
        rules_text = "RÈGLE #1 — test"
        current_signature = cgs._review_rules_signature(
            rules_text + cgs._ethical_lexical_signature_text(),
            groups=cgs._compliance_review_groups_for_final_pass(),
            version=cgs._REVIEW_RULESET_VERSION,
        )
        db_path = self._make_db(current_signature)
        try:
            result, calls = self._run_review_on_db(db_path, rules_text)

            self.assertEqual(result["segments_reviewed"], 0)
            self.assertEqual(result["segments_already_current"], 1)
            self.assertEqual(calls, [])
        finally:
            os.unlink(db_path)

    def test_humanization_patch_invalidates_compliance_review(self):
        rules_text = "RÈGLE #101 — test"
        current_compliance_signature = cgs._current_compliance_review_signature()
        db_path = self._make_db(current_compliance_signature)
        try:
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                UPDATE content_generation_segments
                SET reviewed = 1, review_signature = ?
                WHERE id = 1
                """,
                (current_compliance_signature,),
            )
            conn.commit()
            conn.close()

            def connect():
                return sqlite3.connect(db_path)

            def fake_group_review(current_text, _rules_text, group, model=None):
                return (
                    "Bonjour. [pause] On commence tranquillement.",
                    [{
                        "original": "Bonjour. On commence directement.",
                        "replacement": "Bonjour. [pause] On commence tranquillement.",
                        "rule_violated": "#101",
                        "reason": "Début trop brusque.",
                    }],
                    [],
                    None,
                    1,
                )

            with patch.object(cgs, "get_job_from_db", return_value={"id": 1, "formation_job_id": 9}), patch.object(
                pipeline_repo, "get_db_connection", side_effect=connect
            ), patch.object(cgs, "_load_review_rules", return_value=rules_text), patch.object(
                cgs, "_ensure_review_state_columns"
            ), patch.object(
                cgs, "_save_reviewed_scripts_artifact"
            ), patch.object(cgs, "_review_group_chunks", side_effect=fake_group_review):
                result = cgs.run_humanization_review(123)

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                """
                SELECT humanized, humanization_signature, reviewed, review_signature,
                       dirty, text_content
                FROM content_generation_segments WHERE id = 1
                """
            ).fetchone()
            conn.close()

            self.assertEqual(result["review_kind"], "humanization")
            self.assertEqual(result["patches_applied"], 1)
            self.assertEqual(row[0], 1)
            self.assertEqual(row[1], result["review_signature"])
            self.assertEqual(row[2], 0)
            self.assertIsNone(row[3])
            self.assertEqual(row[4], 1)
            self.assertIn("[pause]", row[5])
        finally:
            os.unlink(db_path)


class ConclusionAppendedAfterStopTest(unittest.TestCase):
    def test_runtime_fit_does_not_append_conclusion_or_extend_timing(self):
        text = _phrases_text(n_phrases=200, words_per_phrase=7)
        bloc = _make_bloc(text, target_sec=2700)
        # Chunk slide explicite avec slide_id pour exercer l'extension du
        # timing (sinon `_merge_adjacent_slide_timings` filtre les timings
        # sans slide_id).
        fake_slide_chunk = {
            "slide_id": "slide-test",
            "word_start": 0,
            "word_end": len(text.split()),
            "text": text,
        }

        with patch.object(
            cgs, "_build_slide_audio_chunks", return_value=[fake_slide_chunk],
        ), patch(
            "services.basic_tts_service.convert_to_speech_basic",
            return_value=_mp3_chunk("VOICE"),
        ), patch.object(
            cgs, "_mp3_duration_seconds_no_ffprobe", return_value=1500.0,
        ), patch.object(
            cgs, "_synthesize_short_conclusion_audio",
            return_value=(_mp3_chunk("CONCL"), 7.5),
        ) as conclusion:
            (
                audio_bytes, voice_duration, fit_method,
                attempts, timings, unconsumed, consumed,
            ) = cgs._synthesize_course_audio_synced_to_slides(
                bloc, [], "cours.mp3",
                mock=False, basic_tts=True,
                runtime_fit=True,
                conclusion_margin_sec=90,
            )

        kinds = [a.get("kind") for a in attempts]
        self.assertNotIn("conclusion", kinds, f"attempts kinds={kinds}")
        conclusion.assert_not_called()

        self.assertTrue(timings, "Au moins un timing slide attendu")
        last = timings[-1]
        self.assertAlmostEqual(last["duration"], 1500.0, places=2)


class PrependedChunksConsumedFirstTest(unittest.TestCase):
    def test_disabled_runtime_fit_ignores_legacy_prepended_chunks(self):
        bloc = _make_bloc("phrase du bloc principal.", target_sec=2700)
        prepended = [{
            "slide_id": "from-previous",
            "word_start": 0,
            "word_end": 5,
            "text": "carryover du bloc précédent.",
        }]

        # Un ancien carryover ne doit plus altérer le texte canonique du bloc.
        seen_texts = []

        def fake_tts(text, **kwargs):
            seen_texts.append(text)
            return _mp3_chunk("X")

        with patch(
            "services.basic_tts_service.convert_to_speech_basic",
            side_effect=fake_tts,
        ), patch.object(
            cgs, "_mp3_duration_seconds_no_ffprobe", return_value=10.0,
        ), patch.object(
            cgs, "_edge_muted_padding_audio",
            return_value=(_mp3_chunk("PAD"), 2690.0),
        ):
            cgs._synthesize_course_audio_synced_to_slides(
                bloc, [], "cours.mp3",
                mock=False, basic_tts=True,
                runtime_fit=True,
                prepended_chunks=prepended,
                conclusion_margin_sec=90,
            )

        self.assertEqual(len(seen_texts), 1)
        self.assertNotIn("carryover", seen_texts[0])
        self.assertIn("bloc principal", seen_texts[0])


class NoRuntimeFitReturnsEmptyUnconsumedTest(unittest.TestCase):
    def test_default_path_has_no_carryover(self):
        text = "court contenu de bloc."
        bloc = _make_bloc(text, target_sec=2700)

        with patch(
            "services.basic_tts_service.convert_to_speech_basic",
            return_value=_mp3_chunk("VOICE"),
        ), patch.object(
            cgs, "_mp3_duration_seconds_no_ffprobe", return_value=3.0,
        ):
            (
                audio_bytes, voice_duration, fit_method,
                attempts, timings, unconsumed, consumed,
            ) = cgs._synthesize_course_audio_synced_to_slides(
                bloc, [], "cours.mp3",
                mock=False, basic_tts=True,
                # runtime_fit non passé → par défaut False
            )

        self.assertEqual(fit_method, "slide_sync_edge_no_padding")
        self.assertEqual(unconsumed, [])
        self.assertEqual(consumed, [])


class ConcatMp3BytesUsedSingleId3Test(unittest.TestCase):
    def test_only_one_id3_header_in_final_output(self):
        # Plusieurs chunks générés via runtime fit → vérifier que concat_mp3_bytes
        # retire les ID3 intermédiaires (1 seul header dans le résultat final,
        # même quand la conclusion est ajoutée).
        text = _phrases_text(n_phrases=200, words_per_phrase=7)
        bloc = _make_bloc(text, target_sec=2700)

        with patch(
            "services.basic_tts_service.convert_to_speech_basic",
            return_value=_mp3_chunk("VOICE"),
        ), patch.object(
            cgs, "_mp3_duration_seconds_no_ffprobe", return_value=1500.0,
        ), patch.object(
            cgs, "_synthesize_short_conclusion_audio",
            return_value=(_mp3_chunk("CONCL"), 5.0),
        ):
            (
                audio_bytes, *_rest,
            ) = cgs._synthesize_course_audio_synced_to_slides(
                bloc, [], "cours.mp3",
                mock=False, basic_tts=True,
                runtime_fit=True,
                conclusion_margin_sec=90,
            )

        self.assertEqual(
            audio_bytes.count(b"ID3"), 1,
            "concat_mp3_bytes doit retirer les ID3 intermédiaires "
            f"(found {audio_bytes.count(b'ID3')})",
        )


class RuntimeFitRejectsMeasuredOverflowTest(unittest.TestCase):
    def test_runtime_fit_flag_does_not_drop_overlong_text(self):
        text = " ".join(["mot"] * 100) + "."
        bloc = _make_bloc(text, target_sec=150)

        with patch(
            "services.basic_tts_service.convert_to_speech_basic",
            return_value=_mp3_chunk("VOICE"),
        ), patch.object(
            cgs, "_mp3_duration_seconds_no_ffprobe", return_value=140.0,
        ), patch.object(
            cgs, "_synthesize_short_conclusion_audio",
            return_value=(_mp3_chunk("CONCL"), 5.0),
        ), patch.object(
            cgs, "_edge_muted_padding_audio",
            return_value=(_mp3_chunk("PAD"), 80.0),
        ):
            result = cgs._synthesize_course_audio_synced_to_slides(
                bloc, [], "cours.mp3",
                mock=False, basic_tts=True,
                runtime_fit=True,
                conclusion_margin_sec=90,
            )

        self.assertEqual(result[1], 140.0)
        self.assertEqual(result[2], "slide_sync_edge_no_padding")
        self.assertEqual(result[5], [])
        self.assertEqual(result[6], [])


class RuntimeFitConclusionFallbackTest(unittest.TestCase):
    def test_runtime_fit_does_not_use_conclusion_fallback(self):
        text = _phrases_text(n_phrases=80, words_per_phrase=7)
        bloc = _make_bloc(text, target_sec=250)

        with patch(
            "services.basic_tts_service.convert_to_speech_basic",
            return_value=_mp3_chunk("VOICE"),
        ), patch.object(
            cgs, "_mp3_duration_seconds_no_ffprobe", return_value=100.0,
        ), patch.object(
            cgs, "_synthesize_short_conclusion_audio",
            side_effect=[
                (_mp3_chunk("LONG"), 200.0),
                (_mp3_chunk("SHORT"), 5.0),
            ],
        ) as conclusion:
            (
                audio_bytes, voice_duration, fit_method,
                attempts, timings, unconsumed, consumed,
            ) = cgs._synthesize_course_audio_synced_to_slides(
                bloc, [], "cours.mp3",
                mock=False, basic_tts=True,
                runtime_fit=True,
                conclusion_margin_sec=90,
            )

        kinds = [a["kind"] for a in attempts]
        self.assertNotIn("conclusion_rejected_overflow", kinds)
        self.assertNotIn("conclusion_fallback", kinds)
        conclusion.assert_not_called()
        self.assertLessEqual(
            voice_duration,
            cgs._course_speech_deadline_sec(250) + cgs._TOLERANCE_OVERFLOW_SEC,
        )
        self.assertNotIn(b"SHORT", audio_bytes)
        self.assertNotIn(b"LONG", audio_bytes)


class RuntimeFitMicroChunkRefinementTest(unittest.TestCase):
    def test_runtime_fit_flag_does_not_split_canonical_chunk(self):
        sentence = " ".join(["mot"] * 20) + "."
        text = " ".join([sentence, sentence, sentence])
        bloc = _make_bloc(text, target_sec=170)
        fake_slide_chunk = {
            "slide_id": "slide-test",
            "word_start": 0,
            "word_end": len(text.split()),
            "text": text,
        }

        with patch.object(
            cgs, "_build_slide_audio_chunks", return_value=[fake_slide_chunk],
        ), patch(
            "services.basic_tts_service.convert_to_speech_basic",
            return_value=_mp3_chunk("VOICE"),
        ), patch.object(
            cgs, "_mp3_duration_seconds_no_ffprobe",
            return_value=120.0,
        ), patch.object(
            cgs, "_edge_muted_padding_audio",
            return_value=(_mp3_chunk("PAD"), 90.0),
        ):
            (
                audio_bytes, voice_duration, fit_method,
                attempts, timings, unconsumed, consumed,
            ) = cgs._synthesize_course_audio_synced_to_slides(
                bloc, [], "cours.mp3",
                mock=False, basic_tts=True,
                runtime_fit=True,
                conclusion_margin_sec=90,
            )

        kinds = [a["kind"] for a in attempts]
        self.assertEqual(kinds.count("gtts"), 1)
        self.assertNotIn("gtts_split_after_measured_overflow", kinds)
        self.assertNotIn("conclusion", kinds)
        self.assertEqual(consumed, [])
        self.assertEqual(unconsumed, [])
        self.assertEqual(voice_duration, 120.0)


class RuntimeFitFinalizeSafetyTest(unittest.TestCase):
    def test_dirty_marking_waits_until_carryover_is_persisted(self):
        with patch.object(
            cgs, "_store_cross_day_carryover", side_effect=RuntimeError("boom")
        ), patch.object(cgs, "_mark_content_segments_clean") as mark_clean:
            with self.assertRaises(RuntimeError):
                cgs._finalize_runtime_fit_carryover_and_clean(
                    job_id=3,
                    pending_clean_seg_keys={(0, 1)},
                    runtime_carryover_text="texte reporte",
                    carryover_out="",
                    folder_id=9,
                    next_folder_id=10,
                    is_last_folder=False,
                    formation_job_id=5,
                )

        mark_clean.assert_not_called()


class ContextualBreakUsesConsumedTextTest(unittest.TestCase):
    def test_fixed_break_ignores_legacy_runtime_consumed_text(self):
        blocs_by_number = {
            1: {
                "text": "texte complet avec partie reportee",
                "runtime_consumed_text": "texte reellement enseigne",
            },
            2: {
                "text": "prochain texte complet",
                "runtime_consumed_text": "prochain texte consomme",
            },
        }

        with patch(
            "services.break_transition_service.build_break_transition_texts",
            side_effect=AssertionError("un script fixe ne doit pas appeler le LLM"),
        ), patch(
            "services.playlist_tts_service._build_pause_audio",
            return_value=b"AUDIO",
        ):
            audio_bytes, mode = cgs._build_contextual_break_audio(
                filename="qa_9h45_9h55.mp3",
                duration_sec=600,
                file_type="qa",
                bloc_num=1,
                item_idx=1,
                playlist_items=[
                    ("cours.mp3", 2700, "cours", 1),
                    ("qa_9h45_9h55.mp3", 600, "qa", 1),
                    ("cours2.mp3", 2700, "cours", 2),
                ],
                blocs_by_number=blocs_by_number,
                mock=False,
                basic_tts=False,
                use_runtime_consumed_text=True,
            )

        self.assertEqual(audio_bytes, b"AUDIO")
        self.assertEqual(mode, "fixed_fish")


class BreakTransitionOwnershipTest(unittest.TestCase):
    def test_qa_after_course_has_no_intro_when_previous_file_owns_transition(self):
        playlist_items = [
            ("cours_9h00_9h45.mp3", 2700, "cours", 1),
            ("qa_9h45_9h55.mp3", 600, "qa", 1),
            ("pause_9h55_10h05.mp3", 600, "pause", 1),
        ]

        with patch.object(
            bks,
            "_llm_post",
            return_value='{"intro": "Ceci devrait être déplacé.", "outro": "On clôt ce temps de questions."}',
        ):
            intro, outro = bks.build_break_transition_texts(
                filename="qa_9h45_9h55.mp3",
                duration_sec=600,
                break_type="qa",
                bloc_num=1,
                item_idx=1,
                playlist_items=playlist_items,
                get_bloc_text=lambda n: "texte du bloc",
                model="test-model",
            )

        self.assertEqual(intro, "")
        self.assertIn("questions", outro)
        self.assertIn("dix minutes de pause", outro)

    def test_pause_after_course_has_no_intro_when_previous_file_owns_transition(self):
        playlist_items = [
            ("cours_9h00_9h45.mp3", 2700, "cours", 1),
            ("pause_9h45_9h55.mp3", 600, "pause", 1),
            ("cours_9h55_10h40.mp3", 2700, "cours", 2),
        ]

        with patch.object(
            bks,
            "_llm_post",
            return_value='{"intro": "On fait une pause.", "outro": "La pause est terminée, on reprend calmement."}',
        ):
            intro, outro = bks.build_break_transition_texts(
                filename="pause_9h45_9h55.mp3",
                duration_sec=600,
                break_type="pause",
                bloc_num=1,
                item_idx=1,
                playlist_items=playlist_items,
                get_bloc_text=lambda n: "texte du bloc",
                model="test-model",
            )

        self.assertEqual(intro, "")
        self.assertIn("pause est terminée", outro)

    def test_pause_midi_after_course_has_no_intro_when_previous_file_owns_transition(self):
        playlist_items = [
            ("cours_12h20_13h05.mp3", 2700, "cours", 4),
            ("pause_midi_13h05_14h35.mp3", 5400, "pause_midi", 4),
            ("cours_14h35_15h20.mp3", 2700, "cours", 5),
        ]

        with patch.object(
            bks,
            "_llm_post",
            return_value='{"intro": "On marque la pause déjeuner.", "outro": "La pause déjeuner est terminée."}',
        ):
            intro, outro = bks.build_break_transition_texts(
                filename="pause_midi_13h05_14h35.mp3",
                duration_sec=5400,
                break_type="pause_midi",
                bloc_num=4,
                item_idx=1,
                playlist_items=playlist_items,
                get_bloc_text=lambda n: "texte du bloc",
                model="test-model",
            )

        self.assertEqual(intro, "")
        self.assertIn("pause déjeuner est terminée", outro)

    def test_first_break_without_previous_audio_has_no_intro(self):
        # Depuis 2026-06-12, les breaks ne portent jamais d'intro propre,
        # même sans audio précédent : silence au début, outro seule à la fin.
        playlist_items = [
            ("pause_9h00_9h05.mp3", 300, "pause", 1),
            ("cours_9h05_9h50.mp3", 2700, "cours", 1),
        ]

        with patch.object(
            bks,
            "_llm_post",
            return_value='{"intro": "", "outro": "On reprend ensuite."}',
        ):
            intro, outro = bks.build_break_transition_texts(
                filename="pause_9h00_9h05.mp3",
                duration_sec=300,
                break_type="pause",
                bloc_num=1,
                item_idx=0,
                playlist_items=playlist_items,
                get_bloc_text=lambda n: "texte du bloc",
                model="test-model",
            )

        self.assertEqual(intro, "")
        self.assertIn("reprend", outro)

    def test_schedule_neutral_current_audio_does_not_announce_next_break(self):
        playlist_items = [
            ("cours_12h20_13h05.mp3", 2700, "cours", 4),
            ("qa_13h05_13h15.mp3", 600, "qa", 4),
            ("pause_midi_13h15_14h45.mp3", 5400, "pause_midi", 4),
        ]

        with patch.object(
            bks,
            "_llm_post",
            return_value='{"intro": "On prend un temps pour les questions.", "outro": "On clôt ce temps de questions sans annoncer la suite."}',
        ):
            intro, outro = bks.build_break_transition_texts(
                filename="qa_13h05_13h15.mp3",
                duration_sec=600,
                break_type="qa",
                bloc_num=4,
                item_idx=1,
                playlist_items=playlist_items,
                get_bloc_text=lambda n: "texte du bloc",
                model="test-model",
            )

        self.assertEqual(intro, "")
        self.assertNotIn("pause déjeuner", outro.lower())

    def test_pause_after_qa_has_no_intro_when_previous_file_owns_transition(self):
        playlist_items = [
            ("cours_9h00_9h45.mp3", 2700, "cours", 1),
            ("qa_9h45_9h55.mp3", 600, "qa", 1),
            ("pause_9h55_10h05.mp3", 600, "pause", 1),
            ("cours_10h05_10h50.mp3", 2700, "cours", 2),
        ]

        with patch.object(
            bks,
            "_llm_post",
            return_value='{"intro": "On fait une pause.", "outro": "La pause est terminée, on reprend calmement."}',
        ):
            intro, outro = bks.build_break_transition_texts(
                filename="pause_9h55_10h05.mp3",
                duration_sec=600,
                break_type="pause",
                bloc_num=1,
                item_idx=2,
                playlist_items=playlist_items,
                get_bloc_text=lambda n: "texte du bloc",
                model="test-model",
            )

        self.assertEqual(intro, "")
        self.assertIn("pause est terminée", outro)


class BasicTTSBreaksUseEdgeVoiceTest(unittest.TestCase):
    def test_basic_tts_fixed_break_does_not_recycle_fish_audio(self):
        seen_texts = []
        seen_volumes = []

        def fake_tts(text, **kwargs):
            seen_texts.append(text)
            seen_volumes.append(kwargs.get("volume", "+0%"))
            return _mp3_chunk(f"EDGE{len(seen_texts)}")

        with patch(
            "services.basic_tts_service.convert_to_speech_basic",
            side_effect=fake_tts,
        ), patch.object(
            cgs, "_mp3_duration_seconds_no_ffprobe",
            side_effect=[4.0, 3.0, 1.0],
        ), patch(
            "services.playlist_tts_service._get_recycled_qa_pause",
            side_effect=AssertionError("ne doit pas recycler audioqapause en mode Edge"),
        ):
            audio_bytes, mode = cgs._build_contextual_break_audio(
                filename="qa_9h45_9h55.mp3",
                duration_sec=600,
                file_type="qa",
                bloc_num=1,
                item_idx=1,
                playlist_items=[
                    ("cours.mp3", 2700, "cours", 1),
                    ("qa_9h45_9h55.mp3", 600, "qa", 1),
                    ("pause_9h55_10h05.mp3", 600, "pause", 1),
                ],
                blocs_by_number={},
                mock=False,
                basic_tts=True,
            )

        self.assertEqual(mode, "fixed_edge_timed")
        self.assertEqual(len(seen_texts), 3)
        self.assertEqual(seen_volumes, ["+0%", "-100%", "-100%"])
        self.assertIn("clôt", seen_texts[0].lower())
        self.assertIn("pause", seen_texts[0].lower())
        self.assertNotIn("c'est le moment", " ".join(seen_texts).lower())
        self.assertEqual(audio_bytes.count(b"ID3"), 1)
        self.assertIn(b"EDGE1", audio_bytes)
        self.assertIn(b"EDGE2", audio_bytes)
        self.assertIn(b"EDGE3", audio_bytes)
        self.assertLess(audio_bytes.index(b"EDGE2"), audio_bytes.index(b"EDGE1"))
        self.assertLess(audio_bytes.index(b"EDGE1"), audio_bytes.index(b"EDGE3"))


class CourseOpeningRewriteTest(unittest.TestCase):
    def test_rewrites_only_opening_and_preserves_rest(self):
        bloc = _make_bloc(
            (
                "C'est un état d'esprit. C'est la promesse que vous faites au client. "
                "Il faut poser ce cadre clairement. Ensuite, on détaille les gestes "
                "professionnels qui permettent de tenir cette promesse."
            ),
            target_sec=2700,
            bloc_number=2,
        )

        with patch.object(
            cgs,
            "_course_opening_transitions_enabled",
            return_value=True,
        ), patch.object(
            cgs,
            "_llm_post",
            return_value=(
                '{"opening": "Très bien, on reprend tranquillement le fil. '
                "Dans cette partie, on va installer une idée simple : la qualité "
                "de prise en charge ne repose pas seulement sur une procédure, "
                "elle repose aussi sur une posture professionnelle.\", "
                "\"rewritten_start\": \"Pour entrer dans cette partie, on va "
                "reprendre l'idée proprement : la qualité de prise en charge "
                "est une vraie posture de service.\"}"
            ),
        ):
            rewritten, _meta = cgs._rewrite_course_opening_for_audio(
                bloc,
                [
                    ("cours_9h00_9h45.mp3", 2700, "cours", 1),
                    ("qa_9h45_9h55.mp3", 600, "qa", 1),
                    ("pause_9h55_10h05.mp3", 600, "pause", 1),
                    ("cours_10h05_10h50.mp3", 2700, "cours", 2),
                ],
                3,
                model="test-model",
            )

        opening, rest = rewritten.split("\n\n", 1)
        self.assertIn("on reprend tranquillement le fil", opening)
        self.assertNotIn("C'est un état d'esprit", opening)
        self.assertIn("Ensuite, on détaille les gestes professionnels", rest)


class HelperSplitTextNaturalKeepsLongSentenceIntactTest(unittest.TestCase):
    def test_sentence_longer_than_max_is_not_split(self):
        # Une seule phrase de 40 mots, avec max_words=10 → garde entière.
        big_sentence = " ".join(["mot"] * 40) + "."
        out = cgs._split_text_natural(big_sentence, max_words=10)
        self.assertEqual(len(out), 1)
        self.assertEqual(len(out[0].split()), 40)

    def test_paragraphs_split_on_natural_boundaries(self):
        text = (
            "Premier paragraphe court. Avec deux phrases.\n\n"
            "Deuxième paragraphe. Plus long. Avec trois phrases ici.\n\n"
            "Troisième."
        )
        out = cgs._split_text_natural(text, max_words=8)
        # 3 paragraphes → 3 sous-chunks (chacun ≤ 8 mots).
        self.assertEqual(len(out), 3)
        for sub in out:
            self.assertLessEqual(len(sub.split()), 8)

    def test_sentence_boundary_positions_still_use_sentence_end_regex(self):
        self.assertEqual(cgs._sentence_boundary_positions(["Bonjour.", "Suite"]), [1])


class HelperMaxChunkWordsAdaptiveTest(unittest.TestCase):
    def test_paliers_returned_correctly(self):
        self.assertEqual(cgs._max_chunk_words_for_remaining(1500), 600)
        self.assertEqual(cgs._max_chunk_words_for_remaining(720), 600)
        self.assertEqual(cgs._max_chunk_words_for_remaining(719), 300)
        self.assertEqual(cgs._max_chunk_words_for_remaining(300), 300)
        self.assertEqual(cgs._max_chunk_words_for_remaining(299), 150)
        self.assertEqual(cgs._max_chunk_words_for_remaining(120), 150)
        self.assertEqual(cgs._max_chunk_words_for_remaining(119), 60)
        self.assertEqual(cgs._max_chunk_words_for_remaining(25), 60)
        self.assertEqual(cgs._max_chunk_words_for_remaining(24), 0)
        self.assertEqual(cgs._max_chunk_words_for_remaining(0), 0)


class RuntimeConclusionTextTest(unittest.TestCase):
    def test_contextual_conclusion_reuses_consumed_content_and_is_longer(self):
        text = (
            "La posture d'écoute active permet de reformuler sans juger et de clarifier la demande. "
            "Le conseiller doit ensuite vérifier les informations essentielles avant de proposer une solution. "
            "Face à une tension, il ralentit le rythme, reconnaît l'émotion et garde un cadre professionnel. "
            "La clôture de l'échange sert à résumer l'accord, confirmer la prochaine étape et sécuriser le client."
        )
        conclusion = cgs._build_runtime_conclusion_text(
            [{"text": text}],
            remaining_sec=150,
            bloc_number=1,
        )

        self.assertIn("écoute active", conclusion)
        self.assertIn("Avant de s'arrêter", conclusion)
        self.assertGreater(len(conclusion.split()), 160)

    def test_runtime_conclusion_announces_next_pause_from_playlist(self):
        conclusion = cgs._build_runtime_conclusion_text(
            [{"text": "On a travaillé la posture professionnelle et la reformulation."}],
            remaining_sec=150,
            bloc_number=1,
            next_playlist_item=("pause_11h00_11h05.mp3", 300, "pause", 1),
        )

        self.assertIn("pause de cinq minutes", conclusion)


class BasicTTSParallelWorkersTest(unittest.TestCase):
    def test_parallel_workers_keep_output_order(self):
        with patch.object(
            bts,
            "_split_for_tts",
            return_value=["alpha.", "beta.", "gamma."],
        ), patch.object(
            bts,
            "_synthesize_chunk_sync",
            side_effect=lambda chunk, voice, rate, volume: _mp3_chunk(chunk[:1].upper()),
        ):
            audio = bts.convert_to_speech_basic(
                "ignored",
                parallel_workers=3,
                max_429_retries=0,
            )

        self.assertLess(audio.find(b"A"), audio.find(b"B"))
        self.assertLess(audio.find(b"B"), audio.find(b"G"))


class FastTTSModeIsolationTest(unittest.TestCase):
    def test_fast_flag_is_ignored_when_runtime_fit_is_disabled(self):
        cgs._clear_edge_tts_fast_cache_for_tests()
        text = "Une phrase courte pour le cache rapide."
        bloc = _make_bloc(text, target_sec=2700)
        seen_workers = []

        def fake_tts(text_arg, **kwargs):
            seen_workers.append(kwargs.get("parallel_workers"))
            return _mp3_chunk("VOICE")

        try:
            with patch(
                "services.basic_tts_service.convert_to_speech_basic",
                side_effect=fake_tts,
            ), patch.object(
                cgs, "_mp3_duration_seconds_no_ffprobe", return_value=3.0,
            ), patch.object(
                cgs, "_synthesize_short_conclusion_audio",
                return_value=(_mp3_chunk("CONCL"), 3.0),
            ), patch.object(
                cgs, "_edge_muted_padding_audio",
                return_value=(_mp3_chunk("PAD"), 2694.0),
            ):
                first = cgs._synthesize_course_audio_synced_to_slides(
                    bloc, [], "cours.mp3",
                    mock=False, basic_tts=True,
                    runtime_fit=True,
                    fast_tts_pipeline=True,
                    conclusion_margin_sec=90,
                )
                second = cgs._synthesize_course_audio_synced_to_slides(
                    bloc, [], "cours.mp3",
                    mock=False, basic_tts=True,
                    runtime_fit=True,
                    fast_tts_pipeline=True,
                    conclusion_margin_sec=90,
                )
        finally:
            cgs._clear_edge_tts_fast_cache_for_tests()

        self.assertEqual(first[2], "slide_sync_edge_no_padding")
        self.assertEqual(second[2], "slide_sync_edge_no_padding")
        self.assertEqual(len(seen_workers), 2)
        self.assertEqual(seen_workers, [1, 1])


class BasicTTSNoSlidesPipelineRuntimeFitTest(unittest.TestCase):
    def _patch_common(self, synth_result, uploaded):
        bloc = {
            "bloc_number": 1,
            "target_sec": 2700,
            "text": "texte du bloc",
            "word_count": 3,
            "start_w": 0,
            "end_w": 3,
            "dirty": True,
            "contributing_seg_indices": {0},
            "word_budget": 8000,
            "filename": "cours_9h00_9h45.mp3",
        }

        def fake_upload(_container, blob_path, audio_bytes):
            uploaded.append((blob_path, audio_bytes))

        patches = [
            patch.object(
                cgs,
                "get_job_from_db",
                return_value={
                    "id": 42,
                    "platform_id": 7,
                    "status": "completed",
                    "formation_job_id": 99,
                },
            ),
            patch.object(
                cgs,
                "list_completed_content_segment_rows",
                return_value=[{
                    "id": 1,
                    "sub_part_index": 0,
                    "sub_part_name": "Intro",
                    "passe": 1,
                    "text_content": "texte source",
                    "word_count": 2,
                    "dirty": 1,
                }],
            ),
            patch.object(
                cgs,
                "_build_course_blocs_from_segments",
                return_value=([bloc], 3, ""),
            ),
            patch.object(
                cgs,
                "_playlist_items_for_platform",
                return_value=[("cours_9h00_9h45.mp3", 2700, "cours", 1)],
            ),
            patch.object(cgs, "_course_opening_transitions_enabled", return_value=False),
            patch.object(
                cgs,
                "_synthesize_course_audio_synced_to_slides",
                return_value=synth_result,
            ),
            patch(
                "services.azure_blob_service.upload_blob",
                side_effect=fake_upload,
            ),
            patch.object(cgs, "_finalize_runtime_fit_carryover_and_clean", return_value=""),
            patch.object(cgs, "_save_course_script_plan"),
            patch.object(cgs, "assert_course_day_word_budget", return_value={"ok": True}),
            patch.object(cgs, "_save_content_artifact"),
            patch.object(cgs, "_load_saved_course_script_plan", return_value={}),
        ]
        return patches

    def test_basic_tts_without_slide_sync_keeps_runtime_fit_disabled(self):
        uploaded = []
        synth_result = (
            _mp3_chunk("OK"),
            2500.0,
            "slide_sync_edge_no_padding",
            [{"kind": "gtts", "duration": 2500.0}],
            [],
            [],
            [{"text": "texte consomme"}],
        )
        patches = self._patch_common(synth_result, uploaded)

        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5] as synth, patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], patch.object(cgs, "_mp3_duration_seconds_no_ffprobe", return_value=2700.0):
            result = cgs.generate_audio_from_script(
                123,
                force_all=True,
                mock=False,
                basic_tts=True,
                sync_slides=False,
                next_folder_id=124,
                is_last_folder=False,
            )

        self.assertEqual(result["generated"], 1)
        self.assertEqual(len(uploaded), 1)
        synth.assert_called_once()
        self.assertEqual(synth.call_args.kwargs["runtime_fit"], False)
        self.assertEqual(synth.call_args.args[1], [], "Le mode non-sync doit utiliser des chunks sans slides")

    def test_pre_upload_guard_rejects_overlong_basic_tts_audio(self):
        uploaded = []
        synth_result = (
            _mp3_chunk("TOO_LONG"),
            3095.0,
            "slide_sync_edge_no_padding",
            [{"kind": "gtts", "duration": 3095.0}],
            [],
            [],
            [{"text": "texte consomme"}],
        )
        patches = self._patch_common(synth_result, uploaded)

        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], patch.object(
            cgs, "_mp3_duration_seconds_no_ffprobe", return_value=3095.0
        ):
            with self.assertRaisesRegex(ValueError, "dépasse la durée autorisée"):
                cgs.generate_audio_from_script(
                    123,
                    force_all=True,
                    mock=False,
                    basic_tts=True,
                    sync_slides=False,
                    next_folder_id=124,
                    is_last_folder=False,
                )

        self.assertEqual(uploaded, [], "Un audio trop long ne doit pas être uploadé")


if __name__ == "__main__":
    unittest.main()
