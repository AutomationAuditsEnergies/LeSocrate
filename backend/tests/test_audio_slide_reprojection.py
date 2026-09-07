import unittest

from services import content_generation_service as cgs


def _slide(
    slide_id: str,
    old_start: int,
    old_end: int,
    source_text: str,
    *,
    course_number: int = 4,
) -> dict:
    return {
        "slide_id": slide_id,
        "source_text": source_text,
        "source_ref": {
            "word_start": old_start,
            "word_end": old_end,
            "word_count": old_end - old_start,
            "segments": [{"course_number": course_number}],
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
            _slide(
                "intro-slide",
                0,
                len(intro_words),
                " ".join(intro_words),
                course_number=1,
            ),
            _slide(
                "body-slide",
                len(intro_words),
                len(audio_words),
                " ".join(body_words),
                course_number=1,
            ),
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

    def test_stale_word_ranges_fall_back_to_declared_course_number(self):
        bloc = {
            "bloc_number": 4,
            "start_w": 0,
            "end_w": 12,
            "text": "un deux trois quatre cinq six sept huit neuf dix onze douze",
        }
        slides = [
            _slide("course-4-a", 1000, 1100, "texte désormais différent"),
            _slide("course-4-b", 1100, 1200, "autre texte désormais différent"),
        ]

        chunks = cgs._build_slide_audio_chunks(bloc, slides)

        self.assertEqual(
            [chunk["slide_id"] for chunk in chunks],
            ["course-4-a", "course-4-b"],
        )
        self.assertEqual(chunks[0]["word_start"], 0)
        self.assertEqual(chunks[-1]["word_end"], 12)

    def test_unmappable_slides_are_detectable_as_an_unbound_audio_chunk(self):
        bloc = {
            "bloc_number": 1,
            "start_w": 0,
            "end_w": 4,
            "text": "un deux trois quatre",
        }
        slides = [{
            "slide_id": "other-course",
            "source_text": "aucune correspondance",
            "source_ref": {
                "word_start": 100,
                "word_end": 120,
                "segments": [{"course_number": 2}],
            },
        }]

        chunks = cgs._build_slide_audio_chunks(bloc, slides)

        self.assertEqual(len(chunks), 1)
        self.assertIsNone(chunks[0]["slide_id"])

    def test_declared_course_wins_over_stale_overlapping_word_ranges(self):
        bloc = {
            "bloc_number": 1,
            "start_w": 0,
            "end_w": 8,
            "text": "un deux trois quatre cinq six sept huit",
        }
        slides = [
            {
                "slide_id": "wrong-course",
                "source_text": "ancien texte qui chevauchait ce bloc",
                "source_ref": {
                    "word_start": 0,
                    "word_end": 4,
                    "segments": [{"course_number": 2}],
                },
            },
            {
                "slide_id": "right-course",
                "source_text": "un deux trois quatre",
                "source_ref": {
                    "word_start": 0,
                    "word_end": 8,
                    "segments": [{"course_number": 1}],
                },
            },
        ]

        chunks = cgs._build_slide_audio_chunks(bloc, slides)

        self.assertEqual([chunk["slide_id"] for chunk in chunks], ["right-course"])


if __name__ == "__main__":
    unittest.main()
