"""Tests du runtime fit Edge TTS dans `_synthesize_course_audio_synced_to_slides`.

On mocke `convert_to_speech_basic`, `_mp3_duration_seconds_no_ffprobe` et
`_synthesize_short_conclusion_audio` pour piloter de manière déterministe les
durées et éviter les appels réseau Edge TTS pendant les tests.
"""

import unittest
from unittest.mock import patch

from services import content_generation_service as cgs


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
    def test_voice_duration_stays_under_target(self):
        # Bloc avec ~1400 mots de phrases courtes (sub-chunkable proprement).
        # Edge TTS mocké : chaque appel renvoie un chunk MP3 et une durée 200s.
        # target_sec=2700, conclusion_margin=90 → budget effectif ~2610s.
        # À 200s/chunk, on stoppe forcément avant épuisement de la file.
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
                audio_bytes, voice_duration, fit_method,
                attempts, timings, unconsumed,
            ) = cgs._synthesize_course_audio_synced_to_slides(
                bloc, [], "cours.mp3",
                mock=False, basic_tts=True,
                runtime_fit=True,
                conclusion_margin_sec=90,
            )

        self.assertEqual(fit_method, "slide_sync_edge_runtime_fit")
        # Tolérance technique 2s (arrondis frame MP3) + durée conclusion (5s).
        self.assertLessEqual(voice_duration, 2700 + 5 + 2)
        # On a forcément stoppé avant la fin → surplus non consommé.
        self.assertGreater(
            len(unconsumed), 0,
            "Le runtime fit doit reporter le surplus quand on dépasse",
        )


class ConclusionAppendedAfterStopTest(unittest.TestCase):
    def test_attempts_contain_conclusion_and_last_timing_extended(self):
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
        ):
            (
                audio_bytes, voice_duration, fit_method,
                attempts, timings, unconsumed,
            ) = cgs._synthesize_course_audio_synced_to_slides(
                bloc, [], "cours.mp3",
                mock=False, basic_tts=True,
                runtime_fit=True,
                conclusion_margin_sec=90,
            )

        # Une entrée "conclusion" doit avoir été ajoutée dans attempts.
        kinds = [a.get("kind") for a in attempts]
        self.assertIn("conclusion", kinds, f"attempts kinds={kinds}")
        conclusion_attempt = next(a for a in attempts if a["kind"] == "conclusion")
        self.assertEqual(conclusion_attempt["duration"], 7.5)

        # Le dernier timing slide doit être étendu pour couvrir la conclusion.
        self.assertTrue(timings, "Au moins un timing slide attendu")
        last = timings[-1]
        # Duration = chunk_duration (1500s) + conclusion (7.5s).
        self.assertAlmostEqual(last["duration"], 1500.0 + 7.5, places=2)


class PrependedChunksConsumedFirstTest(unittest.TestCase):
    def test_prepended_text_is_synthesized_before_bloc_text(self):
        bloc = _make_bloc("phrase du bloc principal.", target_sec=2700)
        prepended = [{
            "slide_id": "from-previous",
            "word_start": 0,
            "word_end": 5,
            "text": "carryover du bloc précédent.",
        }]

        # On enregistre l'ordre des appels TTS pour vérifier qui passe en 1er.
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
            cgs, "_synthesize_short_conclusion_audio",
            return_value=(_mp3_chunk("END"), 1.0),
        ):
            cgs._synthesize_course_audio_synced_to_slides(
                bloc, [], "cours.mp3",
                mock=False, basic_tts=True,
                runtime_fit=True,
                prepended_chunks=prepended,
                conclusion_margin_sec=90,
            )

        self.assertGreaterEqual(len(seen_texts), 2)
        self.assertIn("carryover", seen_texts[0])
        # Le texte du bloc principal vient après.
        self.assertIn("bloc principal", seen_texts[1])


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
                attempts, timings, unconsumed,
            ) = cgs._synthesize_course_audio_synced_to_slides(
                bloc, [], "cours.mp3",
                mock=False, basic_tts=True,
                # runtime_fit non passé → par défaut False
            )

        self.assertEqual(fit_method, "slide_sync_edge_no_padding")
        self.assertEqual(unconsumed, [])


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


class HelperMaxChunkWordsAdaptiveTest(unittest.TestCase):
    def test_paliers_returned_correctly(self):
        self.assertEqual(cgs._max_chunk_words_for_remaining(1500), 600)
        self.assertEqual(cgs._max_chunk_words_for_remaining(720), 600)
        self.assertEqual(cgs._max_chunk_words_for_remaining(719), 300)
        self.assertEqual(cgs._max_chunk_words_for_remaining(300), 300)
        self.assertEqual(cgs._max_chunk_words_for_remaining(299), 150)
        self.assertEqual(cgs._max_chunk_words_for_remaining(120), 150)
        self.assertEqual(cgs._max_chunk_words_for_remaining(119), 0)
        self.assertEqual(cgs._max_chunk_words_for_remaining(0), 0)


if __name__ == "__main__":
    unittest.main()
