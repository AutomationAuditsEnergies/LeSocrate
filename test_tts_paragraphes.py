"""
Test TTS avec silence forcé entre chaque paragraphe.
On génère un audio par paragraphe, puis on assemble avec du blanc entre chaque.
"""

import requests
import os
import io
from pydub import AudioSegment
from dotenv import load_dotenv

load_dotenv("backend/.env")

API_KEY = os.getenv("FISH_AUDIO_API_KEY")
VOICE_ID = os.getenv("FISH_AUDIO_VOICE_ID", "90a39a3f3c0a45c38502fa1d99dabf96")

# Silence entre paragraphes en millisecondes
SILENCE_BETWEEN_PARAGRAPHS_MS = 500  # 0.5 secondes
SILENCE_AFTER_QUESTION_MS = 400  # 0.4 secondes après chaque ?

TEXT = """
[calm] Alors, aujourd'hui on va parler d'un sujet qui est vraiment au cœur de votre métier de vendeur en boulangerie. On va s'intéresser à ce qu'on appelle les familles de produits.

Alors justement, une famille de produits, c'est quoi au juste ? [pause] En gros, c'est quand vous avez plusieurs produits qui se ressemblent, que ce soit dans la façon dont ils sont fabriqués, dans leurs ingrédients, ou dans ce à quoi ils servent. Tout ça, on le regroupe ensemble, et ça forme une famille.

[emphasis] En boulangerie, cette logique de familles, elle est essentielle. Parce que ça vous aide, vous, à structurer votre discours quand vous êtes face à un client. [pause] Et ça aide aussi le client à s'y retrouver dans tout ce que vous proposez. [pause] D'ailleurs, vous entendrez parfois les termes gamme, segment, ou catégorie de produits ; c'est exactement la même chose.

Maintenant, prenons un peu de recul. [pause] Parce que ces familles de produits, elles ne sont pas apparues du jour au lendemain. Elles ont une histoire, et cette histoire, elle est vraiment passionnante.

[nostalgic] Imaginez-vous un seul instant, on est au Moyen Âge. Les boulangers de l'époque, ils avaient déjà cette logique-là. Ils séparaient leur production en grandes catégories. [pause] D'un côté, les pains du quotidien, ceux qui nourrissaient les familles tous les jours. De l'autre, les préparations plus élaborées, celles qu'on réservait pour les grandes occasions ou pour les classes les plus aisées. [pause] Donc vous voyez, cette organisation en familles, elle a des siècles d'existence.

[building anticipation] Au dix-neuvième siècle, il s'est passé quelque chose de vraiment important. La viennoiserie est arrivée d'Autriche. [pause] Le croissant, le pain au chocolat, la brioche, tout ça a débarqué dans les boulangeries françaises et ça a complètement transformé l'offre. Les familles se sont diversifiées comme jamais. [pause] Plus récemment, au cours des années deux mille, de nouvelles familles sont apparues : le bio, le sans gluten, le snacking. Toujours pour répondre aux nouvelles attentes des consommateurs.

Et vous allez me dire, pourquoi c'est si important de connaître ces familles, concrètement, pour vous en tant que vendeur ?

[excited] D'abord, parce que ça vous permet de répondre avec précision aux questions des clients, sans hésiter, sans tâtonner. [pause] Ensuite, parce que cette organisation mentale, elle vous aide à construire des argumentaires cohérents et adaptés. [pause] Mettez-vous à la place d'un client qui hésite entre deux produits. Si jamais vous commencez à lui expliquer en quoi ces produits appartiennent à des familles différentes, avec des usages et des saveurs distinctes, là, il va comprendre votre expertise, et il sera rassuré. [pause] [speaking with conviction] Retenez bien ça, c'est la base.

[warm and reassuring] Et puis il y a un dernier point, et celui-là il est vraiment important. Connaître les familles, ça vous permet de pratiquer ce qu'on appelle la vente additionnelle. [pause] Concrètement, c'est le fait de proposer naturellement un produit complémentaire à celui que le client est venu chercher. Par exemple, un client achète une baguette tradition, vous pouvez lui suggérer une brioche pour le lendemain matin, ou un éclair pour le dessert. [pause] Cette capacité-là, elle repose entièrement sur votre maîtrise des familles de produits.
""".strip()


def tts_paragraph(text):
    """Génère l'audio pour un seul paragraphe."""
    payload = {
        "text": text,
        "reference_id": VOICE_ID,
        "temperature": 0.9,
        "top_p": 0.7,
        "prosody": {"speed": 0.95, "volume": 0, "normalize_loudness": True},
        "chunk_length": 300,
        "normalize": False,
        "format": "mp3",
        "mp3_bitrate": 128,
        "latency": "normal",
    }
    headers = {
        "model": "s2-pro",
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.post("https://api.fish.audio/v1/tts", json=payload, headers=headers)
    if resp.status_code != 200:
        raise Exception(f"Erreur API ({resp.status_code}): {resp.text[:300]}")
    return resp.content


def split_on_questions(text):
    """Découpe un texte en morceaux : chaque '?' marque une coupure."""
    import re
    # Split sur les ? en gardant le ? dans le morceau précédent
    parts = re.split(r'(\?)', text)
    chunks = []
    current = ""
    for part in parts:
        current += part
        if part == "?":
            chunks.append(current.strip())
            current = ""
    if current.strip():
        chunks.append(current.strip())
    return chunks


def generate():
    # Découper en paragraphes (sauts de ligne)
    paragraphs = [p.strip() for p in TEXT.split("\n\n") if p.strip()]
    print(f"{len(paragraphs)} paragraphes détectés\n")

    silence_para = AudioSegment.silent(duration=SILENCE_BETWEEN_PARAGRAPHS_MS)
    silence_question = AudioSegment.silent(duration=SILENCE_AFTER_QUESTION_MS)
    full_audio = AudioSegment.empty()

    for i, para in enumerate(paragraphs):
        print(f"  [{i+1}/{len(paragraphs)}] {para[:60]}...")

        if i > 0:
            full_audio = full_audio + silence_para

        # Découper le paragraphe sur les ? pour ajouter du silence après chaque question
        question_chunks = split_on_questions(para)

        for j, chunk in enumerate(question_chunks):
            if not chunk.strip():
                continue
            audio_bytes = tts_paragraph(chunk)
            audio_segment = AudioSegment.from_mp3(io.BytesIO(audio_bytes))

            # Petit fade-out (150ms) pour adoucir la fin de chaque segment
            audio_segment = audio_segment.fade_out(150)

            full_audio = full_audio + audio_segment

            # Ajouter du silence après une question (sauf si c'est le dernier chunk)
            if chunk.strip().endswith("?") and j < len(question_chunks) - 1:
                full_audio = full_audio + silence_question

    # Export
    output_path = "test_tts_paragraphes.mp3"
    output = io.BytesIO()
    full_audio.export(output, format="mp3", bitrate="128k")

    with open(output_path, "wb") as f:
        f.write(output.getvalue())

    duration_s = len(full_audio) / 1000
    size_kb = os.path.getsize(output_path) / 1024
    print(f"\nAudio généré : {output_path} ({size_kb:.0f} KB, {duration_s:.1f}s)")
    print(f"Silence entre paragraphes : {SILENCE_BETWEEN_PARAGRAPHS_MS}ms")


if __name__ == "__main__":
    generate()
