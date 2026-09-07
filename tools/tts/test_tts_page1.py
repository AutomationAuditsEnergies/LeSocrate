"""
Test TTS Fish Audio S2-Pro -- Page 1 Module 2 reformulee pour l'oral.
Genere un fichier MP3 de test.
"""
import requests
import os
from pathlib import Path
from dotenv import load_dotenv

TOOL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / "backend" / ".env")

API_KEY = os.getenv("FISH_AUDIO_API_KEY")
VOICE_ID = os.getenv("FISH_AUDIO_VOICE_ID", "90a39a3f3c0a45c38502fa1d99dabf96")

# ── Texte reformule pour TTS (Page 1 : sections 1.1, 1.2, 1.3) ──

TEXT = """
[calm] Alors, aujourd'hui on va parler d'un sujet qui est vraiment au cœur de votre métier de vendeur en boulangerie. [pause] On va s'intéresser à ce qu'on appelle les familles de produits.

Alors justement, une famille de produits, qu'est-ce que c'est exactement ? [pause] C'est tout simplement un ensemble d'articles qui partagent des caractéristiques communes. [pause] Ça peut être leur mode de fabrication, leurs ingrédients principaux, leur texture, ou leur usage.

Concrètement, en boulangerie, on regroupe dans une même famille les produits qui relèvent du même savoir-faire. [pause] Et surtout, qui répondent aux mêmes attentes du client. [pause] Autrement dit, c'est une catégorie logique qui va vous aider, vous, à structurer votre discours. [pause] Et qui va aider le client à s'orienter dans l'offre. [pause] Vous entendrez aussi parfois les termes gamme, segment, ou catégorie de produits ; c'est la même chose.

Maintenant, prenons un peu de recul. [pause] Parce que ces familles de produits, elles ne sont pas apparues du jour au lendemain. [pause] Elles ont une histoire. Et cette histoire, elle est passionnante.

Imaginez-vous au Moyen Âge. [pause] Les boulangers de l'époque, ils organisaient déjà leur production en grandes catégories. [pause] D'un côté, vous aviez les pains du quotidien, ceux qui nourrissaient les familles tous les jours. [pause] Et de l'autre, les préparations plus élaborées, celles qu'on réservait pour les fêtes, ou pour les classes les plus aisées. [pause] Vous voyez, la logique de familles, elle existe depuis des siècles.

Et puis, au dix-neuvième siècle, il s'est passé quelque chose d'important. [pause] La viennoiserie est arrivée d'Autriche. [pause] Et là, ça a tout changé. [pause] Le croissant, le pain au chocolat, la brioche, tout ça est venu enrichir l'offre des boulangeries françaises. [pause] Les familles de produits se sont véritablement diversifiées. [pause] Et plus récemment, au cours des années deux mille, on a vu apparaître le bio, le sans gluten, le snacking. [pause] Encore de nouvelles familles, en réponse aux nouvelles attentes des consommateurs.

Et vous allez me dire, pourquoi c'est si important de connaître ces familles, concrètement, pour vous en tant que vendeur ?

[excited] Eh bien d'abord, parce que ça vous permet de répondre avec précision aux questions des clients. [pause] Sans hésiter, sans tâtonner. [pause] Ensuite, parce que cette organisation mentale vous aide à construire des argumentaires cohérents et adaptés. [pause] Imaginez un client qui hésite entre deux produits. [pause] Si vous lui expliquez clairement en quoi ils appartiennent à des familles différentes, avec des usages et des saveurs distincts, il est rassuré.

Et enfin, connaître les familles, ça vous permet de pratiquer efficacement la vente additionnelle. [pause] C'est-à-dire proposer naturellement un produit complémentaire à celui que le client est venu chercher.
""".strip()


def generate():
    payload = {
        "text": TEXT,
        "reference_id": VOICE_ID,
        "temperature": 0.7,
        "top_p": 0.7,
        "prosody": {
            "speed": 0.95,
            "volume": 0,
            "normalize_loudness": True,
        },
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

    print(f"Envoi a Fish Audio S2-Pro... ({len(TEXT)} caracteres)")
    resp = requests.post("https://api.fish.audio/v1/tts", json=payload, headers=headers)

    if resp.status_code != 200:
        print(f"ERREUR {resp.status_code}: {resp.text[:500]}")
        return

    output_path = TOOL_DIR / "test_tts_page1.mp3"
    with open(output_path, "wb") as f:
        f.write(resp.content)

    size_kb = len(resp.content) / 1024
    print(f"Audio genere: {output_path} ({size_kb:.0f} KB)")
    print(f"Ouvre le fichier pour ecouter !")


if __name__ == "__main__":
    generate()
