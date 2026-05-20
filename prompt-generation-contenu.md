# Prompt de Génération de Contenu de Formation — Process Complet

> Ce document décrit le process complet pour générer 170 000 mots de contenu
> de formation à partir d'un programme. Le contenu sera ensuite reformulé
> pour le TTS par le prompt `prompt-tts-reformulation.md`.

---

## Calculs de référence

- 14h de cours audio à 192 mots/min = **161 280 mots**
- Avec silences, pauses, transitions : **~170 000 mots** nécessaires
- Un LLM génère max ~5 000-8 000 mots par appel
- Donc il faut **~25-35 appels** au total

---

## Stratégie : 3 passes par sous-partie

Chaque sous-partie du programme passe par 3 itérations :

| Passe | Objectif | Volume | Cumul |
|-------|----------|--------|-------|
| **Passe 1 — Fondation** | Cours structuré complet | ~5 000 mots | 5 000 |
| **Passe 2 — Expansion** | Exemples, cas d'école, approfondissement | ~5 000 mots | 10 000 |
| **Passe 3 — Enrichissement** | Notions inédites, anecdotes, perspectives | ~5 000 mots | 15 000 |

Avec ~12 sous-parties par programme : 12 × 15 000 = **180 000 mots** → objectif atteint.

---

## PASSE 1 — Fondation (à exécuter pour chaque sous-partie)

```
Tu es un formateur expert qui rédige des cours de formation professionnelle
destinés à des adultes. Le contenu sera ensuite transformé en cours audio
par un logiciel text-to-speech.

CONTEXTE :
Je suis un centre de formation. Mes élèves préparent le titre professionnel
suivant : {NOM_DU_TITRE_PROFESSIONNEL}.

CONSIGNE :
Rédige un cours COMPLET et DÉTAILLÉ sur la sous-partie suivante du programme :
"{NOM_DE_LA_SOUS_PARTIE}"

Le cours doit contenir AU MINIMUM 5 000 mots et suivre cette structure :

1. Définition précise
   Définis le concept clairement. Donne 2-3 variantes de définitions
   (académique, professionnelle, vulgarisée). Délimite ce que le concept
   inclut et ce qu'il n'inclut pas.

2. Contexte historique
   D'où vient cette notion, qui l'a formalisée, comment elle a évolué.
   Cite des dates, des noms, des événements précis.

3. Importance du sujet
   Pourquoi c'est fondamental pour le métier des élèves. Les enjeux
   économiques, humains, organisationnels. Des chiffres si possible.

4. Typologies et catégories
   Les différentes formes et variantes du concept. Comment les distinguer.
   Les avantages et inconvénients de chaque type.

5. Exemples concrets
   Au minimum 4 situations détaillées avec contexte, déroulement et résultat.
   Mélange exemples positifs et négatifs.

6. Approches divergentes
   Les différentes écoles de pensée. Les débats entre professionnels.

7. Liens avec d'autres disciplines
   Comment ce sujet se connecte à d'autres domaines du programme.

8. Applications pratiques
   Comment mettre en pratique. Méthodes, outils, techniques concrètes.

9. Erreurs fréquentes et pièges
   Les 5 erreurs les plus courantes. Pour chaque : cause et solution.

10. Perspectives futures
    Tendances, innovations, évolutions à venir.

11. Conclusion et ouverture
    Résumé des points clés. Transition vers le sujet suivant.

RÈGLES DE RÉDACTION :
- Utilise le "vous" pour s'adresser aux élèves
- Ton pédagogique : explique, illustre, reformule
- Insère des transitions toutes les 800-1000 mots : "Vous m'avez bien compris.",
  "J'espère que je suis clair sur ce point.", "Très bien, on passe à la partie
  suivante."
- Pas d'exercices, pas de QCM, pas de tableaux, pas de bullet points
- Pas d'icônes ni d'emojis
- Français impeccable avec TOUS les accents (é, è, ê, à, ç, ô, etc.)
- Nombres courts en toutes lettres (dix, vingt), longs en chiffres (1 500)
- Chaque phrase doit apporter une information, jamais de remplissage creux
- Ne pas inventer de faux chiffres ou de fausses études

CONTENU ÉTHIQUE — RÈGLE ABSOLUE :
Le contenu ne doit JAMAIS faire la promotion, valoriser ou encourager
les éléments suivants :
- L'alcool (pas d'exemples avec des bars, des vignobles, des dégustations
  de vin, pas de "trinquer pour fêter", etc.)
- La musique (pas de références à des concerts, playlists, ambiance musicale)
- Les crédits à intérêts / l'usure (pas d'encouragement à emprunter avec
  intérêts, pas de "faites un crédit pour lancer votre activité")
- Les jeux de hasard et paris
- Tout contenu à caractère immoral ou indécent
- Aucune parole de kufr ou de shirk : ne jamais attribuer la création,
  la subsistance ou le pouvoir absolu à autre qu'Allah. Ne pas dire
  "la nature a créé", "le hasard a fait que", "l'univers a voulu".
  Utiliser des formulations neutres : "on observe que", "il se trouve que",
  "les études montrent que".
- Ne pas invoquer ou jurer par autre qu'Allah
- Ne pas utiliser d'expressions superstitieuses

Si un sujet du programme touche à ces domaines, traite-le de façon
NEUTRE et FACTUELLE sans en faire la promotion. Par exemple, pour la
vente de produits alimentaires, ne pas utiliser d'exemples liés à
l'alcool — utilise plutôt des exemples avec des jus, du thé, du café,
des pâtisseries, etc.
Cette règle est NON NÉGOCIABLE.

PROGRAMME DE FORMATION :
{COLLER_LE_PROGRAMME_ICI}
```

---

## PASSE 2 — Expansion (après avoir obtenu le résultat de la Passe 1)

```
Voici un cours que j'ai rédigé sur le sujet "{NOM_DE_LA_SOUS_PARTIE}"
dans le cadre de la préparation au titre professionnel
{NOM_DU_TITRE_PROFESSIONNEL}.

CONSIGNE :
Rédige 5 000 mots SUPPLÉMENTAIRES qui viennent compléter et enrichir
ce cours. Tu dois :

1. Approfondir les notions déjà abordées avec de NOUVEAUX exemples
   que tu n'as pas encore utilisés. Pour chaque notion clé du cours
   existant, ajoute au moins 2 exemples concrets supplémentaires.

2. Développer des CAS D'ÉCOLE connus et documentés :
   - Cite des entreprises réelles avec leur nom, la date, le contexte
   - Raconte l'histoire complète : problème, décision, résultat, leçon
   - Mélange grandes entreprises connues et petites structures

3. Ajouter des COMPARAISONS INTERNATIONALES :
   - Comment cette notion est-elle traitée dans d'autres pays ?
   - Quelles sont les différences culturelles ?

4. Inclure des RETOURS D'EXPÉRIENCE de professionnels du secteur :
   - Des situations vécues, des témoignages réalistes
   - Les difficultés rencontrées sur le terrain

RÈGLES :
- Ne répète PAS ce qui est déjà dans le cours existant
- Ne fais PAS d'introduction (le texte sera concaténé au cours existant)
- Continue dans le même ton et le même style
- Insère des transitions toutes les 800-1000 mots
- Français impeccable avec tous les accents
- Pas d'exercices, pas de tableaux, pas de bullet points
- Minimum 5 000 mots
- CONTENU ÉTHIQUE : ne jamais faire la promotion de l'alcool, de la musique,
  des crédits à intérêts/usure, des jeux de hasard, ni de tout contenu immoral.
  Utiliser des alternatives halal dans les exemples (jus, thé, café, pâtisseries).
  Aucune parole de kufr/shirk (ne pas attribuer la création à autre qu'Allah,
  pas de "la nature a créé", "le hasard a fait que").

COURS EXISTANT À COMPLÉTER :
{COLLER_LE_TEXTE_DE_LA_PASSE_1}
```

---

## PASSE 3 — Enrichissement (après concaténation Passe 1 + Passe 2)

```
Voici un cours complet sur le sujet "{NOM_DE_LA_SOUS_PARTIE}" dans le
cadre de la préparation au titre professionnel {NOM_DU_TITRE_PROFESSIONNEL}.

CONSIGNE :
Rédige 5 000 mots SUPPLÉMENTAIRES avec du contenu INÉDIT qui n'a pas
encore été abordé dans le cours existant. Tu dois :

1. Aborder des NOTIONS INÉDITES qui ne sont pas dans le programme mais
   qui font sens avec le sujet :
   - Psychologie comportementale et cognitive
   - Neurosciences appliquées au métier
   - Sociologie des organisations
   - Économie comportementale
   - Management et leadership
   - Éthique professionnelle

2. Raconter des ANECDOTES professionnelles détaillées et immersives.
   Le lecteur doit se sentir transporté dans la situation.

3. Faire des PONTS avec l'actualité récente (dernières années).

4. Aborder les DIMENSIONS ÉTHIQUES du sujet quand c'est pertinent.

5. Ajouter de NOUVELLES RUBRIQUES inédites que tu juges pertinentes
   pour approfondir la compréhension du sujet. Sois créatif dans le
   choix des angles d'approche.

RÈGLES :
- Ne répète RIEN de ce qui est déjà dans le cours existant
- Ne fais PAS d'introduction
- Continue dans le même ton et le même style
- Insère des transitions toutes les 800-1000 mots
- Français impeccable avec tous les accents
- Pas d'exercices, pas de tableaux, pas de bullet points, pas de cas d'étude
- Des anecdotes et des exemples uniquement
- Minimum 5 000 mots
- CONTENU ÉTHIQUE : ne jamais faire la promotion de l'alcool, de la musique,
  des crédits à intérêts/usure, des jeux de hasard, ni de tout contenu immoral.
  Utiliser des alternatives halal dans les exemples (jus, thé, café, pâtisseries).
  Aucune parole de kufr/shirk (ne pas attribuer la création à autre qu'Allah,
  pas de "la nature a créé", "le hasard a fait que").

COURS EXISTANT À NE PAS RÉPÉTER :
{COLLER_LE_TEXTE_COMPLET_PASSE_1_ET_2}
```

---

## Process complet pas à pas

### Pour chaque sous-partie du programme :

```
1. Exécuter PASSE 1 → obtenir ~5 000 mots (texte_A)
2. Exécuter PASSE 2 en fournissant texte_A → obtenir ~5 000 mots (texte_B)
3. Concaténer : texte_AB = texte_A + texte_B
4. Exécuter PASSE 3 en fournissant texte_AB → obtenir ~5 000 mots (texte_C)
5. Concaténer : texte_final = texte_A + texte_B + texte_C (~15 000 mots)
```

### Pour une formation de 14h (2 journées) :

```
Programme → identifier ~12 sous-parties

Pour chaque sous-partie (12×) :
    Passe 1 → 5 000 mots
    Passe 2 → 5 000 mots
    Passe 3 → 5 000 mots
    Total sous-partie : ~15 000 mots

Total brut : 12 × 15 000 = ~180 000 mots ✅

Ensuite :
    → Reformulation TTS (prompt-tts-reformulation.md)
    → Pipeline TTS (pipeline_tts_v2.py)
    → 14 fichiers cours MP3 (7 par jour)
```

---

## Estimation des coûts

### Pour 14h de formation (170 000 mots)

| Étape | Appels API | Coût Claude Sonnet 4 |
|-------|-----------|---------------------|
| Passe 1 (12 sous-parties) | 12 appels | ~$2.50 |
| Passe 2 (12 expansions) | 12 appels | ~$3.50 |
| Passe 3 (12 enrichissements) | 12 appels | ~$4.50 |
| **Total génération contenu** | **36 appels** | **~$10.50** |
| Reformulation TTS | ~45 chunks | ~$3.00 |
| Fish Audio TTS | ~3 000 paragraphes | ~$20.00 |
| **TOTAL PIPELINE COMPLÈTE** | | **~$33.50** |

---

## Répartition sur 2 jours

| | Jour 1 | Jour 2 |
|---|--------|--------|
| Sous-parties | 1 à 6 | 7 à 12 |
| Mots bruts | ~90 000 | ~90 000 |
| Blocs cours | 7 (45-60 min chacun) | 7 (45-60 min chacun) |
| Q&A | 7 fichiers | 7 fichiers |
| Pauses | 5 fichiers | 5 fichiers |
| **Total fichiers** | **19 MP3** | **19 MP3** |
