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
[calm] Alors, aujourd'hui on va parler d'un sujet qui est vraiment au cœur de votre métier de vendeur en boulangerie. [pause] On va s'intéresser à ce qu'on appelle les familles de produits.

Alors justement, une famille de produits, qu'est-ce que c'est exactement ? [pause] C'est tout simplement un ensemble d'articles qui partagent des caractéristiques communes. [pause] Ça peut être leur mode de fabrication, leurs ingrédients principaux, leur texture, ou leur usage.

Concrètement, en boulangerie, on regroupe dans une même famille les produits qui relèvent du même savoir-faire. [pause] Et surtout, qui répondent aux mêmes attentes du client. [pause] Autrement dit, c'est une catégorie logique qui va vous aider, vous, à structurer votre discours. [pause] Et qui va aider le client à s'orienter dans l'offre. [pause] Vous entendrez aussi parfois les termes gamme, segment, ou catégorie de produits ; c'est la même chose.

Maintenant, prenons un peu de recul. [pause] Parce que ces familles de produits, elles ne sont pas apparues du jour au lendemain. [pause] Elles ont une histoire. Et cette histoire, elle est vraiment passionnante.

Imaginez-vous un seul instant, on est au Moyen Âge. [pause] Et déjà, les boulangers de l'époque, qu'est-ce qu'ils faisaient ? Eh bien, ils organisaient déjà leur production en grandes catégories. [pause] D'un côté, vous aviez les pains du quotidien, ceux qui nourrissaient les familles tous les jours. [pause] Et de l'autre, les préparations plus élaborées, celles qu'on réservait pour les grandes occasions, les fêtes, ou pour les classes les plus aisées. [pause] Vous voyez, la logique de familles, elle existe depuis des siècles.

Et puis, au dix-neuvième siècle, il s'est passé quelque chose de vraiment important. [pause] La viennoiserie, elle est arrivée d'Autriche. [pause] Et là, qu'est-ce qui s'est passé ? Eh bien, ça a tout changé. [pause] Le croissant, le pain au chocolat, la brioche, tout ça est venu enrichir l'offre des boulangeries françaises. [pause] Les familles de produits, elles se sont véritablement diversifiées. [pause] Et puis plus récemment, au cours des années deux mille, on a vu apparaître le bio, le sans gluten, le snacking. [pause] Encore de nouvelles familles, toujours en réponse aux nouvelles attentes des consommateurs.

Et vous allez me dire, pourquoi c'est si important de connaître ces familles, concrètement, pour vous en tant que vendeur ?

[excited] Eh bien d'abord, parce que ça vous permet de répondre avec précision aux questions des clients. [pause] Sans hésiter, sans tâtonner. [pause] Ensuite, parce que cette organisation mentale, elle vous aide à construire des argumentaires cohérents et adaptés. [pause] Imaginez-vous un seul instant un client qui va hésiter entre deux produits. [pause] Si jamais vous commencez à lui expliquer en quoi ces produits entre lesquels il hésite appartiennent à des familles différentes, avec des usages et des saveurs distinctes, là, il va comprendre votre expertise, et il sera rassuré.

Et enfin, connaître les familles, ça vous permet de pratiquer efficacement ce qu'on appelle la vente additionnelle. [pause] C'est-à-dire proposer naturellement un produit complémentaire à celui que le client est venu chercher.
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
