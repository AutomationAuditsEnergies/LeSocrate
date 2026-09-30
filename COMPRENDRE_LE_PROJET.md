# Comprendre le projet Le Socrate / Cadrenza

Ce document explique, en langage simple, ce qu'est le projet, son origine, comment il fonctionne techniquement, et où il en est. Mis à jour à partir du mémoire de fin d'études de Nassim ISSAD (EFREI Paris, 2025-2026), qui est la source la plus fiable sur l'origine et la conception du projet — écrit par la personne qui l'a conçu, validé par Mehdi Rousselle en tant que tuteur entreprise.

---

## 1. Le projet en une phrase

**Une plateforme qui génère automatiquement des formations professionnelles complètes (cours audio + slides + Q&A) à partir d'un simple numéro de titre professionnel (RNCP), avec un "professeur IA" qui remplace entièrement un formateur humain.**

---

## 2. L'histoire complète — d'où vient ce projet

### L'entreprise mère : Audits Énergies

Fondée en 2022 par **Valentin Guemache** et **Mehdi Rousselle**, à la suite de la libéralisation du marché de l'énergie (fin du monopole EDF). Son métier d'origine : le **courtage en énergie** — accompagner des entreprises pour renégocier leurs contrats d'électricité/gaz. Basée à Noisy-le-Grand, elle recrute des téléprospecteurs pour démarcher ces entreprises.

### La naissance de la formation : Sales Hacking

Pour former ses propres téléprospecteurs (communication commerciale, réglementation du secteur de l'énergie, techniques de prospection), Audits Énergies crée un centre de formation interne. Les fondateurs y développent une vraie expertise pédagogique, ce qui les pousse à lancer une **deuxième entreprise en juin 2025 : Sales Hacking**, dédiée à la formation en ligne.

**Le modèle économique est un cercle vertueux** : Audits Énergies démarche des entreprises pour le courtage énergie → une fois clientes, on leur propose aussi de former leurs salariés via Sales Hacking (formation en alternance, 1 jour/semaine, parfois sur près d'un an) → l'entreprise cliente monte ses équipes en compétence sans les mobiliser à plein temps, et bénéficie d'aides de l'État qui réduisent le coût.

### Le problème qui a tout déclenché

Produire et animer ces formations avec de vrais formateurs pose deux problèmes :
- **Économique** : les formateurs réduisent fortement la marge sur l'activité formation.
- **Organisationnel** : dépendre de plusieurs intervenants humains (rédacteurs de contenu, voix off) crée des risques de turnover et d'indisponibilité — *"l'entreprise s'est retrouvée à plusieurs reprises dans une situation où aucun intervenant n'était disponible pour préparer les contenus audio de la semaine suivante"*.

### Les tentatives successives (avant l'IA)

1. **Été 2025** : Nassim (alors stagiaire/alternant, arrivé en février 2025 sur des sujets de données) construit la **toute première version de la plateforme** — pas encore de "professeur IA", juste un système qui héberge des audios pré-enregistrés par des humains et les enchaîne automatiquement le jour J, pour simuler un cours en "faux direct".
2. Le contenu de ces audios était rédigé par des personnes suivant des prompts et méthodes conçus par Mehdi Rousselle, puis lu par une personne recrutée comme voix off. Cette organisation à plusieurs intervenants s'est révélée fragile (coordination, validations, turnover de la voix off).

C'est cette fragilité répétée qui a fait émerger l'idée du **"professeur IA"** : remplacer entièrement l'humain, pas juste l'assister.

### La construction du professeur IA (depuis février 2026)

À partir de février 2026, Nassim reprend le projet avec un objectif précis : concevoir ce professeur IA, en autonomie complète sur les choix techniques (Mehdi valide a posteriori, sans intervenir sur l'architecture). C'est ce travail qui a donné naissance au pipeline actuel de génération de formation.

### Le tournant commercial (mi-2026)

Une fois l'outil interne stabilisé, l'entreprise a engagé une deuxième étape : transformer la plateforme en un **produit SaaS vendable à d'autres centres de formation**, sous le nom **Cadrenza**. C'est un chantier technique séparé (nouvelle base de données Postgres, authentification Supabase, paiement Stripe), commencé fin juin 2026, sur lequel Nassim a aussi été le principal artisan technique.

**Aujourd'hui, il existe donc deux versions du même projet, avec des objectifs différents** : l'outil interne ("Le Socrate", utilisé quotidiennement par l'équipe pour ses propres formations) et Cadrenza (la version en cours de préparation pour la vente à des centres de formation externes).

---

## 3. Comment ça marche techniquement — le détail qui compte

### Le principe central : décomposer, pas tout générer d'un bloc

L'idée fondatrice du pipeline (expliquée en détail dans le mémoire) : **on ne peut pas demander à une IA de générer une journée entière de cours d'un coup.** Le texte serait trop long, impossible à calibrer, et impossible à synchroniser avec des slides. La solution a été de décomposer le problème sur deux axes :

- **Axe horizontal** (dans le temps) : une journée de formation est découpée en séquences audio successives — des temps de cours (45min-1h), des temps de questions-réponses (~10min), des pauses (dont le déjeuner) — qui s'enchaînent automatiquement avec des transitions naturelles ("cette question clôt notre échange, passons à la pause").
- **Axe vertical** (dans le contenu) : pour chaque séquence, on descend progressivement du général au particulier avant d'écrire le moindre mot de texte final.

### Le pipeline de génération, étape par étape

1. **Récupérer le REAC** : à partir du numéro RNCP, le système va chercher le référentiel officiel qui décrit les compétences visées par le titre professionnel (document dense et réglementaire, pas du tout pédagogique en soi).
2. **Enrichir en base de connaissances** : chaque compétence du REAC est enrichie par l'IA (définitions, cas fictifs, pièges fréquents, vocabulaire métier) pour devenir une vraie matière pédagogique.
3. **Générer le programme global** : une vision d'ensemble de la formation sur plusieurs mois — grandes lignes de chaque journée.
4. **Générer le programme journalier** : chaque journée est découpée en 7 chapitres (correspondant aux 7 audios de cours de la journée), chacun avec un thème précis.
5. **Planifier la structure de chaque chapitre AVANT d'écrire le texte** (amélioration clé de la V2 du pipeline, voir plus bas) : introduction + 2 à 4 sous-parties + conclusion, avec pour chacune les éléments à couvrir, à éviter, et **la séquence de diapositives déjà choisie** dans une bibliothèque de templates.
6. **Générer le texte bloc par bloc**, en suivant ce plan et un budget de mots calculé à partir de la vitesse de parole mesurée empiriquement de la voix choisie (c'est de là que vient le chiffre de 165,7 mots/minute qu'on retrouve dans le code).
7. **Appliquer des garde-fous** : contrôle du budget de mots, reformulation des passages problématiques (statistiques inventées, tournures mal adaptées à l'oral).
8. **Transformer le texte en audio** (Fish Audio ou Edge TTS), avec les slides déjà synchronisées puisqu'elles ont été choisies dès l'étape de planification.

### Pourquoi cette structure précise (V2) plutôt qu'une plus simple (V1) ?

La toute première version du pipeline générait le texte librement, puis essayait après coup d'associer des slides aux passages du texte. Ça posait 4 problèmes : textes trop libres (pas assez structurés), garde-fous inefficaces sur de trop gros volumes de texte, calibrage de durée imprécis, et surtout — le point le plus grave — une association texte/slides fragile et peu naturelle.

**La solution a été de tout inverser : choisir la séquence de slides D'ABORD, puis écrire le texte pour remplir ce plan déjà défini.** Ça résout les 4 problèmes en même temps : le texte suit un déroulé imposé, chaque bloc est petit donc facile à calibrer et à contrôler, et l'association texte/slide est immédiate puisque le texte est écrit exprès pour chaque slide.

### La deuxième moitié du produit : répondre aux questions des élèves

Un professeur ne fait pas que parler, il répond aussi aux questions. Pour que le "professeur IA" réponde à partir du contenu réellement enseigné (pas juste ses connaissances générales, qui pourraient être hors-sujet ou contredire le cours), le système utilise une architecture **RAG** (Retrieval-Augmented Generation) :

1. Les documents de cours sont découpés en petits passages ("chunks").
2. Chaque passage est transformé en représentation mathématique (embedding, via `text-embedding-3-small` d'OpenAI) qui capture son sens.
3. Quand un élève pose une question, elle est comparée à tous ces passages pour trouver les plus pertinents.
4. Ces passages sont donnés au modèle (GPT-4) qui rédige sa réponse à partir d'eux, pas de sa mémoire générale.

**Amélioration technique notable** : le système ne fait pas qu'une recherche "par le sens" (vectorielle) — il combine aussi une recherche "par les mots exacts" (BM25, la même famille de technique que les moteurs de recherche classiques), puis fusionne les deux résultats (technique appelée RRF). Pourquoi les deux ? Parce qu'une recherche par le sens rate parfois les codes/identifiants exacts (ex. "META-BQ9-QUALITE"), alors qu'une recherche par mots-clés rate les questions reformulées différemment du cours. Les tests réalisés par Nassim le confirment chiffres à l'appui : sur des questions reformulées, la recherche vectorielle est nettement meilleure (87,5% de rappel vs 62,5% pour la recherche par mots-clés) ; sur des questions avec un identifiant exact, c'est l'inverse (100% vs 66,7%). La recherche combinée (hybride) obtient le meilleur des deux mondes.

---

## 4. Ce qui existe déjà et fonctionne

- Le pipeline complet de génération (RNCP → programme → contenu → audio + slides synchronisées) — validé empiriquement par de nombreuses générations de formations réelles.
- Le système de questions-réponses (RAG hybride) — testé et évalué avec de bons résultats, mais **pas encore déployé auprès de vraies promotions d'élèves** au moment de la rédaction du mémoire (selon Nassim lui-même).
- Sur Cadrenza (la version commerciale) : inscription de centre de formation, paiement Stripe, système d'invitation élève sécurisé, workers séparés pour le traitement lourd — tous confirmés fonctionnels.

## Point de vigilance découvert grâce à ce document

Le mémoire de Nassim confirme que le système de questions-réponses (RAG, via Azure OpenAI + Azure Search) est **une des deux fonctions centrales du produit**, pas un détail secondaire. Or, dans l'analyse du code de Cadrenza, ces variables (`AZURE_OPENAI_*`, `AZURE_SEARCH_*`) n'apparaissaient pas dans la configuration de déploiement actuelle de Formation3 — ce qui avait été noté comme "probablement du code mort". **À la lumière de ce mémoire, ce n'est probablement pas du code mort, mais une fonctionnalité centrale qui n'a peut-être pas encore été branchée dans le déploiement commercial.** Point à vérifier en priorité : le chat/RAG fonctionne-t-il réellement pour les élèves sur Cadrenza aujourd'hui ?

## Ce qui manque encore pour vendre sereinement à plusieurs clients

- La sécurité entre centres de formation clients n'a qu'une seule ligne de défense (le code), pas de deuxième filet au niveau de la base de données — point bloquant vu le nombre réel de centres clients prévus.
- Pas encore de vraie facturation par abonnement (aujourd'hui : paiement à la commande).
- Le système de Q&A (RAG) à vérifier/rebrancher pour Cadrenza (cf. point ci-dessus).
- Pistes d'évolution notées par Nassim lui-même : réponses orales en direct (pas juste écrites), historique de conversation (RAG conversationnel), suivi individualisé des élèves avec exercices/quiz.

---

## 5. Glossaire

| Terme | Explication simple |
|---|---|
| **Audits Énergies** | L'entreprise mère, à l'origine spécialisée en courtage énergie. |
| **Sales Hacking** | La société sœur créée en juin 2025, dédiée à la formation en ligne — c'est le produit dont ce projet est l'outil. |
| **RNCP** | Le numéro officiel d'un titre professionnel (diplôme reconnu par l'État). Point de départ de toute formation générée. |
| **REAC** | Le référentiel officiel qui décrit les compétences qu'un titre RNCP doit couvrir. |
| **Chapitre** | Une des 7 sections d'une journée de formation, correspondant à un audio de cours. |
| **RAG** | "Retrieval-Augmented Generation" — technique qui fait répondre une IA en s'appuyant sur des documents précis plutôt que sur sa mémoire générale. |
| **Chunk** | Un petit passage de texte découpé dans un document, unité de base du RAG. |
| **Embedding** | La représentation mathématique du sens d'un texte, utilisée pour comparer des passages entre eux. |
| **BM25** | Une technique de recherche par mots-clés exacts (comme un moteur de recherche classique). |
| **RRF** (Reciprocal Rank Fusion) | La technique qui combine les résultats de deux recherches différentes (mots-clés + sens) en une seule liste. |
| **P1, P2, P3, P4** | Les "plateformes"/instances du système, chacune un site différent avec ses propres utilisateurs. |
| **`staging`** | La branche de code de la plateforme interne "Le Socrate". |
| **Cadrenza** | Le produit commercial en préparation (branche `codex/current-saas-postgres-20260705`). |
| **TTS** | "Text-To-Speech" — transforme un texte écrit en voix audio. |
| **Multi-tenant** | Un seul système qui sert plusieurs clients différents, chacun avec ses données isolées des autres. |
| **1 RNCP = 1 module durable** | Principe central : on génère le contenu d'un titre professionnel une seule fois, puis on le réutilise pour toutes les futures promotions de ce même titre. |

---

## 6. En une phrase pour résumer

Ce projet est né d'un vrai problème opérationnel (dépendance fragile à des formateurs et des voix off humains), résolu par Nassim ISSAD à travers un pipeline IA soigneusement décomposé (structurer avant d'écrire, découper avant de générer) qui fonctionne déjà en interne depuis plus d'un an ; l'entreprise cherche maintenant à en faire un produit vendable (Cadrenza) à d'autres centres de formation, ce qui demande de finir la sécurisation multi-client et de vérifier que toutes les fonctions du produit (notamment les questions-réponses) sont bien branchées sur cette nouvelle version.
