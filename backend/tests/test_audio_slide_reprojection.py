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


if __name__ == "__main__":
    unittest.main()
