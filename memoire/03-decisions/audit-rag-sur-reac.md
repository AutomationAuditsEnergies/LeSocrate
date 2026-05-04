# Audit RAG : pourquoi RAG sur REAC est un mauvais outil

**Date** : 2026-04-17
**Thématique** : décision technique
**Statut** : arbitré

## Contexte

Face au problème de [dilution du REAC](../02-problemes/ratio-dilution-reac.md) sur les formations longues (14 jours et +), l'utilisateur a proposé une piste RAG : *"j'avais pensé peut-être à un RAG pour extraire à partir du REAC pour le programme global, pour le programme journée. Et quand je dis un RAG, pas nécessairement sur Azure, tu peux faire un RAG avec Obsidian, des choses dans le genre."*

Bonne intuition générale (reconnaître qu'il faut mieux structurer la source), mais appliquée au mauvais endroit.

## Question / Problème

RAG (Retrieval-Augmented Generation) sur le REAC est-il la bonne solution pour améliorer la qualité du programme ?

## Analyse

### Quand RAG est utile

Le RAG sert à **retrouver les passages pertinents dans un corpus trop volumineux pour tenir dans la fenêtre de contexte du modèle**. Canonical use-cases :
- Documentation technique de 10 000+ pages
- Base de connaissance multi-tenants
- Historique de tickets support
- Corpus juridique avec recherche conceptuelle

### Le REAC dans le cas présent

- Taille du REAC : **95 509 caractères** ≈ **15 000 mots** ≈ **~25 000 tokens**
- Fenêtre de contexte Claude Sonnet 4 : **200 000 tokens**
- Ratio : le REAC occupe **12%** de la fenêtre disponible

Le REAC entier tient aisément dans un seul prompt. RAG = chunker puis retrouver ce qu'on a déjà en main. **Complexité ajoutée sans gain fonctionnel.**

### Le vrai problème : densité, pas retrieval

Le problème n'est pas *"comment retrouver les bonnes infos du REAC"* mais *"comment produire 600k mots pertinents à partir de 15k mots source"*. Le REAC est un input dense, pas un corpus à interroger — c'est un matériau à **expandre**, pas à **retrouver**.

### Où RAG prend son sens (Couche 4)

Si on voulait enrichir avec des sources externes :
- Manuels pro du métier concerné
- Articles de blog spécialisés
- Jurisprudence / réglementation du secteur
- Fiches techniques fournisseurs

Là, un corpus peut dépasser la fenêtre de contexte et RAG devient pertinent. L'idée **Obsidian-RAG** (vault maintenu à la main par métier) est alors élégante : corpus curaté, embedding local, réutilisable.

## Décision finale

- **Couche 1 (enrichissement)** : expand le REAC via Claude, pas de RAG. Le modèle transforme 15k en 120k+ mots structurés.
- **Couche 4 (RAG Obsidian)** : envisagée plus tard, uniquement pour les métiers où le REAC enrichi ne suffit pas. Corpus externe maintenu dans Obsidian.

## Rationale technique

Règle générale retenue pour le projet : **n'utiliser RAG que quand le corpus dépasse la fenêtre de contexte du modèle**. En dessous, passer le contenu complet au modèle est plus simple, plus précis (pas de risque de rate les passages pertinents), et souvent moins cher (pas d'embedding, pas de vector DB).

Règle complémentaire : **RAG résout un problème de retrieval, pas un problème de densité**. Confondre les deux mène à des architectures inutilement complexes.

## Références code

- `backend/services/formation_pipeline_service.py` — implémentation actuelle sans RAG
- Cf. existant Azure AI Search dans le projet : utilisé pour le chat RAG utilisateur (corpus plus large : tous les PDFs cours d'une plateforme) — **bon use-case de RAG**, à opposer au cas REAC.

## Leçons / Pour le mémoire

- **Le bon outil au bon problème** : RAG est devenu un buzzword, appliqué par réflexe sur tout problème de contenu IA. Le savoir-faire architectural consiste à identifier **quand RAG est pertinent** et quand il ne l'est pas.
- **Les limites de contexte des LLMs évoluent vite** : en 2022, 4k tokens étaient une contrainte forte et le RAG était omniprésent. En 2026 avec 200k+ tokens de contexte, beaucoup de use-cases RAG historiques sont obsolètes.
- **Critique technique bienveillante** : savoir dire à l'utilisateur "ton instinct est bien placé mais l'application ne l'est pas" est plus utile que valider toutes les pistes par politesse. L'idée d'Obsidian-RAG a été retenue pour la Couche 4.
- **Distinction densité vs. retrieval** : utile à poser comme grille d'analyse pour d'autres problèmes IA génératifs.
