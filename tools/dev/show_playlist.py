#!/usr/bin/env python3
"""
Script pour afficher la playlist détaillée des audios
avec timestamps, durées et ordre
"""

# Copie de COURS_PLAYLIST depuis config.py
COURS_PLAYLIST = [
    # === BLOC 1 : 9h00 - 10h05 ===
    {
        "id": 1,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/cours_9h00_9h45.mp3",
        "duration": 2700,  # 45 minutes = 2700 secondes
        "title": "Cours - Bloc 1 (9h00-9h45)",
        "type": "cours",
    },
    {
        "id": 2,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/qa_9h45_9h55.mp3",
        "duration": 600,  # 10 minutes = 600 secondes
        "title": "Questions-Réponses IA (9h45-9h55)",
        "type": "qa",
    },
    {
        "id": 3,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/pause_9h55_10h05.mp3",
        "duration": 600,  # 10 minutes = 600 secondes
        "title": "Pause (9h55-10h05)",
        "type": "pause",
    },
    # === BLOC 2 : 10h05 - 11h05 ===
    {
        "id": 4,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/cours_10h05_10h50.mp3",
        "duration": 2700,  # 45 minutes = 2700 secondes
        "title": "Cours - Bloc 2 (10h05-10h50)",
        "type": "cours",
    },
    {
        "id": 5,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/qa_10h50_11h00.mp3",
        "duration": 600,  # 10 minutes = 600 secondes
        "title": "Questions-Réponses IA (10h50-11h00)",
        "type": "qa",
    },
    {
        "id": 6,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/pause_11h00_11h05.mp3",
        "duration": 300,  # 5 minutes = 300 secondes
        "title": "Pause (11h00-11h05)",
        "type": "pause",
    },
    # === BLOC 3 : 11h05 - 12h20 ===
    {
        "id": 7,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/cours_11h05_12h00.mp3",
        "duration": 3300,  # 55 minutes = 3300 secondes
        "title": "Cours - Bloc 3 (11h05-12h00)",
        "type": "cours",
    },
    {
        "id": 8,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/qa_12h00_12h10.mp3",
        "duration": 600,  # 10 minutes = 600 secondes
        "title": "Questions-Réponses IA (12h00-12h10)",
        "type": "qa",
    },
    {
        "id": 9,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/pause_12h10_12h20.mp3",
        "duration": 600,  # 10 minutes = 600 secondes
        "title": "Pause (12h10-12h20)",
        "type": "pause",
    },
    # === BLOC 4 : 12h15 - 14h40 ===
    {
        "id": 10,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/pause_midi_13h15_14h45.mp3",
        "duration": 5400,  # 90 minutes = 5400 secondes
        "title": "Pause déjeuner (12h20-13h50)",
        "type": "pause_midi",
    },
    {
        "id": 11,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/cours_12h20_13h05.mp3",
        "duration": 2700,  # 45 minutes = 2700 secondes
        "title": "Cours - Bloc 4 (13h50-14h35)",
        "type": "cours",
    },
    {
        "id": 12,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/qa_13h05_13h15.mp3",
        "duration": 600,  # 10 minutes = 600 secondes
        "title": "Questions-Réponses IA (14h35-14h45)",
        "type": "qa",
    },
    # === BLOC 5 : 14h45 - 16h00 ===
    {
        "id": 13,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/cours_14h45_15h45.mp3",
        "duration": 3600,  # 60 minutes = 3600 secondes
        "title": "Cours - Bloc 5 (14h45-15h45)",
        "type": "cours",
    },
    {
        "id": 14,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/qa_15h45_16h00.mp3",
        "duration": 900,  # 15 minutes = 900 secondes
        "title": "Questions-Réponses IA (15h45-16h00)",
        "type": "qa",
    },
    # === BLOC 6 : 16h00 - 17h25 ===
    {
        "id": 15,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/cours_16h00_17h00.mp3",
        "duration": 3600,  # 60 minutes = 3600 secondes
        "title": "Cours - Bloc 6 (16h00-17h00)",
        "type": "cours",
    },
    {
        "id": 16,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/qa_17h00_17h15.mp3",
        "duration": 900,  # 15 minutes = 900 secondes
        "title": "Questions-Réponses IA (17h00-17h15)",
        "type": "qa",
    },
    {
        "id": 17,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/pause_17h15_17h25.mp3",
        "duration": 600,  # 10 minutes = 600 secondes
        "title": "Pause (17h15-17h25)",
        "type": "pause",
    },
    # === BLOC 7 : 17h25 - 18h30 ===
    {
        "id": 18,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/cours_17h25_18h15.mp3",
        "duration": 3000,  # 50 minutes = 3000 secondes
        "title": "Cours - Bloc 7 (17h25-18h15)",
        "type": "cours",
    },
    {
        "id": 19,
        "filename": "https://formationaudios-ebbgcnh0hbcxdjcq.z02.azurefd.net/audios/qa_18h15_18h30.mp3",
        "duration": 900,  # 15 minutes = 900 secondes
        "title": "Questions-Réponses IA (18h15-18h30)",
        "type": "qa",
    },
]

def format_time(seconds):
    """Convertit des secondes en format HHhMM"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours:02d}h{minutes:02d}"

def main():
    print('=' * 100)
    print('PLAYLIST COMPLÈTE DES AUDIOS - SOCRATE FORMATION')
    print('=' * 100)
    print()

    temps_cumule = 0

    for i, audio in enumerate(COURS_PLAYLIST, 1):
        temps_debut = temps_cumule
        temps_fin = temps_cumule + audio['duration']

        print(f"{i:2d}. [{format_time(temps_debut)} - {format_time(temps_fin)}] {audio['title']}")
        print(f"    ID: {audio['id']:2d} | Durée: {audio['duration']:5d}s ({audio['duration']//60:3d} min) | Type: {audio['type']}")
        print(f"    Timestamp début: {temps_debut:6d}s | Timestamp fin: {temps_fin:6d}s")
        print(f"    Fichier: {audio['filename'].split('/')[-1]}")
        print()

        temps_cumule += audio['duration']

    print('=' * 100)
    print(f"DURÉE TOTALE: {temps_cumule}s = {temps_cumule//60} minutes = {temps_cumule//3600}h{(temps_cumule%3600)//60:02d}min")
    print('=' * 100)
    print()

    # Exemple de calcul
    print("EXEMPLE:")
    print("Si le cours commence à 15h30 et qu'il est maintenant 16h03:")
    print("  → Temps écoulé: 33 minutes = 1980 secondes")
    print("  → Audio actuel: Audio #1 (cours_9h00_9h45.mp3)")
    print("  → Position dans l'audio: 1980 secondes = 33 minutes")
    print()

if __name__ == "__main__":
    main()
