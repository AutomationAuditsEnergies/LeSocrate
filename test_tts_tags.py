"""
Test de TOUS les types de tags Fish Audio S2-Pro.
On teste : tags documentés, free-form, paralanguage, combinaisons.
"""
import requests
import os
from dotenv import load_dotenv

load_dotenv("backend/.env")

API_KEY = os.getenv("FISH_AUDIO_API_KEY")
VOICE_ID = os.getenv("FISH_AUDIO_VOICE_ID", "90a39a3f3c0a45c38502fa1d99dabf96")

TEXT = """
Bonjour à tous, on va tester différentes façons de parler. [long pause]

Première série, les tags documentés. [long pause]

[whisper] Imaginez que je vous confie un secret, quelque chose que personne ne sait encore. [long pause]

[laugh] Ha ha, non je plaisante, c'est pas un secret du tout ! [long pause]

[emphasis] Mais par contre, ce point-là est absolument fondamental, retenez-le bien. [long pause]

[sigh] Bon, on va pas se mentir, c'est un sujet un peu complexe. [long pause]

[gasp] Et là, surprise, le résultat est complètement inattendu ! [long pause]

[excited] C'est vraiment passionnant ce qu'on découvre ici, vous allez voir ! [long pause]

[sad] Malheureusement, beaucoup de vendeurs font encore cette erreur. [long pause]

[angry] Et ça, c'est inacceptable quand on est un professionnel. [long pause]

[inhale] Alors, maintenant, la question que tout le monde se pose. [long pause]

[exhale] Voilà, c'est aussi simple que ça finalement. [long pause]

Deuxième série, les tags en langage libre. [long pause]

[speaking with conviction] Vous devez absolument maîtriser cette compétence si vous voulez progresser. [long pause]

[slightly amused] C'est un peu comme quand on essaie de faire un croissant pour la première fois, on sait pas trop par où commencer. [long pause]

[as if sharing a secret] Et entre nous, la plupart des clients ne connaissent même pas la différence. [long pause]

[building anticipation] Et maintenant, on arrive à la partie la plus intéressante de tout le cours. [long pause]

[warm and reassuring] Ne vous inquiétez pas, c'est tout à fait normal de trouver ça difficile au début. [long pause]

[nostalgic] Il y a quelques années encore, cette technique n'existait même pas. [long pause]

[speaking slowly and clearly] Alors je répète, parce que c'est vraiment important. La clé, c'est la régularité. [long pause]

[whispering mysteriously] Et c'est là que ça devient vraiment intéressant. [long pause]

[laughing nervously] Bon, j'avoue que même moi, la première fois, j'étais un peu perdu. [long pause]

[with authority] Voici les trois règles que vous devez retenir absolument. [long pause]

[gently] Prenez votre temps, il n'y a pas d'urgence, l'important c'est de bien comprendre. [long pause]

[surprised and impressed] Et figurez-vous que les résultats ont dépassé toutes les attentes ! [long pause]

Troisième série, le paralanguage. [long pause]

On va dire que, euh, parfois on hésite un peu en cherchant ses mots. [long pause]

Donc voilà, hm, c'est un sujet qui mérite qu'on s'y attarde. [long pause]

Et pour finir, une phrase normale sans aucun tag, pour comparer.
""".strip()


def generate():
    payload = {
        "text": TEXT,
        "reference_id": VOICE_ID,
        "temperature": 0.7,
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

    print(f"Envoi à Fish Audio S2-Pro... ({len(TEXT)} caractères)")
    resp = requests.post("https://api.fish.audio/v1/tts", json=payload, headers=headers)

    if resp.status_code != 200:
        print(f"ERREUR {resp.status_code}: {resp.text[:500]}")
        return

    output_path = "test_tts_tags.mp3"
    with open(output_path, "wb") as f:
        f.write(resp.content)

    size_kb = len(resp.content) / 1024
    print(f"Audio généré : {output_path} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    generate()
