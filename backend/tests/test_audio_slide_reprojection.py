import unittest

from services import content_generation_service as cgs


def _slide(slide_id: str, old_start: int, old_end: int, source_text: str) -> dict:
    return {
        "slide_id": slide_id,
        "source_text": source_text,
        "source_ref": {
            "word_start": old_start,
            "word_end": old_end,
            "word_count": old_end - old_start,
            "segments": [{"course_number": 4}],
        },
    }


class AudioSlideReprojectionTest(unittest.TestCase):
    def test_slide_windows_are_reprojected_on_final_audio_text(self):
        recap_words = [f"recap{i}" for i in range(113)]
        opener_words = (
            "Si l'on souhaite guider tout le monde avec cette même fluidité "
            "il faut se poser une question simple mais fondamentale"
        ).split()
        body_words = [f"body{i}" for i in range(80)]
        audio_words = recap_words + opener_words + body_words

        # Ancien repère slides : le cours commençait à 1000.
        old_course_start = 1000
        old_opener_start = old_course_start + len(recap_words)

        # Nouveau repère audio : le texte final TTS a 83 mots de décalage.
        audio_course_start = 1083
        bloc = {
            "bloc_number": 4,
            "start_w": audio_course_start,
            "end_w": audio_course_start + len(audio_words),
            "text": " ".join(audio_words),
        }
        slides = [
            _slide(
                "recap",
                old_course_start,
                old_opener_start,
                " ".join(recap_words),
            ),
            _slide(
                "chapter-opener",
                old_opener_start,
                old_opener_start + len(opener_words),
                " ".join(opener_words),
            ),
        ]

        chunks = cgs._build_slide_audio_chunks(bloc, slides)

        self.assertEqual([chunk["slide_id"] for chunk in chunks[:2]], ["recap", "chapter-opener"])
        self.assertEqual(chunks[0]["word_start"], audio_course_start)
        self.assertEqual(chunks[0]["word_end"], audio_course_start + len(recap_words))
        self.assertEqual(chunks[1]["word_start"], audio_course_start + len(recap_words))
        self.assertTrue(chunks[1]["text"].startswith("Si l'on souhaite guider"))

    def test_existing_fish_timeline_can_repair_slide_audio_timings(self):
        recap_words = [f"recap{i}" for i in range(113)]
        opener_words = (
            "Si l'on souhaite guider tout le monde avec cette même fluidité "
            "il faut se poser une question simple mais fondamentale"
        ).split()
        body_words = [f"body{i}" for i in range(80)]
        audio_words = recap_words + opener_words + body_words
        timeline = [
            {"text": word, "start": round(index * 0.5, 3), "end": round(index * 0.5 + 0.4, 3)}
            for index, word in enumerate(audio_words)
        ]

        old_course_start = 1000
        old_opener_start = old_course_start + len(recap_words)
        audio_course_start = 1083
        bloc = {
            "bloc_number": 4,
            "start_w": audio_course_start,
            "end_w": audio_course_start + len(audio_words),
            "text": " ".join(audio_words),
            "actual_reading": {
                "audio_duration_sec": timeline[-1]["end"],
                "timeline": timeline,
            },
        }
        slides = [
            _slide("recap", old_course_start, old_opener_start, " ".join(recap_words)),
            _slide(
                "chapter-opener",
                old_opener_start,
                old_opener_start + len(opener_words),
                " ".join(opener_words),
            ),
        ]

        timings, detail = cgs._repair_bloc_timings_from_timeline(
            bloc,
            slides,
            "cours_12h20_13h05.mp3",
        )

        self.assertEqual(detail["status"], "repaired")
        self.assertEqual([item["slide_id"] for item in timings[:2]], ["recap", "chapter-opener"])
        self.assertEqual(timings[1]["start_time"], round(len(recap_words) * 0.5, 3))
        self.assertEqual(timings[1]["repair_method"], "timeline_text_match")

    def test_missing_fish_timeline_repairs_with_word_ratio(self):
        intro_words = [f"intro{i}" for i in range(100)]
        body_words = [f"body{i}" for i in range(300)]
        audio_words = intro_words + body_words
        bloc = {
            "bloc_number": 1,
            "start_w": 0,
            "end_w": len(audio_words),
            "text": " ".join(audio_words),
            "target_duration_sec": 1200,
        }
        slides = [
            _slide("intro-slide", 0, len(intro_words), " ".join(intro_words)),
            _slide("body-slide", len(intro_words), len(audio_words), " ".join(body_words)),
        ]

        timings, detail = cgs._repair_bloc_timings_from_timeline(
            bloc,
            slides,
            "cours_9h00_9h45.mp3",
        )

        self.assertEqual(detail["status"], "repaired_by_word_ratio")
        self.assertEqual([item["slide_id"] for item in timings], ["intro-slide", "body-slide"])
        self.assertEqual(timings[0]["start_time"], 0)
        self.assertEqual(timings[0]["end_time"], 300)
        self.assertEqual(timings[1]["start_time"], 300)
        self.assertEqual(timings[1]["repair_method"], "word_ratio_no_fish_timeline")


if __name__ == "__main__":
    unittest.main()
