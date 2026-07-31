# Changelog

## 2026-07-31

### refactor(runtime): retrait de SocketIO et Eventlet

Le frontend n'utilisait plus aucun canal SocketIO. Les rooms, événements de
présence, messages temps réel et signaux de déconnexion inutilisés sont donc
supprimés. L'API Formation3 tourne désormais sous Gunicorn `gthread` et les
fan-outs bornés du pipeline utilisent les threads standards, sans modifier la
file durable, les checkpoints ni les limites de concurrence.

### refactor(slides): retrait de l'ancien générateur audio Whisper

L'ancienne chaîne audio → transcription Whisper → reconstruction des slides et
ses modules de fusion sont supprimés. Les slides proviennent uniquement du
script validé et de leur deck persistant par cours ; les anciennes routes
répondent explicitement `410 Gone`.

## 2026-07-29

### refactor(pipeline): suppression définitive du runner Claude Code local

Le service `claude_code_mission_service.py` et ses tests exclusivement liés aux
exports, imports et subprocess locaux sont supprimés. La pipeline ne peut plus
lancer Claude Code en local et continue d'utiliser son chemin API DeepSeek.

Les responsabilités encore actives ont été isolées avant la suppression :
l'audit de volume est désormais un service de lecture indépendant, l'état
transitoire des relances manuelles ne dépend plus du runner historique, et les
anciens rapports stockés dans `review_queue` restent lisibles pour préserver la
compatibilité avec les formations déjà générées.

## 2026-07-27

### feat(ui): calendrier de recrutement en plein espace

L’écran de recrutement devient un espace de travail fixe sans défilement global
sur ordinateur. L’aperçu du professeur occupe toute la hauteur disponible,
les éléments décoratifs redondants sont retirés et les trois informations
d’identité restent regroupées dans un bandeau compact.

Le calendrier devient l’élément principal de la configuration : il occupe la
majorité de la largeur et de la hauteur, tandis que les dates retenues et leurs
templates restent dans un rail secondaire à défilement interne. L’aide au
préremplissage est désormais repliable afin de laisser le calendrier visible
dès l’ouverture, sans retirer les réglages de rythme existants.

La passe de densité suivante replie automatiquement la navigation à l’ouverture
du recrutement manuel, tout en permettant de la rouvrir. Le panneau professeur
gagne en largeur, le calendrier et le préremplissage deviennent plus compacts,
et les textes redondants autour du planning sont retirés.

Les champs prénom, formation et RNCP quittent enfin le calendrier. Un bouton
crayon placé directement sur la fiche professeur ouvre leur panneau de saisie
sur l’aperçu de gauche, afin de réserver toute la partie droite au planning.
Le dashboard verrouille maintenant le défilement du document et se cale sur la
hauteur dynamique du viewport, sans supprimer les défilements internes utiles.

Le sélecteur mensuel adopte une présentation inspirée de Notion Calendar :
jours sans cases, semaine active sur un bandeau gris continu, date cochée dans
un carré sombre et jours hors mois atténués.
Le préremplissage refuse désormais explicitement les dates inexistantes, comme
le 31 septembre, et remplace toute suggestion initiale invalide par la première
date réellement autorisée.

L’affectation des templates se fait maintenant journée par journée dans un
carrousel à flèches, sans longue liste ni validation permanente dans le rail.
Le clic sur « Lancer la préparation » signale précisément les journées
incomplètes ou une première date avant J+2, puis ouvre une modale récapitulative
pour la confirmation définitive.

Le panneau d’organisation est désormais aligné sur toute la hauteur du
calendrier. La fiche journée n’est plus décalée par un numéro latéral et ses
flèches de navigation sont intégrées en bas. Une option compacte permet
d’appliquer, et de maintenir, le même template sur toutes les journées.

### fix(ci): alignement de la fixture planning V2

La fixture SQLite des tests de parité du repository pipeline expose désormais
`module_day_id` et `local_date`, comme le schéma `course_sessions` V2. Le contrôle
PostgreSQL peut ainsi valider la sélection dynamique des journées audio sans
échouer sur une table de test historique incomplète.

Ajout du guide `AI-Mentor-Prompt.md` à la racine du projet pour faciliter sa
réutilisation.

## 2026-07-26

### feat(planning): journées pédagogiques modulables et pipeline audio dynamique

Les centres peuvent désormais composer et conserver une bibliothèque de
templates de journées en blocs `cours → questions-réponses → pause`, avec pause
finale facultative et pause déjeuner de 60 à 120 minutes. Le planificateur
responsive permet de préremplir un calendrier, de corriger librement les dates
cochées puis d'affecter un template à chaque journée. La validation verrouille
un snapshot immuable du déroulé pédagogique ; les templates déjà utilisés
restent consultables, duplicables ou archivables sans pouvoir être modifiés.

Le contrat de planning V2 remplace les hypothèses fixes de 7 cours et 19 MP3 par
un manifeste exact propre à chaque journée. Les budgets de texte suivent la
durée de chaque cours avec 30 secondes de marge, le TTS parcourt le manifeste à
H-24, et les lecteurs apprenant/administration respectent l'ordre et les durées
verrouillés. Les modules historiques continuent d'utiliser leur playlist V1.

La réutilisation d'un module durable conserve ses journées et ses assets audio
immuables, exige le même nombre de nouvelles dates, et n'est proposée qu'après
la fin du module source lorsque son manifeste est complet. Une nouvelle
formation refuse toute première date située à moins de 48 heures ; une
réutilisation déjà générée ne relance pas le TTS.

### refactor(pipeline): retrait du legacy et accès Lyon explicite

La plateforme de référence conserve uniquement les parcours encore utilisés :
les pages `/recorder`, `/admin`, `/generated-slides` et `/intro` sont retirées,
ainsi que les API d'upload audio du Recorder et les cinq routes de missions
Claude Code locales. La connexion centre mène directement au dashboard et les
téléchargements de la pipeline utilisent désormais le client authentifié.

`/formation-pipeline` devient une capacité serveur explicite des comptes centre.
La permission est accordée une seule fois au compte Lyon
`newpiprod@gmail.com` lors de l'introduction de la colonne, puis chaque
révocation est conservée. Toutes les routes formation relisent la permission et
le rattachement du job au centre avant d'exécuter leur logique ; les anciens
comptes admin et les autres centres échouent en mode fermé. La migration ne
rattache au compte Lyon que les plateformes orphelines qui possèdent déjà un
job de pipeline.

La pipeline Formation3 utilise désormais DeepSeek uniquement : suppression du
fallback Anthropic, de tous les chemins runtime vers le runner Claude CLI, du
SDK Anthropic et des sélecteurs Claude dans l'interface. Le client partagé est
renommé `deepseek_client`. Le workflow exige `DEEPSEEK_API_KEY`, fixe le
fournisseur DeepSeek et supprime l'ancienne clé Anthropic d'Azure au prochain
déploiement. Les noms de modèles historiques stockés en base sont convertis
vers les profils DeepSeek Pro/Flash afin que les jobs existants restent
reprenables. Le fichier historique des missions reste temporairement présent
car les diagnostics de jobs existants y lisent encore leurs artefacts ; aucun
endpoint ne peut lancer son subprocess local.

## 2026-07-21

### feat(hr-dashboard): recrutement manuel avec identité professeur en direct

Le formulaire manuel adopte une composition 1/3–2/3 : aperçu permanent du
robot à gauche, formulaire complet à droite. Le nom, la formation, le RNCP, la
durée et la couleur actualisent la fiche du professeur pendant la saisie. Une
description est générée localement depuis le titre de formation (avec un texte
spécifique au TP CRCD), puis reste modifiable et régénérable avant paiement.

Ajout d'un symbole vectoriel original du Socrate composé de deux bandes
violettes, sans reprendre le pictogramme fictif de la maquette. Les cinq robots
3D existants restent les seules variantes d'identité. Le robot sélectionné
dispose d'un mouvement d'attente discret et d'un halo orbital, tous deux coupés
par `prefers-reduced-motion`. La description est bornée à 600 caractères côté
serveur et conservée dans la commande professeur. La fiche propose désormais
une palette compacte de cinq pastilles à la place du bouton d'identité visuelle,
et le formulaire utilise des séparateurs et contours plus discrets. L'aperçu
devient ensuite un véritable panneau scindé sur un studio réaliste, avec le
robot 3D animé au premier plan. Le choix de couleur est masqué derrière l'action
« Change visual color » et la section d'identité visuelle du formulaire est
retirée. Le décor aménagé est remplacé par un fond de studio taupe, doux et
progressivement assombri vers le bas, fidèle à la référence retenue.

## 2026-07-01

### feat(database): socle de migration pipeline vers Postgres

Premiere tranche de migration progressive de la pipeline formation vers
Postgres, sans changer le comportement metier visible. Le schema Postgres couvre
desormais les tables pipeline principales : jobs, knowledge base, dossiers,
documents, jobs/segments de generation, annotations, regles, rapports de revue,
evenements, modules durables et decks slides.

Ajout du script `migrate_sqlite_pipeline_to_postgres.py` pour copier les tables
pipeline depuis SQLite apres la migration du coeur SaaS. Ajout d'un repository
`pipeline_repository.py` qui conserve SQLite comme source de verite par defaut,
peut miroir-ecrire les jobs vers Postgres avec `PIPELINE_POSTGRES_MIRROR=1`, et
peut basculer les fonctions centralisees de jobs avec
`PIPELINE_DATABASE_BACKEND=postgres`.

Deuxieme tranche : les operations canoniques sur `cours_folders` attendus par
journee (`get_expected_course_folders`, reparation des dossiers orphelins) passent
elles aussi par le repository pipeline, toujours avec SQLite comme comportement
par defaut.

Troisieme tranche : l'observabilite pipeline (`content_review_reports` et
`formation_pipeline_events`) passe par le meme repository, avec conservation de
la creation lazy des tables en SQLite et schema explicite en Postgres.

Quatrieme tranche : les checkpoints `formation_knowledge_base` (clear, insert
pending, save enriched, mark error, list, stats) passent par le repository
pipeline afin de preparer leur lecture/ecriture Postgres.

Cinquieme tranche : les primitives centralisees de `content_generation_jobs` et
`content_generation_segments` (creation/reset de job, lecture du job, statuts,
checkpoint segment, dirty flag, texte segment, snapshot artefact) passent par le
repository pipeline, tout en conservant SQLite comme backend par defaut.

Sixieme tranche : le report inter-journees `carryover` (dossier suivant, stockage
source/cible, nettoyage et dirty flag du premier segment cible) passe par le
repository pipeline.

## 2026-06-29

### feat(hr-dashboard): robots transparents pré-colorés + flip au clic

Suite du recto robot prof IA. Remplacement de l'asset à fond blanc (2,1 Mo +
hack mix-blend-multiply) par 5 PNG **transparents détourés**, un par teinte
(bleu/violet/rose/vert/ambre, ~280 Ko chacun), pré-colorés par décalage de
teinte HSV depuis l'asset rose fourni. Le robot flotte désormais proprement
sur n'importe quel fond (clair/sombre), en plus grand (`min-height` 340px,
`max-w-full`), sans cadre. Le flip se déclenche au **clic sur une flèche** sous
le robot (toggle maintenu), plus au survol. `ROBOT_THEMES` mappe désormais
`platform_id → { src, glow }`.

## 2026-06-28

### feat(hr-dashboard): cartes plateformes en robots prof IA (flip 3D)

Les `PlatformCard` du HR Dashboard deviennent des professeurs IA. Recto : un
robot coloré sur son socle (PNG `/robot-prof.png` teinté par `hue-rotate` selon
le `platform_id` — chaque plateforme garde son robot attitré, cf. `ROBOT_THEMES`
+ `getRobotTheme`). Au survol, la carte pivote (`rotateY`) pour révéler au verso
la fiche formation **inchangée** (chip Pn, audios, actions, liens). Les deux
faces se superposent dans la même cellule grid ; `backface-visibility` + bascule
`pointer-events` selon l'état `flipped` pour que seule la face visible capte les
clics. Prolonge le storytelling « déployez une armée de professeurs IA ».

## 2026-06-12

### fix(slides): story — le texte du tableau noir ne déborde plus

Le template `story` (tableau noir) coupait souvent le récit en haut et en bas :
tableau à hauteur fixe (600px), texte manuscrit à 86px fixe, contenu centré →
un récit de 40+ mots dépassait des deux côtés et était rogné par
l'`overflow: hidden` du cadre. Corrigé avec `AutoFitText` sur `ch-lines`
(le parent `board-inner` à hauteur fixe sert de gabarit) : la police descend
progressivement (plancher −55 %) jusqu'à ce que tout le récit tienne.

L'audit `overflow-audit.mjs` détecte désormais aussi le texte rogné par un
ancêtre `overflow: hidden` (top/bottom/left/right) — ce cas était invisible
pour les checks scroll/stage. Deux cas story réels (Samir plateau, Léa
télétravail) ajoutés au banc : 49 cas, 0 anomalie.

### fix(slides): fin des textes coupés et débordements — audit Playwright

Suite et fin du chantier « le texte ne fait pas sa loi » (troncatures `…`,
débordements, soulignements arbitraires, textes amputés). Audit mené avec un
banc de rendu réel (`frontend/overflow-test.html` + `overflow-audit.mjs`,
Playwright) sur 47 slides : 42 slides réels issus des decks en base + 5 cas
extrêmes synthétiques. Résultat : 30 anomalies → 0 (2 faux positifs
letter-spacing restants).

Corrections en plus du travail déjà en cours (AutoFitText, suppression du
`slice + '…'`, wrapper `_SlideText` anti-troncature backend) :

- **`casestudy` : cartes hors cadre** — `cols-2`/`cols-3` utilisaient
  `1fr` (min-size = min-content en grid) : une carte au contenu large
  élargissait la grille au-delà du slide. → `repeat(n, minmax(0, 1fr))`.
- **`definition` : colonne écrasée** — même piège grid sur `.s-def`
  (`1.05fr 1fr` → `minmax(0, …)` + `min-width: 0` sur `.left`).
- **`comparison` : mauvais titres** — le grand titre de colonne affichait
  `col.label` (eyebrow) au lieu de `col.title` ; le schéma du prompt de
  curation documente maintenant `label` (eyebrow) vs `title` (grand titre).
- **Mots cassés en plein milieu** (« ÉMOTIONNELL/E ») — `overflow-wrap:
  anywhere` remplacé par pas-de-césure + auto-fit, avec `hyphens: auto`
  (césure typographique fr) en dernier recours sur le terme de définition.
- **`box-sizing` garanti** — les dimensions du deck source supposaient le
  border-box du preflight Tailwind ; désormais imposé localement dans
  `SalesHackingSourceDeck.css`.
- **`recap`/`reprise_recap` : description dupliquée** — quand desc == titre,
  on n'affiche plus le doublon (`pointParts` ne recopie plus le texte entier
  en desc).
- **Prompt curation durci** — interdiction de terminer un champ par `...`/`…`
  (reformuler, jamais couper) ; `definition` exige une définition réellement
  posée par la source, justifiée par `source_quote`.

Le banc de test est commité : `node overflow-audit.mjs` (Vite lancé) rejoue
l'audit complet et screenshote les cas en anomalie dans `/tmp/slide-audit/`.

### feat(tts): plus d'intro dans les fichiers pause/Q&A — outro seule

Les audios `pause_*`/`pause_midi_*`/`qa_*` générés en TTS portaient une intro
parlée au début du fichier. Décision : plus jamais d'intro propre — le fichier
commence par du silence et garde seulement son outro de fin de créneau
(annonce de reprise), durée totale inchangée. L'annonce du break reste portée
par l'outro de l'audio précédent quand le pipeline le permet.

Implémentation : `break_intro_owned_by_previous()` retourne désormais vrai pour
tout break (`qa`/`pause`/`pause_midi`), sans condition sur le fichier précédent
ni sur la neutralité été/hiver. Tous les chemins en aval forcent déjà
`intro = ""` quand ce flag est vrai : prompt LLM (`generate_break_transition`),
fallbacks statiques, chemin générique Edge (`_generic_break_texts`), assembleurs
(`_build_pause_audio`, `_build_timed_edge_break_audio` gèrent l'intro vide).
Les textes manuels saisis dans la modale HR (`break_overrides`) ne sont pas
touchés. Test `test_first_break_without_previous_audio_keeps_intro` renommé
en `..._has_no_intro` pour refléter la nouvelle règle.

### feat(video+hr): slides dédiés pause/Q&A affichés pendant les pauses

Pendant les pauses (10 min, midi) et les Q&A, la page `/video` affichait une
simple carte de compte à rebours, et la modale d'édition audio du HR Dashboard
affichait « Aucune synchro trouvée pour cet audio » : les decks générés ne
contiennent pas de timings pour les audios `pause_*`/`qa_*`.

Les slides statiques dédiés du deck Sales Hacking (`DeckPause`, `DeckQA` via
`SalesHackingSourceSlide`) sont maintenant affichés :

- **`Video.jsx`** : pendant un audio `pause`/`pause_midi`/`qa`, le slide dédié
  remplit la zone vidéo (via `SlidePreviewFrame`), avec un bandeau « Reprise
  dans M:SS » + barre de progression en surimpression bas. `getBreakSlideCopy`
  (textes de l'ancienne carte) supprimé.
- **`AudioEditor.jsx`** (modale HR) : détection par préfixe du nom de fichier
  (`pause_*`/`pause_midi_*` → pause, `qa_*` → qa) ; le slide dédié remplace le
  message « Aucune synchro trouvée », avec libellé « Slide dédié pause/Q&A »
  dans l'en-tête. Si des timings existent un jour pour ces audios, ils gardent
  la priorité.
- **Durée réelle sur le slide pause** : le « 5 minutes. » en dur du slide
  statique est remplacé par la durée effective (`breakDurationLabel` dans
  `audioSlideSync.js` : 600 s → « 10 minutes. », 5400 s → « 1h30. »).
  Côté `/video` la durée vient de l'API (`audio_duration`), côté modale HR
  elle est déduite de la plage horaire du nom de fichier
  (`pause_9h55_10h05.mp3` → 10 min). `SalesHackingSourceSlide` accepte un
  prop `replacements` pour substituer du texte dans le HTML statique.

### perf(frontend): code splitting + splash — fini l'écran noir au chargement

Le bundle initial (2,9 Mo : toutes les pages + runtime Spline) bloquait le
premier rendu sur fond noir (`body #0b0b0b`) plusieurs secondes, à chaque
déploiement (hash du bundle invalidé). Trois changements :

- **Code splitting par route** (`React.lazy`) : seule la page de login reste
  dans le bundle initial → 239 Ko (77 Ko gzip). HRDashboard, FormationPipeline,
  Video, etc. deviennent des chunks à la demande.
- **Spline différé** : le runtime 3D (~4 Mo avec physics) se charge après le
  rendu du formulaire, son fade-in existant masque l'arrivée tardive.
- **Splash inline dans index.html** (`#root:empty` + spinner violet) : pendant
  le téléchargement du JS on voit un écran de chargement Le Socrate au lieu du
  noir. Le fallback Suspense reprend le même visuel.

### fix(hr): containers audio créés avec accès public blob

Les containers audio créés par « Nouvelle plateforme » étaient privés → le
lecteur recevait 404 sur tous les MP3 (il streame anonymement via FrontDoor,
comme formationaudio-dev/p2/p3/p4 qui sont en accès `blob`). Création désormais
avec `public_access="blob"` pour le container playlist uniquement (archives et
PDFs restent privés, accès SAS). Les 35 containers existants (p5–p41) ont été
passés en accès public via az CLI.

### fix(playlist): URLs audio par plateforme depuis platform_config

La playlist du lecteur construisait toutes ses URLs depuis `AZURE_AUDIO_BASE_URL`
(env du backend), ignorant le container de la plateforme. Conséquence : les
plateformes créées depuis le dashboard HR (P5+), servies par le backend socrate1,
jouaient les audios de P1 (`formationaudio-dev`) au lieu des leurs.

`get_playlist(platform_id)` lit maintenant `audio_base_url` et `audio_container`
dans `platform_config` et réécrit les URLs : `audio_base_url` explicite >
host FrontDoor commun + `audio_container` > base env (fallback, comportement
inchangé). Neutre pour P1–P4 (leurs env vars correspondent déjà à la convention
`formationaudio-p{id}`).

## 2026-06-11

### feat(db): système de sécurité SQLite — backups, intégrité, récupération auto

Suite à l'incident "database disk image is malformed" (commit 5d9f00a), mise en
place d'une défense complète dans `backend/database/db_safety.py` :

- **Au boot** (avant `init_database`) : `PRAGMA integrity_check` ; si la base
  est saine → backup horodaté dans `<dir DB>/backups/` (`/home/backups/` sur
  Azure) avec rotation (15 max). Chaque déploiement redémarre l'app, donc
  chaque déploiement déclenche un backup.
- **Si corruption détectée** : quarantaine (`.corrupt-<ts>`), puis restauration
  automatique du dernier backup sain. Sans backup sain, base recréée vide mais
  **mode maintenance activé** : toute l'API répond 503 (sauf `/api/admin/db/*`
  et `/api/admin/login`) au lieu de repartir vide silencieusement.
- **Backup périodique** toutes les 6h (green thread eventlet).
- **Durcissement connexions** (`get_db_connection`) : `timeout=30` contre les
  "database is locked" des écritures concurrentes. En local : `journal_mode=WAL`
  (activé au boot, persistant) + `synchronous=NORMAL`. **Pas de WAL sur Azure** :
  `/home` est un partage réseau (Azure Files/CIFS) et SQLite documente le WAL
  comme non fiable sur filesystem réseau — possiblement la cause de la
  corruption d'origine. Sur Azure on garde rollback journal + `synchronous=FULL`.
- **Endpoints admin** (session `is_admin` requise) :
  `GET /api/admin/db/status` (intégrité, backups, notices de récupération),
  `POST /api/admin/db/backup` (backup manuel),
  `POST /api/admin/db/restore` (`{"backup": "<nom>"}`, vérifie l'intégrité du
  backup, sauvegarde l'actuelle en `pre-restore`, ré-applique les migrations),
  `POST /api/admin/db/maintenance` (`{"enabled": bool}`).
- Le filet de sécurité existant dans `init_database` tente lui aussi la
  restauration d'un backup sain avant de recréer une base vide.

Testé : boot sain → backup ; corruption → quarantaine + restauration auto avec
données intactes ; corruption sans backup → maintenance ON.

## 2026-06-10

### feat(slides): variantes structurelles 2/4 items pour les templates source

Ajout de variantes de composition pour les templates source qui peuvent porter
2 à 4 éléments sans créer de nouvelle slide : `casestudy`, `steps/process`,
`recap` et rendu tolérant pour `situations`. Les variantes restent dans le
même design source exact, mais adaptent grille, espacement et tailles selon le
nombre réel d'items. La page Test Slides expose maintenant ces variantes, et
la curation/normalisation accepte `casestudy` jusqu'à 4 cartes.

### feat(slides): budgets de texte sans split ni variante visuelle

Ajout d'un contrat de longueur pour les templates source exacts. Le prompt de
curation reçoit des budgets de caractères par template et doit reformuler les
champs trop longs pour rentrer dans le design existant, sans créer de slide
supplémentaire et sans variante visuelle. Le backend applique aussi une sécurité
déterministe qui compresse les champs au budget du template source en dernier
recours et persiste `layout_fit` pour audit.

### feat(plan): cohérence interne des slide_anchors (spoken_requirement ↔ shape)

Le plan pouvait livrer des anchors auto-contradictoires : la
`spoken_requirement` demandait parfois une structure orale, tandis que le
`pedagogical_shape` et le `template_type` annonçaient une autre forme. La
curation finale (section_slide_alignment), qui suit le texte réel, corrigeait
alors le template — mais elle corrigeait une contradiction déjà présente dans
le plan, pas une dérive d'écriture. Ajout dans `structured-plan.md`, le prompt
de plan global et le prompt d'enrichissement des beats : la structure orale
dominante demandée par la `spoken_requirement` fait autorité, puis le plan fixe
un `pedagogical_shape` et un `template_type` compatibles. La curation finale
garde le dernier mot si le texte dévie malgré un plan cohérent.

### feat(slides): signaux génériques de plan dans le catalogue

Ajout de `pedagogical_shape`, `plan_signals` et `plan_avoid` au catalogue de
templates pour guider le plan avec des signaux structurels génériques, sans
exemples liés à un domaine de formation. Le prompt de plan reçoit ces champs,
la curation conserve ses `strong_signals`/`rejection_rules`, et un test
anti-overfitting bloque les termes spécialisés dans les signaux de plan.

### feat(slides): carte d'affichage déclarée par le rédacteur

Ajout d'une carte technique `ORDRE_AFFICHAGE_SLIDES` / `CARTE_AFFICHAGE_SLIDES`
à la génération de section, strippée avant budget/TTS, validée par match
verbatim et persistée dans les artifacts de sections. Le deck sait désormais
calculer des fenêtres de slides depuis cette carte en
`FORMATION_SLIDES_DISPLAY_MAP_MODE=on`, avec mode `shadow` par défaut et
fallback LLM par section si une carte est absente ou invalide.
Durcissement avant rollout : la carte est aussi strippée si le modèle omet
`ORDRE_AFFICHAGE_SLIDES`, un filet anti-fuite retire les marqueurs résiduels
avant TTS, et la validation utilise le même matching tokenisé que le deck.
Les patches de conformité appliqués aux sections transportent maintenant les
repères de slide : si un `ANCRAGE` ou une `QUOTE` est réécrit via
`original → replacement`, la carte hérite du texte successeur avec le statut
`relocated_patch`; si le successeur n'est plus vérifiable, la section est
marquée `degraded` et retombe sur le fallback LLM.

## 2026-06-02

### fix(slides): chevauchement du titre sur la slide "Programme journée"

Le conteneur `.deck-slide` n'est pas un canevas fixe 1920×1080 mais un
cadre fluide (`width: 90vw; max-width: 1200px`). Les dimensions
structurelles de `deck-program7` avaient bien été réduites à cette échelle
(gap 75, padding 88, pastilles 46px…), mais les `max` des `clamp()` de
police étaient restés aux valeurs du design 1920 d'origine
(`104px`/`27px`/`35px`) — soit ~1,6× trop gros pour un cadre de 1200px. Le
`<h1>` débordait donc de sa colonne et chevauchait la timeline. Correctif :
caler les `max` de police à la proportion du canevas 1200px
(h1 `65px`, sous-titre `17px`, items `22px`) et resserrer le `max-width`
du paragraphe (600→375px).

Cause racine complémentaire : les polices du design (`Archivo Black`,
`Archivo`, `Manrope`, `JetBrains Mono`, `Caveat`) n'étaient chargées nulle
part — le projet n'importait que Fredoka/Poppins — donc tout `DeckTemplates`
retombait sur une police de substitution (titre, numéros mono, logo
manuscrit perdus). Ajout de l'`@import` Google Fonts en tête de
`DeckTemplates.css`. Correction aussi du logo « Sales » qui était en
`Archivo Black` au lieu de `Caveat` (manuscrit) comme dans le design.

## 2026-05-20

### fix(audio-editor): seek arbitraire cassé sur la waveform

L'endpoint `GET /api/hr/cours-folders/<id>/audio-stream/<filename>`
annonçait `Accept-Ranges: bytes` mais ignorait le header `Range` envoyé par
le navigateur : il renvoyait toujours le MP3 complet avec `200 OK`. Quand
l'utilisateur cliquait vers la fin de la waveform (`AudioEditor.jsx`), le
`<audio>` HTML5 sous WaveSurfer demandait un range partiel, recevait `200`
au lieu de `206 Partial Content`, et le seek échouait silencieusement —
seule la lecture depuis le début fonctionnait.

Correctif : `stream_audio_file` parse maintenant `Range: bytes=START-END`
(et `bytes=-SUFFIX`), renvoie `206 Partial Content` avec `Content-Range`
et `Content-Length` corrects, ou `416 Range Not Satisfiable` si la plage
est invalide. Aucune modification frontend nécessaire — le bug était
100 % côté backend.

## 2026-05-19

### feat(slides): deck de référence 12 templates de slides visio

Import du deck de design Claude (bundle `pyVNROKZYR8pVON75b4TNw`) dans
`frontend/public/slide-templates/` :

- `deck.html` — 12 templates 16:9 (1920×1080) pour formation en visio, un
  par type du storyboard : `intro_formation`, `big_statement`, `definition`,
  `diagnostic`, `mistake`, `case_study`, `process`, `checklist`, `recap`,
  `transition`, `pause`, `qa`.
- `deck-stage.js` — web component `<deck-stage>` (navigation clavier,
  thumbnails, auto-scale, print → PDF).
- Identité visuelle : bleu profond (`#050a26`→`#1a37d6`) + accent corail
  (`#ff5d6c`), typo Archivo Black display + Manrope body + JetBrains Mono
  labels + Caveat manuscrit ; grille subtile + grain pour un rendu
  « studio de formation » plutôt que « PDF projeté ».

Visualisation locale : `http://localhost:5173/slide-templates/deck.html`
(une fois `npm run dev` lancé sur frontend).

**Suite prévue** : porter les 12 templates en composants React dans
`frontend/src/components/slides/` pour les brancher sur le storyboard JSON
généré par l'IA à partir du texte de chaque bloc cours.

### measure(tts): débit réel Fish Audio mesuré + calibration Edge TTS

**Mesure Fish Audio S2-Pro** via le nouvel endpoint `with-timestamp`, sur
72 min d'audio (~12 000 mots du script TTS-ready `Module1_accueil_boulangerie`),
au rythme exact de la formation (speed=0.90) :

- **wpm réel = 165,7** (mots/heure ≈ 9 942) — alors que la pipeline supposait
  **192** (`_DEFAULT_TTS_WORDS_PER_MINUTE`). Sur-estimation de ~16 % : la
  pipeline budgète trop de mots par créneau cours.
- wpm par batch : 161 / 174 / 162 — la mesure par minute est bruitée (±8 %),
  seul l'agrégat sur ~1h est fiable.
- Scripts : `measure_fish_wpm.py`, sortie `fish_wpm_report.json` +
  `fish_1h_audio.mp3`.

**Calibration Edge TTS** (voix de synthèse gratuite, `fr-FR-DeniseNeural`) pour
servir de remplaçant fidèle au rythme :

- Edge natif (speed 1.0) = 144,6 wpm.
- Pour atteindre 165,7 wpm → `BASIC_TTS_SPEED=1.15` (rate edge-tts +15 %).
  Vérifié : régénération à +15 % → 166,3 wpm (écart +0,3 %).
- `BASIC_TTS_SPEED=1.15` ajouté à `backend/.env`.
- Script : `calibrate_edge_speed.py`, sortie `edge_calibration_report.json`.

**Correction appliquée** : la calibration pipeline par défaut passe de `192` à
`165,7` mots/min (`FORMATION_TTS_WORDS_PER_MINUTE` reste surchargeable). Les
budgets génération, sécurité volume, closings contextuels et garde-fous Word 2 /
audio utilisent désormais cette cadence.
Noté aussi : la pipeline `basic_tts` envoie le texte avec ses tags `[pause]`
bruts à Edge TTS (qui les vocaliserait) — à vérifier séparément.

### fix(prompts): interdire "hier"/"demain" dans les références inter-cours

**Problème** : le contenu généré (visible dans le cours 2 de la formation
Employé Commercial) disait "depuis hier" et "hier, on a posé les fondations".
Or les cours ne s'enchaînent PAS au jour le jour — un cours par semaine, et ce
rythme peut changer. "hier" est donc factuellement faux.

**Cause racine** : `prompt-generation-tts-scratch.md` autorisait explicitement
"hier on a vu…" dans la RÈGLE #25 (cours à distance) et dans les blocs "Référencer
la progression pédagogique" — sur les 3 passes de génération. De plus, le ruleset
de la passe **Humanisation** (#101-#113) — qui ignore volontairement #1-#27 — ne
contenait AUCUNE règle interdisant "hier" : la passe Humanisation ne corrigeait
donc jamais ces occurrences.

**Correction** :
- RÈGLE #25 (×3 passes) : "hier"/"demain" passent d'autorisés à INTERDITS ;
  références imposées vagues et non datées ("la dernière fois", "lors du dernier
  cours", "dans la séance précédente").
- Blocs "Référencer la progression pédagogique" (×2) : même correction.
- **Nouvelle RÈGLE #114** dans le ruleset Humanisation (`_HUMANIZATION_REVIEW_RULES`)
  : "Références entre cours toujours vagues, jamais datées". Ajoutée au groupe
  `humanisation_rythme` (#101-#114), version du ruleset bumpée en
  `2026-05-19-humanisation-v4`. Mentions hardcodées "#101 à #113" mises à jour
  dans `claude_code_mission_service.py` et `content_generation_service.py`.
- `closing_transition_service.py` : wording des prompts aligné ("la dernière
  fois" / "lors du dernier cours" au lieu de "au cours dernier").
- `content_generation_service.py` : `_CARRYOVER_INTRO` et prompt de réduction
  du dernier bloc alignés sur les mêmes formulations vagues.

Impact : la génération ne produira plus "hier" (RÈGLE #25), et les passes
**Conformité** (#25) ET **Humanisation** (#114) patcheront désormais les
occurrences existantes. Le bump de version du ruleset humanisation force la
re-revue des segments. Les cours déjà générés doivent être repassés en relecture
pour être corrigés.

## 2026-05-17

### feat(formation): extension cours "Employé Commercial - Écoute Active" (+2400 mots supplémentaires)

**Continuation avancée du cours écoute active** (2400 mots supplémentaires) :
- Cas contraste détaillé : analyse erreur collègue réfrigérateur (absence écoute active)
- Adaptation selon profils clients : novice/expert/pressé/exploratoire avec exemples spécifiques
- 5 nouveaux exemples fictifs contextualisés (jouets, maroquinerie, plantes, vêtements enfants, électroménager)
- Gestion contraintes non-exprimées (budget, décisions familiales)
- Évolution compétence vers maîtrise naturelle et invisible
- Mini-récaps oraux après chaque section + conclusion transformationnelle
- Respect complet règles TTS Fish Audio et ton oral avec pauses
- Fichier : `cours_employe_commercial_ecoute_active_suite.txt`

### feat(formation): extension cours "Employé Commercial - Écoute Active" (+1800 mots supplémentaires)

**Extension avancée du cours écoute active** (1800 mots supplémentaires) :
- 3 pièges fréquents avec exemples détaillés (impatience résultat, écoute sélective, confusion interrogatoire)
- 3 techniques concrètes d'écoute active (reformulation, questions ouvertes, écho émotionnel)
- 4 conseils pratiques pour développer la compétence au quotidien
- Gestion des situations difficiles (clients fermés, agacés, très bavards)
- Conclusion synthétique — total cours : ~7500 mots
- Respect complet paradigme cours à distance synchrone + règles TTS Fish Audio
- Fichier : `cours_employe_commercial_ecoute_active_suite.txt`

### feat(formation): extension cours "Employé Commercial - Écoute Active" (+1980 mots)

**Suite du cours écoute active** (1980 mots supplémentaires) :
- 4 exemples fictifs contextes variés (expert pressé, novice exploratoire, client mécontent, décideur collectif)
- 1 cas contraste explicite : écoute active pervertie en technique de vente déguisée
- Nuances selon profils clients (novice vs expert, pressé vs exploratoire) 
- Technique miroir émotionnel et art de la question de relance
- Mini-récapitulatifs oraux après chaque section + conclusion renforcée
- Respect complet règles TTS anti-dérive (#21-#26) et paradigme cours à distance synchrone
- Fichier : `cours_employe_commercial_ecoute_active_suite.txt`

### feat(formation): création cours "Employé Commercial - Écoute Active et Identification des Besoins"

**Nouveau cours complet** (5000+ mots) :
- Base écoute active 3756 mots + extension 1800+ mots
- 4 exemples fictifs contextes variés (sport/randonnée, bijouterie/alliance, auto/citadine, jardinage/tomates)  
- 1 cas contraste explicite (échec électroménager par manque d'écoute)
- Adaptation selon profils clients (novice, expert, pressé, exploratoire)
- Mini-récapitulatifs oraux après chaque section
- Respect complet règles TTS (tags Fish Audio, ton oral, transitions naturelles)
- Fichier : `cours_employe_commercial_ecoute_active_suite.txt`

### feat(formation): extension cours "Employé Commercial - Réception et contrôle des marchandises"

**Extension 1** (+1800 mots supplémentaires, total >5000 mots) :
- 4 exemples fictifs détaillés (Sarah/bricolage, Marc/bio, Carole/vêtements, Kevin/contre-exemple)
- Cas contraste explicite montrant les erreurs à éviter (négligence, signature prématurée, dissimulation)
- Nuances relationnelles selon profils interlocuteurs (transporteurs, fournisseurs, hiérarchie)
- Mini-récapitulatifs oraux après chaque section
- Respect complet des règles TTS (tags Fish Audio, ton oral, transitions naturelles)

**Extension 2** (+1800 mots supplémentaires, total largement >7000 mots) :
- 3 nouveaux exemples concrets : Isabelle (électroménager/urgence), Thomas (sport/éthique saisonnalité), Patricia (électronique/innovation)
- Situations d'exception : gestion urgences, dilemmes éthiques, adaptation aux innovations
- Perspective évolution métier : impact IA, blockchain, écologie, mondialisation
- Mini-récaps après chaque section + conclusion renforcée
- Même ton oral et respect intégral tags Fish Audio

**Extension 3** (+1800 mots supplémentaires, total >9000 mots) :
- 4 exemples terrain diversifiés : Brigitte (SAV électroménager/urgence), Antoine (informatique/expert), Sandrine (agence voyage/indécis), démonstration Kevin (bricolage/erreurs)
- Cas contraste détaillé : 3 pièges classiques (standardisation aveugle, intrusion excessive, désynchronisation)
- Nuances profils clients : pressé efficace, exploratoire prudent, novice anxieux, expert exigeant
- Situations exceptionnelles : détresse émotionnelle, compétences dépassées, agressivité
- Mini-récaps systématiques + conclusion finale renforcée

**Extension 3** (+2040 mots supplémentaires, total 5744 mots) :
- 4 nouveaux exemples détaillés : Julien (déco/fins de série), Caroline (pharmacie/multi-sites), Fabrice (luxe/authentification), Sandrine (électronique/retours)
- Cas contraste catastrophique : Laurent (alimentaire/négligence grave menant à intoxication)
- Nuances profil client approfondies : novice vs expert, pressé vs exploratoire
- Situations ultra-spécialisées : coordination réseau, produits haut de gamme
- Transition naturelle depuis fin existante + mini-récaps + conclusion enrichie
- Maintien cohérence TTS (tags Fish Audio, ton oral, discours indirect)

**Extension 3** (+1800 mots supplémentaires, total >9000 mots) :
- 3 exemples fictifs variés dans contextes différents : épicerie de quartier (espace/temps limité), entrepôt informatique (valeur/fragilité), boulangerie (fraîcheur/rotation rapide)
- Cas contraste explicite : 3 erreurs critiques à éviter (habitude vs logique, formation équipes temporaires, piège informatisation)
- Nuances selon profil client : novice (simplicité), expert (optimisation), pressé (impact rapide), exploratoire (approfondissement)
- Gestion fins de série et produits discontinuité : segmentation demande résiduelle, stratégies différenciées
- Coordination transporteurs : créneaux négociés, solutions secours, communication contraintes
- Mini-récaps oraux après chaque section majeure
- Transition naturelle et maintien cohérence ton oral + tags Fish Audio

Fichier final : `cours_employe_commercial_reception_marchandises_suite.txt`

## 2026-05-13

### feat(content-review): revérif au niveau BLOC COURS (cours de 45-55 min), pas au niveau segment interne

Remarque utilisateur déterminante : *« les règles que j'ai écrites portent sur les introductions, les conclusions et les transitions de mes cours de 45 ou 55 min. Donc il faut que tout ça soit fait par rapport aux cours, pas aux sous-parties × passes. »*

Le mode précédent travaillait au niveau `content_generation_segments` (6 sous-parties × 3 passes = 18 segments par jour). Ce découpage est interne au système de génération, pas l'unité éditoriale du formateur. Conséquence : DeepSeek voyait des bouts de cours isolés et ne pouvait pas juger les règles structurelles (intro / corps / conclusion / transition).

**Bascule au niveau bloc cours** : 1 bloc = 1 MP3 = un cours complet de 45-55 min = ~7000-10000 mots. Sur 2 journées × 7 blocs = 14 cours à analyser. DeepSeek voit le cours dans son entier et peut juger correctement.

**Backend** (`backend/services/script_rules_service.py`)
- Nouvelle fonction `review_blocs_with_rules(folder_id, *, dry_run, progress_task_id)` qui remplace conceptuellement l'ancienne `review_segments_with_rules` (cette dernière est conservée mais plus appelée par défaut).
- Pour chaque bloc :
  1. Récupère le texte complet via `get_course_script_plan_for_ui(...).course_blocs`.
  2. Appel DeepSeek (max_tokens dynamique selon taille bloc, retry JSON).
  3. Reçoit la liste de `patches` (find/replace/reason).
  4. Pour chaque patch : `_locate_patch_segment(find, segments_rows)` cherche dans quel `content_generation_segments.text_content` le `find` apparaît exactement une fois.
  5. Si trouvé → applique le replace dans **ce segment précis** (dirty=1 reviewed=0). Si introuvable ou ambigu → patch ignoré, erreur tracée.
- `start_text_review_async` appelle maintenant `review_blocs_with_rules` par défaut. Le `task.segments_total` est désormais le **nombre de blocs** (pas de segments).
- Le summary expose les compteurs sous 2 noms (compat ascendante) : `blocs_examined/modified/conforme/failed` ET `segments_examined/modified/conforme/failed`.
- Chaque détail de bloc porte `bloc_number`, `filename`, `patches[]` avec `applied + segment_id` (lequel des segments DB a été touché), `segments_touched: [id, id, ...]`.

**Frontend** (`frontend/src/components/CoursFolders.jsx`)
- Titre du résumé : « Résumé revérif **cours** » (au lieu de « texte »).
- Compteurs : « Cours examinés / Modifiés / Conformes / Échecs ».
- Chaque détail affiche désormais « **Cours N/7** · <filename.mp3> · status · X/Y patch(s) appliqué(s) · Z segment(s) DB touché(s) ». Plus de référence aux sous-parties × passes (qui est une concrétion interne).
- La liste des patches sous chaque cours reste affichée en diff `− <find>` / `+ <replace>` comme avant.

Effet pratique : les règles « éviter les débuts trop brusques », « créer une vraie phase de conclusion », « donner l'impression d'une journée vécue » fonctionnent maintenant correctement parce que DeepSeek voit l'entrée + milieu + sortie d'un cours dans le même prompt.

### feat(content-review): revérif texte en mode PATCHES chirurgicaux (au lieu de réécriture complète)

Remarque utilisateur cruciale : *« la feature est censée remplacer que les parties qu'elle juge à remplacer ... ajouter quelques choses, supprimer quelques choses, etc »*. Le mode précédent demandait un `corrected_text` complet au LLM, qui reformulait tout le segment même les phrases conformes. Bascule en mode **patches find/replace ciblés**.

**Backend** (`backend/services/script_rules_service.py`)

- Nouveau format de réponse DeepSeek :
  ```json
  {
    "conforme": false,
    "violations": ["Règle 1 : ..."],
    "patches": [
      {"find": "<texte exact à modifier>", "replace": "<nouveau texte>", "reason": "Règle X : motif"}
    ]
  }
  ```
- `_build_review_prompt` réécrit avec 8 règles impératives sur les patches :
  - `find` doit être présent **une seule fois** (sinon ambiguïté → ignoré).
  - `find` doit être **strictement identique** au texte de l'extrait (ponctuation, espaces, tags audio).
  - `replace` peut modifier / ajouter une phrase / supprimer une phrase / ajouter des tags audio, etc.
  - Préférer **plusieurs petits patches** à un seul gros qui remplace un paragraphe entier.
  - Conforme = `"patches": []`.
- Nouvelle fonction `_apply_patches(original_text, patches) -> (corrected, applied_count, errors)` qui applique chaque patch en `str.replace(find, replace, 1)`. Renvoie aussi les erreurs (find introuvable ou ambigu).
- Compat ascendante : si DeepSeek renvoie encore l'ancien `corrected_text`, on fabrique un patch unique pour ne pas casser.
- Chaque détail du résumé porte maintenant `patches` (liste avec `find/replace/reason/applied`), `patches_applied` (int), `patch_errors` (list[str]).
- Le segment est marqué `conforme` si `patches=[]` OU si aucun patch n'a pu être appliqué (find introuvable).

**Frontend** (`frontend/src/components/CoursFolders.jsx`)

- Le panneau Règles a maintenant `max-height: 70vh` + `overflow-y: auto` → **scrollable** quand le contenu dépasse.
- Section résumé revérif texte : **plus de limite slice(0, 6)** — tous les segments non-conformes sont affichés dans un sous-conteneur `max-h-[60vh] overflow-y-auto`.
- Chaque segment affiche :
  - En-tête : sous-partie · passe · status · X/Y patch(s) appliqué(s)
  - Liste des règles violées
  - Compteur de mots (avant → après)
  - **Pour chaque patch** : un bloc dédié avec :
    - Bordure verte si appliqué, rouge si ignoré
    - Raison (1 ligne)
    - Bloc rouge `− <find>` (passage original)
    - Bloc vert `+ <replace>` (nouveau texte)
  - Bloc erreurs patches si certains ont été ignorés (find ambigu ou introuvable)

Résultat : tu vois maintenant **exactement** quelle phrase a été remplacée par quelle phrase, avec la règle qui l'a justifié, sans avoir à comparer mentalement deux blocs de 5000 mots.

### fix(content-review): revérif texte — max_tokens dynamique, retry JSON, contrainte longueur stricte

Suite au run 18/18 où 9 segments (les passes 1-2, les plus longues 5000-7000 mots) ont échoué en « JSON inparseable » à cause de la troncature DeepSeek + DeepSeek réduisait les textes de ~50 % au lieu de ±15 %. Trois corrections :

**1. `max_tokens` calculé dynamiquement par segment** (`script_rules_service.py:_process_group`)
- Avant : `max_tokens=8000` fixe. Pour un segment de 6000 mots, la réponse `corrected_text` peut faire ~9000-10000 tokens → tronquée → JSON cassé.
- Maintenant : `llm_max_tokens = min(60000, max(8000, int(word_count × 1.15 × 1.6) + 800))`.
  - `× 1.15` : tolérance de la contrainte de longueur (cf. point 3).
  - `× 1.6` : ratio token/mot moyen en français.
  - `+ 800` : marge pour le wrapper JSON (champs `conforme`, `violations`, etc.).
  - Cap à 60000 pour rester dans les limites du provider.
- Timeout passé de 300s à 600s pour les longs appels.

**2. Retry automatique sur JSON inparseable** (`_process_group`)
- Si la 1re réponse n'est pas du JSON valide : 2e tentative avec un **prompt renforcé** (préambule explicite « format JSON strict, pas de fence, échappe les caractères spéciaux ») et `max_tokens × 1.5`.
- Si le retry réussit → le segment est traité normalement et un log `✓ retry OK` apparaît.
- Si le retry échoue aussi → segment marqué `failed` avec raison `JSON DeepSeek inparseable (après retry)` et un `raw_preview` plus long (500 chars au lieu de 200) pour debug.

**3. Contrainte de longueur stricte dans le prompt** (`_build_review_prompt`)
- Avant : « Conserve la longueur approximative » → DeepSeek interprétait les règles « ralentir, ajouter pauses, casser les phrases » comme un mandat pour couper le texte de moitié.
- Maintenant : **IMPÉRATIF longueur** annoncé en gras, avec borne min/max calculée explicitement (`min_words = wc × 0.85`, `max_words = wc × 1.15`).
- Phrase ajoutée : *« Si tu ne peux pas appliquer toutes les règles sans dépasser cette borne, applique-en moins mais respecte strictement la longueur. Couper le contenu de moitié est INTERDIT. »*
- Bonus : rappel de conserver tous les tags audio (`[pause]`, `[calm]`, etc.) déjà présents dans l'extrait.
- Le nombre de mots de l'extrait est affiché dans le marqueur `=== Extrait à vérifier (X mots) ===` pour que le LLM en ait conscience.

### feat(content-review): revérif texte parallélisée par sous-partie + persistance à travers la modale

Deux améliorations sur la revérif texte (Phase 3b') basées sur retour utilisateur :

**1. Parallélisation par sous-partie** (`backend/services/script_rules_service.py`)
- Les segments sont regroupés par `sub_part_index` (1 « cours » par sous-partie).
- Chaque sous-partie est traitée par un greenlet eventlet dédié — concrètement, sur un cours de 6 sous-parties × 3 passes, on a jusqu'à 6 greenlets actifs en parallèle qui traitent leurs 3 passes séquentiellement chacun.
- Pool plafonné via env var `SCRIPT_RULES_TEXT_PARALLEL` (défaut **6**, override possible). Évite de saturer DeepSeek (rate limit) et SQLite (write-lock).
- Deux `eventlet.semaphore.Semaphore(1)` pour synchroniser :
  - `state_lock` : MAJ concurrentes du `summary` + `_TEXT_REVIEW_TASKS[task_id]`.
  - `db_lock` : sérialise les `UPDATE content_generation_segments` pour éviter `database is locked` côté SQLite.
- Gain attendu : 6 sous-parties parallèles × 3 passes séquentielles ≈ **~3x plus rapide** que la version 100% séquentielle (limité par la passe la plus lente de chaque sous-partie). Pour 36 segments × ~20s/segment, on passe d'environ 12 min à ~4 min.

**2. Persistance à travers la fermeture de la modale**
- Nouveau dict module `_FOLDER_TO_LATEST_TASK: dict[int, str]` qui mémorise le dernier `task_id` connu pour chaque `folder_id`.
- `start_text_review_async` met à jour cette map au lancement.
- Nouvelle fonction `get_active_text_review_for_folder(folder_id)` qui retourne la tâche (active ou récemment terminée) du folder.
- Nouvel endpoint `GET /api/hr/cours-folders/<id>/content-job/rules/review-text/active` qui expose cette info au frontend.
- Frontend (`CoursFolders.jsx`) :
  - À l'ouverture de la modale Script TTS, `handleViewContentScript` appelle `resumeActiveTextReview()` :
    - Si `task.status === 'running'` → réouvre le panneau Règles, réactive `reviewingText`, et redémarre le polling toutes les 2s.
    - Si `task.status === 'completed'` → affiche directement le résumé final dans le panneau Règles.
  - `closeContentScriptModal` ne stoppe que le polling local ; la tâche backend continue dans son greenlet.
  - Conséquence : tu peux fermer la modale, naviguer ailleurs, et la rouvrir → la progression est restaurée comme si tu ne l'avais pas quittée.

### feat(content-review): revérif texte en mode async + polling progression (logs live)

Suite à la remarque utilisateur « rajoute des logs pour qu'on sache où on en est » sur la revérif texte (qui peut prendre 10-15 min), bascule en mode async :

**Backend** (`backend/services/script_rules_service.py`)
- État partagé en mémoire `_TEXT_REVIEW_TASKS: dict[task_id, state]` au niveau module (lifetime = process gunicorn worker). Volontairement non persistant.
- `start_text_review_async(folder_id, dry_run, sub_part_indices)` :
  - Valide les pré-requis (job + règles existent)
  - Compte les segments totaux pour pré-remplir `segments_total`
  - Génère un `task_id` UUID4
  - Spawn un greenlet eventlet qui exécute `review_segments_with_rules(...)` et stocke le résultat dans `_TEXT_REVIEW_TASKS[task_id]`
  - Retourne immédiatement (< 1s)
- `review_segments_with_rules` accepte un nouveau paramètre `progress_task_id` qui, s'il est passé, met à jour l'état au fil du traitement : `current_segment`, `current_step` (lecture / appel DeepSeek / écriture DB), compteurs incrémentaux, et un buffer `log_lines` (50 dernières lignes max) avec timestamps.
- `get_text_review_task(task_id)` : lookup par task_id.

**Endpoints HR** (`backend/routes/hr_routes.py`)
- `POST .../rules/review-text` retourne maintenant `202 Accepted` avec `{task_id, dry_run}` au lieu de bloquer la requête (évite les timeouts Azure App Service ~230s sur les longues revérif).
- Nouveau `GET .../rules/review-text/status/<task_id>` qui retourne l'état complet de la tâche (status, progression, log_lines, result final si completed).

**Frontend** (`frontend/src/components/CoursFolders.jsx`)
- `runTextReview(dryRun)` : POST → reçoit task_id → démarre un polling toutes les 2s sur `/status/<task_id>`.
- Le polling se termine automatiquement quand `status === 'completed'` ou `'failed'`.
- Cleanup ref `textReviewPollRef` pour annuler le polling proprement entre runs.
- Nouveau bloc bleu « ⏳ Revérif texte en cours » qui affiche tant que `status === 'running'` :
  - Barre de progression `segments_done / segments_total` avec dégradé bleu animé (transition CSS 0.4s).
  - Ligne « 📄 <segment courant> · <étape courante> » qui se met à jour à chaque tick.
  - 4 compteurs live (à modifier / conformes / skipped / échecs).
  - Console scrollable des 12 dernières `log_lines` avec timestamps (police monospace, max 32rem de haut).

Bénéfice : tu vois en temps réel quelle sous-partie + passe DeepSeek est en train d'analyser, combien de segments restent, et lesquels ont planté/sont conformes — au lieu de rester 10-15 min devant un spinner muet.

### feat(content-review): revérif des règles au niveau TEXTE (avant les MP3) — Phase 3b'

Nouveau mode de revérif qui modifie le **texte des segments en base** au lieu de splicer directement les MP3. Travaille au niveau `content_generation_segments` (sub_part × passe) au lieu des chunks audio. Avantages :

1. **Pas besoin de `script_slide_deck`** ni d'`audio_sync.timings` — fonctionne même quand la pipeline a tourné en mode « Edge TTS voix basique » sans slides, donc sans deck créé.
2. **Plus sûr** : tu vois les modifs en texte avant qu'elles n'atteignent les MP3. Tu peux itérer sur tes règles sans coût TTS.
3. **Moins d'appels DeepSeek** : ~36 segments vs ~150 chunks (4x moins de coût/temps que Phase 3b chunks).
4. **Workflow naturel** : segments modifiés → marqués `dirty=1 reviewed=0` → à la prochaine relance TTS, les MP3 sont régénérés depuis le texte corrigé.

**Backend** (`backend/services/script_rules_service.py`)
- Nouvelle fonction `review_segments_with_rules(folder_id, *, dry_run, sub_part_indices)` qui boucle sur `content_generation_segments` (status='completed'), envoie chaque segment + règles à DeepSeek Pro, et applique les corrections en `UPDATE text_content, word_count, dirty=1, reviewed=0, review_error=NULL`.
- Réutilise `_build_review_prompt` et `_parse_review_response` de Phase 3b chunks (mêmes contraintes JSON, max_tokens passé à 8000 pour les longs segments).
- Best-effort par segment : un échec n'arrête pas les autres.
- Filtre optionnel `sub_part_indices` pour cibler quelques sous-parties (utilité future : étape pipeline ciblée).

**Endpoint HR** : `POST /api/hr/cours-folders/<id>/content-job/rules/review-text` accepte `{dry_run, sub_part_indices}`.

**Frontend** (`frontend/src/components/CoursFolders.jsx`)
- 4 boutons dans le panneau Règles maintenant, dans cet ordre logique :
  - 📄 **Simuler texte** (gris) — dry_run au niveau segment, ne touche à rien
  - ✏️ **Appliquer au texte** (bleu) — modifie segments en DB + dirty=1, avec confirmation
  - 👁 **Simuler MP3** (gris) — dry_run au niveau chunk audio (Phase 3b chunks, nécessite deck)
  - ✨ **Appliquer aux MP3** (vert) — splice MP3 ms-précis (Phase 3b chunks, nécessite deck)
- Résumé revérif texte affiche : examinés / modifiés / conformes / échecs + détails sub_part/passe + words_before → words_after par segment.
- Note jaune sous résumé non-dry-run rappelle que les MP3 actuels ne reflètent pas encore les changements.

**Note design** — service conçu pour double usage :
1. Manuel via UI (bouton « Appliquer au texte »).
2. Pipeline (à venir) : étape automatique à incruster entre la review conformité et le TTS, pour appliquer les règles apprises directement dans le flux normal.

### fix(content-review): correction strictement limitée à l'extrait surligné (plus de "paragraphe alentour" débordant)

**Bug observé** : quand l'utilisateur surlignait ~3 paragraphes dans la modal Script TTS et cliquait « Noter », DeepSeek lui proposait de réécrire **tout le bloc** (~7000 mots) au lieu de juste son extrait.

**Cause** : `create_script_annotation` appelait `_extract_paragraph_around(paragraph_context, selected_text)` pour deviner le « paragraphe alentour ». Or `event.currentTarget.textContent` côté frontend **collapse tous les sauts de ligne `\n\n` en espaces simples**. Conséquence : `text.split("\n\n")` retournait `[le_bloc_entier]` comme un unique paragraphe — donc DeepSeek recevait le bloc entier à réécrire.

**Fix** :
- `original_paragraph = selected_text` directement (plus de devinette). DeepSeek réécrit STRICTEMENT le périmètre de l'extrait surligné.
- Prompt LLM ajusté : « réécris UNIQUEMENT cet extrait, pas plus, pas moins. Le nombre de mots produit doit rester proche de l'extrait (±20%). Conserve les tags audio entre crochets (`[pause]`, `[calm]`, `[emphasis]`) s'ils sont présents dans l'extrait. »
- Suppression de `_extract_paragraph_around()` (dead code maintenant).

**Effet de bord positif** : le splice MP3 chirurgical (Phase B) cherche désormais `selected_text` (= ce que tu as surligné) dans le bloc texte au lieu d'un paragraphe potentiellement plus large → splice plus précis.

### feat(content-review): DeepSeek Pro par défaut sur les 3 services LLM + édition manuelle du markdown des règles

**Modèle LLM revu à la hausse** — les 3 services qui appellent DeepSeek passent du modèle Flash au modèle Pro :
- `script_annotation_service.py` : `CORRECTION_MODEL` (correction immédiate d'un paragraphe à l'annotation, Phase A)
- `script_rules_service.py` : `RULES_MODEL` (extraction de règles transversales, Phase 3a) + `REVIEW_MODEL` (revérif post-TTS chunk par chunk, Phase 3b)

Toutes les valeurs par défaut passent de `DEEPSEEK_DEFAULT_MODEL` (= `deepseek-v4-flash`) à `"deepseek-v4-pro"`. Les env vars (`SCRIPT_ANNOTATION_MODEL`, `SCRIPT_RULES_MODEL`, `SCRIPT_RULES_REVIEW_MODEL`) restent dispo pour override.

Conséquence : qualité de correction / extraction / revérif nettement meilleure (modèle plus capable de raisonner sur du français technique RNCP). Coût par appel plus élevé mais latence acceptable, et les volumes sont modérés (1 appel par annotation, 1 appel par extraction, 1 appel par chunk audio en revérif).

**Édition manuelle du markdown des règles** (`frontend/src/components/CoursFolders.jsx`) — l'admin peut désormais retoucher à la main le markdown produit par DeepSeek avant que Phase 3b ne l'applique aux MP3.

- Nouveau bouton « Modifier » dans le panneau Règles (à côté de « Markdown » télécharger).
- En mode édition : `<textarea>` plein largeur 14 lignes redimensionnable, police monospace, valeur initialisée avec le markdown actuel.
- Boutons « Annuler » / « Enregistrer » en bas du textarea. Le bouton « Modifier » disparaît pendant l'édition.
- L'enregistrement appelle `PUT /api/hr/cours-folders/<id>/content-job/rules` (endpoint déjà existant côté backend, branché à `update_rules_markdown`).
- L'état local React est mis à jour avec la réponse du backend (rules_markdown, rules_count, updated_at, model='manual').
- En cas d'erreur réseau ou backend, message d'erreur affiché sous les boutons.

Workflow type : extraction DeepSeek → relecture par l'admin → édition manuelle (suppression de règles non pertinentes, reformulation, ajout de cas-limites observés) → enregistrement → revérif Phase 3b s'applique sur le markdown édité, pas sur la sortie brute LLM.

## 2026-05-12

### ui(formation-pipeline): suppression de la barre redondante « Fichiers playlist MP3 » du panneau global

Avec l'ajout des barres cyan « ⚡ Audio en cours » par journée, la barre jaune « Fichiers playlist MP3 X/19 fichiers » dans le panneau « En cours maintenant » du haut affichait exactement la même donnée que la barre cyan du dernier dossier actif — sans dire de quel dossier elle parlait. L'utilisateur voyait deux barres identiques avec deux libellés différents, ce qui embrouillait.

Changements :
- **Suppression** de la sous-section barre + compteur « Fichiers playlist MP3 » du panneau « En cours maintenant ». Le panneau reste textuel : titre, étape en cours, folder, message.
- **Renommage** du panneau « En cours maintenant » → « Étape en cours » + note de pointage vers les barres cyan par journée.
- **Renommage** du panneau global « Segments texte audio à jour » → « Segments validés (texte ↔ audio) » + note explicative : « Compteur figé pendant la régénération (mis à jour à la fin de chaque bloc TTS). Pour le live, voir la barre ⚡ par journée. »

Cohérence visuelle : maintenant 3 niveaux d'info distincts au lieu de 4 qui se recouvraient. (1) Étape en cours (texte seul). (2) % validation DB (statique, fin de bloc). (3) Progression live par journée (cyan, temps réel).

### ui(formation-pipeline): barre de progression audio temps réel par journée

Pendant la synthèse audio (~10-15 min par journée), la barre « X/18 segments à jour » de chaque journée restait figée parce que le flag `dirty=0` n'est mis qu'à la **fin** de chaque bloc cours complet, pas pendant. Conséquence : l'utilisateur croyait la pipeline bloquée.

Ajouté **sous la barre statique « X/N à jour »** une seconde barre cyan **« ⚡ Audio en cours · step/total · X% »** qui :
- Lit le dernier event `audio_progress` filtré par `folder_id` (déjà émis par `_make_audio_progress_logger` à chaque chunk TTS).
- Affiche `step/total` (ex. `5/19 fichiers · 26%`) avec une barre dégradée cyan animée (transition CSS 0.4s).
- Apparaît uniquement quand `lastFolderEvent.status === 'running'` ou type `audio_folder_started`/`audio_progress`, et disparaît dès que le folder est `audio_folder_completed` ou `audio_folder_failed`.

**Polling étoffé** (`useEffect` polling de FormationPipeline) : pendant `AUDIO_ACTIVE_STATUSES`, le tick toutes les 3s rappelle aussi `fetchPipelineDiagnostic(silent=true)` pour rafraîchir la liste d'events — sans ça, la barre cyan ne bougeait pas même avec les events backend qui arrivent.

Résultat : pendant le run Edge TTS parallèle des 2 journées, chaque journée affiche sa propre barre cyan qui avance indépendamment de l'autre, sans avoir à F5.

### ui(formation-pipeline): détection « stale audio running » + débloque les boutons Relancer

Quand Azure App Service redémarre le backend en plein run TTS (déploiement GitHub Actions, scaling instance, etc.), les greenlets eventlet meurent silencieusement et le `formation_pipeline_jobs.status` reste figé à `audio_running` indéfiniment. Conséquence côté UI : `audioBusy = AUDIO_ACTIVE_STATUSES.has(job.status)` reste `true` → tous les boutons « Relancer » affichent `…` et sont désactivés → l'utilisateur ne peut plus rien relancer.

**Détection heuristique** dans `FormationPipeline.jsx` :
- Lecture du timestamp du dernier event audio (filtre `step === 'audio' || event_type starts_with 'audio_'`).
- Si `AUDIO_ACTIVE_STATUSES.has(status)` ET dernier event > **3 min** → considère le run comme « stale ».
- `audioBusy` ignore alors `audio_running` (mais reste vrai pendant `launchingAudio` court instant après un clic frais).

**Bandeau d'avertissement orange** juste avant les boutons Relancer quand stale :
> ⚠️ Pipeline probablement interrompue
> Le job est marqué « en cours » mais aucun événement audio n'a été émis depuis X min. Cause typique : redémarrage Azure App Service (déploiement, scaling) qui tue les greenlets en plein run sans nettoyer le statut DB.
> Les boutons « Relancer » ci-dessous sont activés — un nouveau run remplacera proprement l'ancien.

**Côté backend rien à changer** : `launch_audio` accepte déjà un relancement même si le statut est `audio_running` (il fait juste `update_job(status="audio_running")` sans vérification préalable du status d'avant — confirmé via grep).

**Workaround utilisateur tant que ce fix n'est pas déployé** : tu peux SQL-update manuellement `formation_pipeline_jobs SET status='audio_error' WHERE id=8` côté Azure si tu veux débloquer maintenant.

### feat(formation-pipeline): parallélisation inter-folders pour Edge TTS (~40% plus rapide)

Lancement audio en parallèle (1 greenlet par journée, GreenPool eventlet) activé **uniquement** pour Edge TTS et mock. Fish Audio reste séquentiel à cause du rate limit + coût.

**Backend** (`backend/routes/formation_routes.py`)
- Route `launch-audio` accepte `parallel_folders` (int, défaut env var `AUDIO_PARALLEL_FOLDERS` ou 1).
- Hard cap côté serveur : `parallel_folders=1` forcé si `basic_tts=False` (Fish payant), même si le frontend envoie une valeur > 1. Filet de sécurité contre coût/rate-limit Fish Audio.
- `_run_all_audios_sequential` renommée `_run_all_audios` et branche entre :
  - Mode parallèle : `eventlet.GreenPool(size=parallel_folders)` + `GreenPile`, **pas de cooldown**, `next_folder_id=None` à tous les folders (le carryover inter-jours n'a pas de sens quand Jour 2 démarre avant que Jour 1 ait fini).
  - Mode séquentiel (Fish ou défaut) : comportement actuel inchangé (1 folder à la fois + cooldown 30s).

**Frontend** (`frontend/src/pages/FormationPipeline.jsx`)
- `handleLaunchAudio` accepte un nouveau paramètre `parallelFolders` (défaut 1) et le passe dans le body **uniquement si basicTts ou mock** (defense en profondeur).
- Les 3 boutons Edge TTS (basique premier lancement + basique relance + slides+Edge relance + slides+Edge premier lancement) passent `parallel_folders = nb_days` → toutes les journées en parallèle.
- Les 3 boutons Fish Audio (premier lancement + relance payante + slides payant) restent inchangés (séquentiel).
- Labels enrichis : `⚡ Relancer Edge TTS voix basique (2 journées en parallèle · 0€ · ~10 min)` au lieu de `(... · ~15 min)`.
- Note d'info violette enrichie avec un encart orange pour Edge (parallèle, plus rapide, pas de carryover) et un encart blanc pour Fish (séquentiel, coût, cooldown 30s).

**Gain mesuré attendu**
- Edge TTS basique 2 journées : ~15 min → **~10 min** (gain ~33% sans compter le skip du cooldown 30s).
- Edge TTS slides 2 journées : ~25 min → **~17 min** (gain ~32%).
- Pour 3+ journées le gain s'accentue puisque le facteur de parallélisme augmente.

**Limites**
- Pas de carryover de surplus runtime-fit entre journées en mode parallèle (Jour 2 ne reçoit pas le débord éventuel de Jour 1). Acceptable pour les sessions Edge de test ; pour le rendu de production via Fish, on garde le séquentiel donc le carryover marche normalement.
- Plusieurs greenlets simultanés sollicitent les serveurs Edge Microsoft en parallèle. Risque rate limit faible côté Microsoft mais non nul ; si ça arrive, baisser `parallel_folders` à 2 ou repasser séquentiel via env var `AUDIO_PARALLEL_FOLDERS=1`.

### ui(formation-pipeline): boutons « Relancer TTS » plus explicites sur le périmètre + coût + durée

Suite à confusion utilisateur (pensait que le bouton relançait juste les segments dirty alors que le backend utilise `force_all=True` par défaut), les boutons et leur contexte sont maintenant auto-explicites :

- **Note d'info violette** au-dessus des boutons : « Régénération **complète** par défaut » avec rappel que chaque clic réécrit **tous** les MP3 (19/jour × N jours) et que `course_script_plan.json` + `audio_sync.timings` sont réécrits alignés sur les nouveaux MP3.
- **Labels enrichis** : `(N journées · 0€ · ~15 min)` pour Edge basique, `(N journées · ~18$ · ~150 min)` pour Fish payant, etc. Le coût Fish est calculé à 9$/journée.
- **Tooltips étoffés** : commencent tous par « Régénération COMPLÈTE » (en majuscules), précisent moteur TTS, coût exact, fourchette de temps, et mention "ÉTAPE IRRÉVERSIBLE côté facturation" pour les variantes payantes.
- Renommage `Relancer TTS test (gratuit)` → `Relancer TTS test silence (N journées · 0€)` pour clarifier que c'est juste du silence MP3, pas une vraie synthèse.

Aucun changement de comportement backend.

### ui(formation-pipeline): tous les boutons « Relancer TTS » affichent désormais le nombre de journées

Avant, seul « Lancer le TTS » (Fish Audio) précisait le périmètre (`(N journées)`). Les boutons Edge TTS et leurs variantes slides n'indiquaient pas qu'ils couvraient eux aussi **toutes les journées du job** (le backend `_run_all_audios_sequential` boucle sur `folder_ids` indépendamment du moteur TTS choisi). Conséquence : ambigüité visuelle qui faisait croire que le bouton Edge ne couvrirait peut-être qu'un seul dossier.

Tous les boutons relance utilisent maintenant le même template : `« Relancer <mode> (N journées) »` où N = `contentFolders.length || job.nb_days`. Comportement backend inchangé.

### feat(content-review): revérif post-TTS + splice MP3 automatique sur règles apprises (Phase 3b)

L'admin peut désormais déclencher une **revérification automatique** de tous les chunks audio d'un dossier contre le markdown des règles (Phase 3a). DeepSeek parcourt chaque chunk via `audio_sync.timings`, vérifie la conformité, propose une réécriture minimale si nécessaire, et **patche le MP3 ms-précis** via la même primitive que Phase B. Deux modes : **Simuler** (dry_run, n'écrit rien) et **Appliquer aux MP3** (modifie Azure en place).

**Backend** (`backend/services/script_rules_service.py`)
- `_word_slice(text, start, end)` : extrait le texte d'un chunk depuis les indices de mots.
- `_build_review_prompt(rules_markdown, chunk_text)` : prompt DeepSeek qui demande un JSON strict `{conforme: bool, violations: [...], corrected_text: ...}`. Contrainte explicite : réécriture **minimale**, conserve longueur/ton/niveau RNCP.
- `_parse_review_response(raw)` : extrait le premier JSON valide de la réponse (gère le fenced markdown ```json … ```).
- `review_chunks_with_rules(folder_id, *, dry_run, bloc_numbers, max_chunks)` :
  - Filtre les timings non-patchés du deck (`patched=True` ignoré).
  - Groupe par bloc, charge le texte de chaque bloc via `_course_bloc_text`.
  - Pour chaque chunk : DeepSeek → si non conforme → splice via `splice_chunk_audio` extrait de Phase B.
  - **Important** : relit `audio_sync.timings` à chaque chunk pour gérer les décalages accumulés par les splices précédents dans le même bloc (sinon les bornes seraient fausses après le 1er splice).
  - Retourne `{chunks_examined, chunks_corrected, chunks_skipped, chunks_failed, details: [...]}`.

**Refactor** (`backend/services/script_annotation_service.py`)
- Extraction de la primitive `splice_chunk_audio(folder_id, platform_id, *, deck, audio_sync, filename, splice_start_sec, splice_end_sec, new_text, word_start, word_end_target, slide_id_for_patch)` rendue **publique et réutilisable**.
- `_attempt_audio_splice` (Phase B annotations) délègue désormais à cette primitive après avoir résolu word_range et chevauchement timings. Le comportement reste identique, juste DRY.

**Endpoint HR**
- `POST /api/hr/cours-folders/<id>/content-job/rules/review-post-tts` — accepte `{dry_run, bloc_numbers, max_chunks}` dans le body.

**Frontend** (`frontend/src/components/CoursFolders.jsx`)
- 2 nouveaux boutons dans le panneau Règles : **Simuler** (dry_run) et **Appliquer aux MP3** (avec `window.confirm` parce que l'action modifie les MP3 sur Azure).
- Bloc de résumé affichant : examinés / corrigés (ou « à corriger » en simu) / skipped / échecs. Liste les 6 premières corrections avec filename, bloc, violations détectées, statut splice (done/error/would_correct).

**Garanties**
- Best-effort par chunk : un échec n'arrête pas la revérif des suivants.
- Les chunks déjà patchés (par annotation ou revérif précédente) sont ignorés via le flag `patched: true` du timing.
- Mode dry_run pour valider le prompt sans écrire sur Azure.

**Workflow complet désormais possible**
1. Tu surlignes + commentes dans la modal Script TTS (Phase A) → DeepSeek propose une correction → tu valides → MP3 splicé ms-précis (Phase B).
2. Après quelques annotations, tu cliques « Extraire » dans le panneau Règles → DeepSeek produit un markdown de règles transversales (Phase 3a). Tu peux l'éditer à la main.
3. Tu cliques « Simuler » → tu vois quels chunks DeepSeek voudrait corriger sans rien modifier. Si tu es d'accord, « Appliquer aux MP3 » → patch automatique de tous les chunks non conformes (Phase 3b).

### feat(content-review): extraction DeepSeek de règles transversales depuis les annotations (Phase 3a)

À partir de toutes les annotations d'un dossier cours (applied + rejected + proposed), DeepSeek extrait un **markdown de règles transversales** qui décrit les patterns récurrents de corrections demandées par le formateur. Ce markdown alimente la Phase 3b à venir : un agent de revérification post-TTS qui patche automatiquement les chunks audio non-conformes via la primitive de splice MP3 ms-précis (Phase B).

**Backend**
- Nouvelle table `content_script_rules` (folder_id, job_id, rules_markdown, rules_count, source_annotations_count, model, markdown_path, generated_at, updated_at) avec UNIQUE(folder_id, job_id) + index (`backend/database/db.py`).
- Nouveau service `backend/services/script_rules_service.py` :
  - `_fetch_applied_annotations` récupère les annotations applied (corrections validées) + rejected (signal négatif : règle à NE PAS extraire) + proposed (en cours).
  - `_build_llm_prompt` formate le contexte programme + N corrections (commentaire, extrait, avant/après, statut) pour DeepSeek. Le prompt explicite que les corrections rejetées sont un signal négatif à ne pas inclure dans le markdown.
  - `extract_rules_from_annotations(folder_id)` appelle DeepSeek (modèle par défaut `DEEPSEEK_DEFAULT_MODEL`, override env `SCRIPT_RULES_MODEL`), parse le retour, persiste en DB (`ON CONFLICT DO UPDATE`) et sur disque (`tts_script_reviews/regles-folder-X-job-Y.md`).
  - `get_rules(folder_id)` lecture, `update_rules_markdown(folder_id, markdown)` édition manuelle (l'admin peut éditer le markdown à la main pour ajouter/retirer/affiner des règles avant la Phase 3b).
- 4 endpoints HR (`backend/routes/hr_routes.py`) : GET `/content-job/rules` (lecture), POST `/content-job/rules/extract` (déclenche extraction), PUT `/content-job/rules` (édition manuelle), GET `/content-job/rules/markdown` (download).

**Frontend** (`frontend/src/components/CoursFolders.jsx`)
- Nouveau bouton « Règles (N) » dans le header de la modal Script TTS, à côté du bouton Markdown.
- Panneau collapsible (couleur jaune `#facc15`) qui affiche : nombre d'annotations source, modèle, date de génération, le markdown des règles dans un `<pre>` scrollable, et boutons « Extraire » / « Ré-extraire » + « Markdown » (download).
- États : `scriptRules`, `rulesPanelOpen`, `extractingRules`, `rulesError`. Chargement auto via `loadScriptRules()` à l'ouverture de la modal.

**Phase 3b (à venir)** — un agent de revérification post-TTS lit le markdown des règles + parcourt chaque chunk audio via `audio_sync.timings`, demande à DeepSeek si chaque chunk respecte les règles, et patche le MP3 chirurgicalement via la primitive Phase B sur les portions non-conformes.

### feat(content-review): splice MP3 chirurgical ms-précis au moment du Appliquer (Phase B)

Quand l'admin clique « Appliquer » sur une annotation `source_type=course`, le backend ne se contente plus de marquer le bloc `dirty=1` — il **patche directement le MP3 en place sur Azure** au millisecond près. Plus besoin de régénérer 10 min de TTS pour corriger 30 secondes.

**Comment ça marche**
1. Récupère le `script_slide_deck` du job → `audio_sync.timings` (déjà persistés à chaque génération de chunk audio, lignes ~1198 de `content_generation_service.py`). Chaque timing porte `{slide_id, audio_filename, start_time, end_time, word_start, word_end}`.
2. Récupère le texte complet du bloc cours via `get_course_script_plan_for_ui`.
3. `_find_word_range` localise `original_paragraph` dans le texte du bloc (matching normalisé sur espaces, fallback case-insensitive) → indices de mots.
4. Filtre les timings du même `audio_filename` dont la plage `[word_start, word_end]` chevauche le paragraphe → `splice_start_sec` / `splice_end_sec`.
5. Génère le TTS du `proposed_text` via `convert_to_speech` (Fish Audio S2-Pro).
6. Télécharge le MP3 original depuis Azure (`audiostts/platform-X/folder-Y/playlist/<filename>`), splice via pydub avec crossfade 25 ms aux jointures.
7. Re-uploade le MP3 patché à la même URL.
8. `_splice_recompute_timings` : retire les timings de la plage spliced, insère un timing `patched-<annotation_id>` avec la nouvelle durée, **décale tous les timings suivants** du delta `(new_dur - old_dur)`. Persisté via `update_script_slide_deck_audio_sync`.

**Garanties**
- Best-effort : toute exception est attrapée et stockée dans `splice_error`. L'apply reste réussi (correction_status=applied) même si le splice échoue.
- `source_type=course` + splice OK → segment source NON marqué `dirty=1` (sinon la prochaine régénération bloc écraserait le splice).
- `source_type=segment` → patch texte segment + `dirty=1` (comportement Phase A préservé, pas de splice direct).

**Nouvelles colonnes** (`content_script_annotations`)
- `splice_status` : `done | error | skipped`
- `splice_error` : message d'erreur si échec
- `splice_blob_path` : chemin Azure du MP3 patché (pour audit)

**Frontend** : badge « 🎯 MP3 patché ms-précis » (vert) ou « Splice échoué : … » (rouge) sous le diff Avant/Après, visible uniquement quand `correction_status=applied`.

**Limite connue (à corriger Phase 3)** — pour `source_type=course` avec splice OK, le texte source en DB n'est PAS mis à jour parce qu'on ne sait pas dans quel segment se trouve le passage. Conséquence : si l'utilisateur clique plus tard « régénérer tout », le bloc complet sera re-TTS-é depuis le texte source non corrigé, écrasant le splice. Workaround pour rendre une correction durable : annoter depuis l'onglet « Source » (`source_type=segment`).

### feat(content-review): correction immédiate DeepSeek sur sélection — preview avant/après (Phase A)

Quand l'admin surligne du texte dans la modal Script TTS et ajoute un commentaire, DeepSeek réécrit le paragraphe alentour en appliquant la consigne. La proposition apparaît côte-à-côte (Avant / Après) dans le panneau d'annotation, avec boutons Appliquer / Rejeter. Sur Appliquer, le texte du segment source est mis à jour en DB et le segment marqué `dirty=1 reviewed=0` — la prochaine régénération audio le re-fera. Étape suivante (Phase B) : splice MP3 chirurgical au moment de Appliquer, pour ne PAS re-générer tout le bloc de 10 min.

**Backend**
- Migration `content_script_annotations` (`backend/database/db.py` + `backend/services/script_annotation_service.py::_ensure_annotations_table`) : ajout colonnes `original_paragraph`, `proposed_text`, `correction_status` (`pending|proposed|applied|rejected|error`), `correction_error`, `applied_at`. ALTER TABLE défensif pour les bases déployées.
- Nouveau service `correct_paragraph_with_llm(paragraph, selected_text, comment) -> str` via `post_message` du client Anthropic-compatible. Modèle par défaut : `DEEPSEEK_DEFAULT_MODEL` (override via env `SCRIPT_ANNOTATION_MODEL`). Prompt cadré : conservation niveau RNCP + ton oral + longueur, modification limitée à ce que le commentaire demande.
- Helper `_extract_paragraph_around(full_text, selected_text)` : trouve le paragraphe contenant l'extrait (séparation `\n\n`), gère chevauchement multi-paragraphes par union.
- `create_script_annotation` accepte `paragraph_context` (texte du conteneur affiché côté frontend). À la création, persiste l'annotation puis appelle DeepSeek en best-effort (`_attach_correction`) — sur erreur, `correction_status=error` mais l'annotation reste utilisable.
- `apply_script_annotation(folder_id, annotation_id)` : pour `source_type=segment`, remplace `original_paragraph` par `proposed_text` dans `content_generation_segments.text_content`, recalcule `word_count`, met `dirty=1 reviewed=0 review_error=NULL`. Pour `source_type=course`, marque seulement l'annotation applied (Phase B prendra le splice MP3).
- `reject_script_annotation(folder_id, annotation_id)` : marque `correction_status=rejected` sans toucher au texte.

**Endpoints HR** (`backend/routes/hr_routes.py`)
- `POST .../annotations/<aid>/apply` — applique la correction.
- `POST .../annotations/<aid>/reject` — rejette la proposition (l'annotation reste tracée pour le markdown et l'apprentissage Phase 2).

**Frontend** (`frontend/src/components/CoursFolders.jsx`)
- `captureScriptSelection` envoie désormais `paragraph_context = event.currentTarget.textContent` (limité à 8000 chars).
- `applyAnnotationCorrection` / `rejectAnnotationCorrection` : nouveaux handlers HTTP.
- `ScriptAnnotationsList` : badge de statut, panneau Avant / Après côte-à-côte quand `correction_status != pending`, boutons Appliquer / Rejeter visibles uniquement quand `proposed`. Affichage erreur DeepSeek si `error`.

**Limitations Phase A** — La régénération audio reste à la granularité bloc (1 MP3 ~10 min) via le flag `dirty`. La Phase B suivra avec splice chirurgical ms-précis utilisant `audio_sync.timings` déjà persistés par la pipeline.

### feat(content-review): annotations humaines sur le script TTS + markdown de revue

Nouveau flux de revue collaborative sur le script TTS d'un dossier cours : l'admin sélectionne du texte dans le modal Script TTS, ajoute un commentaire de correction, et l'ensemble est persisté + exporté en markdown pour réinjection dans l'agent de correction avant régénération audio.

**Backend**
- Nouvelle table SQLite `content_script_annotations` (folder_id, job_id, source_type, sub_part_index, passe, bloc_number, filename, selected_text, comment, status, markdown_path) + index `(folder_id, job_id, status)` (`backend/database/db.py`).
- Nouveau service `backend/services/script_annotation_service.py` : CRUD annotations + génération du markdown de revue avec contexte (titre programme, type source, bloc, filename).
- 4 nouveaux endpoints HR (`backend/routes/hr_routes.py`) :
  - `GET    /api/hr/cours-folders/<id>/content-job/annotations` — liste
  - `POST   /api/hr/cours-folders/<id>/content-job/annotations` — création
  - `DELETE /api/hr/cours-folders/<id>/content-job/annotations/<aid>` — suppression logique
  - `GET    /api/hr/cours-folders/<id>/content-job/annotations/markdown` — export markdown
- L'endpoint `GET .../content-job/script` retourne désormais aussi `annotations`, `annotations_count`, `annotations_markdown_path` pour pré-remplir le modal.

**Frontend** (`frontend/src/components/CoursFolders.jsx`)
- Capture de la sélection texte dans le modal Script TTS (`captureScriptSelection`) avec context source (source_type, sub_part_index, passe, bloc_number, filename).
- Panneau d'annotation : champ commentaire, save, liste des annotations existantes, suppression, état d'erreur.
- Persistance synchronisée avec le modal (`scriptAnnotations`, `annotations_markdown_path`).

**Pourquoi** — la régénération audio coûte cher (Fish Audio S2-Pro) et le script TTS est long. Avant cette feature, les corrections humaines transitaient par chat / capture d'écran et étaient perdues entre deux passes. Le markdown de revue centralise désormais toutes les corrections demandées, prêt à être consommé par l'agent de correction LLM avant la passe suivante.

### fix(content-review): création paresseuse de `content_script_annotations` sur bases déployées

Ajout de `_ensure_annotations_table()` dans `script_annotation_service.py`, appelé en tête des fonctions `list / create / delete / write_markdown`. Crée la table + index si absents (CREATE TABLE IF NOT EXISTS), pour les environnements P2/P3/P4 où `init_database()` n'a pas encore été rejoué depuis le déploiement de la feature annotations.

## 2026-05-11

### feat(pipeline): robustesse auto-pilot — résolution canonique des dossiers cours + diagnostic UI

Refonte ciblée de la pipeline formation auto-pilot pour fiabiliser l'enchaînement contenu → TTS quand des doublons de dossiers apparaissent (double-clic « Lancer », retry après crash, relance manuelle d'une journée).

**1. Résolution canonique des dossiers cours** (`backend/services/formation_pipeline_service.py`)
- Nouvelle fonction `get_expected_course_folders(job_id, *, create_missing=False)` : pour chaque journée `daily_programs[i]`, on cherche le `cours_folder` correspondant par `name` exact (`expected_course_folder_name`) et on garde **un seul** folder canonique par jour. Tri par priorité : `cg_status == 'completed'` > `total_words > 0` > `running` > `idle` > pas de job > autre, puis `total_words DESC`, `segments_completed DESC`, `position ASC`, `id ASC`.
- Retourne `{folder_ids, duplicates, missing, created, expected_count}` — les doublons restent en DB mais ne sont plus consommés en aval.
- `launch_tts_for_all_days(...)` réécrit pour s'appuyer sur ce résolveur (avec `create_missing=True`) au lieu de re-créer aveuglément un folder par journée.
- Helper `expected_course_folder_name(day_data, fallback)` mutualisé.

**2. Health check ciblé canonique** (`backend/services/formation_health_service.py`)
- `compute_health()` n'audite plus tous les `cours_folders` avec `formation_job_id == job_id` (qui incluent les doublons) — il appelle `get_expected_course_folders(job_id)` et restreint la requête aux `folder_ids` canoniques via `IN (?, ?, ...)`.
- Nouveau check `course_folders_expected` : `ok = len(folders) == nb_days and not missing_folders`. Les doublons sont remontés en `warnings` sans casser le check.
- Fallback safe en cas d'exception du résolveur (`resolution_failed` dans `missing`).

**3. AI stop decision + carryover runtime cours** (`backend/services/content_generation_service.py`)
- `_ai_should_defer_chunk_before_conclusion(...)` : décision pilotée par LLM (Claude) sur le fait de garder un chunk pour la conclusion plutôt que de le sortir dans le bloc courant. Guardé par `_course_ai_stop_decision_enabled()` (flag `AI_COURSE_STOP_DECISION_ENABLED`) + fenêtre temporelle `_course_ai_stop_window_sec()`.
- `_rewrite_runtime_carryover_chunks(...)` : réécrit les chunks de carryover récupérés du bloc précédent pour qu'ils enchaînent naturellement (suppression de répétitions, ajout d'une accroche).
- `_parse_course_handoff_json(...)` + `_fallback_course_opening(...)` : gestion robuste du handoff opening/closing entre blocs cours, avec fallback statique si le JSON Claude est invalide.
- Helpers `_compact_words` / `_tail_words` / `_extract_llm_json` pour le pré-traitement des prompts.
- `_snapshot_pre_review_for_content_job(job_id)` : capture les fichiers actifs avant review pour pouvoir comparer ensuite.

**4. Persistance des review reports** (`backend/services/claude_code_mission_service.py`)
- `_persist_review_reports_from_active_files(job_id, generated_via)` : lit les fichiers de review générés par Claude Code Mission et les persiste en blob pour rester accessibles même après nettoyage local.

**5. Diagnostic auto-pilot exposé via API** (`backend/routes/formation_routes.py`, ~400 lignes touchées)
- Les endpoints diagnostic auto-pilot retournent désormais `folder_resolution: {expected_count, folder_ids, duplicates, missing}` + `events` enrichis avec status `running`.
- Le frontend reçoit de quoi afficher l'état réel de la résolution sans re-requêter la DB.

**6. UI bandeau actif Pipeline** (`frontend/src/pages/FormationPipeline.jsx`)
- Nouveau composant `PipelineActiveNotice({ job, autoPilotState, diagnostic, contentFolders })` : affiche le step auto-pilot courant (mapping `AUTO_PILOT_STEP_LABELS`), le folder actif, le compteur `completed/expected`, la liste des doublons détectés, le modèle Claude et le mode TTS en cours.
- Bandeau `showGlobalAudioSummary` quand `folders.length > 1`.

**Pourquoi maintenant** — la pipeline auto-pilot enchaîne en série création folder → contenu → TTS, et un double-clic sur « Lancer » créait 2 dossiers `"Jour 1 — …"` avec 2 `content_generation_jobs` en parallèle. Le health check tombait à mi-pipeline et l'utilisateur perdait du temps à comprendre quel folder était le « bon ». Maintenant on a un canonical résolu côté backend, et l'UI le montre.

### fix(ui): label « gTTS » → « Edge TTS » dans le dropdown auto-pilot

Le dropdown « Voix TTS pour l'étape audio » du formulaire « Nouvelle plateforme » (HRDashboard) affichait encore « gTTS — voix basique gratuite (recommandé pour test) » alors que la migration gTTS → Edge TTS a déjà été faite côté backend (cf. `9de3898`). L'identifiant DB historique reste `"gtts"` (utilisé par `auto_pilot_tts_mode`, `tts_mode`, `voice_type`, mapping `basic_tts == (tts_mode == "gtts")` dans `formation_routes.py`), mais le pipeline route déjà vers Edge TTS (voix neurales Microsoft).

Modif minimale : libellé seulement, sans toucher à la valeur `"gtts"` ni au backend. Cohérent avec `FormationPipeline.jsx:238` qui affichait déjà « Edge TTS — voix basique gratuite » ailleurs dans l'UI.

## 2026-05-10

### feat: modal Script TTS affiche le texte réellement lu (même si script modifié depuis)

**Symptôme** — la vue « Cours audio » affichait le découpage théorique (label « Prévu · N mots ») même quand un audio avait été généré juste avant et qu'on avait toute l'info pour montrer le texte réellement envoyé au TTS (avec opening reformulé, conclusion Edge TTS runtime ajoutée, carryover consommé). Dès qu'on touchait un segment côté Sous-parties, ou que la pipeline marquait un bloc dirty, on perdait l'accès au texte vraiment lu.

**Cause** — `get_course_script_plan_for_ui` ne retournait le plan persisté que si `dirty_blocs == 0`. Sinon → preview, alors qu'on a déjà `_save_course_script_plan(...)` qui stocke en blob Azure le `course_script_plan` rempli depuis `_record_course_bloc` (lignes 3722-3747) avec `course_text_for_ui` = `runtime_consumed_text` + conclusions runtime — donc le vrai texte envoyé au TTS.

**Backend** (`content_generation_service.py`, `get_course_script_plan_for_ui`)
- Prio inconditionnelle au plan persisté dès qu'il existe et qu'il contient `course_blocs`. Le flag `course_blocs_source="last_audio_generation"` est conservé.
- Nouveau champ `course_blocs_stale` (bool) : vrai si `dirty_blocs > 0`. Le frontend l'utilise pour basculer le bandeau d'info en orange « warning » au lieu d'une teinte neutre.
- `course_blocs_note` intègre directement le ratio « X/Y bloc(s) à régénérer » quand stale ; le frontend ne fait plus la concaténation lui-même.

**Frontend** (`CoursFolders.jsx`)
- Bandeau de note du panneau Cours audio : palette orange (`#fff7ed` / `#fed7aa` / `#c2410c` en clair, `#431407` / `#7c2d12` / `#fdba74` en sombre) quand `course_blocs_stale` est vrai. Sinon palette neutre (inchangée).

### feat: textes Q&A/pauses génériques restaurés + visibles dans le modal Script TTS

**Backend — `_generic_break_texts` simplifiée** (`content_generation_service.py`)
- Le commit `52525f1` (07/05) avait ajouté un texte « du milieu » entre intro et outro (« Je vous laisse utiliser ce temps… », « Profitez-en pour souffler, vous étirer… ») et un outro spécial « Très bien, on clôt cette session de questions… » quand un Q&A précède une pause. Restauration des variants statiques d'origine : `_generic_break_texts` retourne directement `(intro, outro)` issus de `_get_qa_text` / `_get_pause_text` / `_get_pause_midi_text` (`playlist_tts_service.py`).
- `_generic_basic_tts_break` n'a plus à concaténer `intro + middle` ; le texte passé à `_build_timed_edge_break_audio` est désormais celui des variants `_QA_VARIANTS` / `_PAUSE_VARIANTS` exactement.
- Les variants `_QA_VARIANTS` / `_PAUSE_VARIANTS` / `_PAUSE_MIDI_INTRO` / `_PAUSE_MIDI_OUTRO` ne sont pas modifiés : on ne fait que ré-utiliser les anciens textes tels quels.

**Backend — exposition des textes breaks à l'UI** (`content_generation_service.py`)
- Nouvelle helper `_build_breaks_for_ui(platform_id)` : retourne les textes intro/outro statiques pour chaque Q&A/pause de la playlist effective (`_playlist_items_for_platform` — donc le mode été/hiver est respecté). Pour chaque break : `filename`, `duration_sec`, `type`, `bloc_number`, `intro`, `outro`.
- `get_course_script_plan_for_ui` renvoie désormais une clé `breaks` à côté de `course_blocs`.
- Limite assumée : si un jour Fish Audio est utilisé avec le LLM contextuel, les textes réellement prononcés ne sont pas persistés et ne peuvent donc pas être affichés ; on montre les variants statiques (qui restent le fallback).

**Frontend — vue « Cours audio » étendue** (`CoursFolders.jsx`)
- Nouveau state `scriptActiveBreak` (par filename) en parallèle de `scriptActiveCourse`. Cliquer sur un break désactive la sélection cours et inversement (un seul item actif à la fois dans la sidebar).
- Sidebar : sous la liste des 7 cours, nouvelle section « Q&A et pauses » avec un item par Q&A/pause de la playlist (icône `forum` pour Q&A, `restaurant` pour la pause déjeuner, `pause_circle` pour les pauses courtes).
- Panneau de détail : quand un break est sélectionné, affichage de l'intro et de l'outro dans deux blocs distincts (police monospace, `whitespace-pre-wrap`), avec un bandeau d'info qui rappelle que le reste du créneau est rempli en silence Edge TTS.

### feat: aperçu « Cours audio » dans le modal Script TTS + garde-fous closings

**Backend — plan de découpe des cours pour l'UI** (`content_generation_service.py`)
- Nouvelles helpers : `_course_filename_for_bloc`, `_course_duration_for_bloc`, `_serialize_course_bloc`, `_load_segments_for_course_plan`, `_build_course_blocs_preview`, `_load_saved_course_script_plan`, `_save_course_script_plan`, `get_course_script_plan_for_ui`.
- Mode `preview=True` pour `_build_course_blocs_from_segments` / `_handle_last_bloc_overflow` : pas de remaniement API, pas de carryover persisté ; flag `overflow_unresolved` + `overflow_words` posé sur le dernier bloc si dépassement budget.
- Capture systématique du texte des conclusions/closings (`closing_text`, et `text` dans `attempts`) pour les rendre visibles côté UI.
- `_record_course_bloc()` interne à `generate_audio_from_script` : enregistre statut (`generated` / `preserved` / `preview` / `skipped`), durée finale, texte, opening reformulé, runtime conclusions ajoutées.

**Backend — route exposée** (`hr_routes.py`) — `GET /api/hr/cours-folders/<id>/content-job/script` renvoie en plus `course_blocs` (via `get_course_script_plan_for_ui`) à côté des `sub_parts`.

**Backend — closings durcis** (`closing_transition_service.py`)
- Regex `_FORBIDDEN_DEICTIC_RE = \b(hier|demain)\b` : si le LLM ressort un closing contenant ces marqueurs temporels, on lève `ValueError` et on bascule en fallback statique. Évite les closings qui prétendent qu'« hier » s'est passé X ou que « demain » sera Y.
- Nouvelle consigne dans les 3 prompts (court / moyen / long) : « N'invente jamais une échéance d'examen, un passage devant jury ou un contexte de certification daté qui n'apparaît pas explicitement dans l'extrait. »
- Fallback long retravaillé : « on garde ces repères pour la suite du parcours » au lieu de « on se retrouve juste après pour la suite » (cohérent avec la règle no-`questions`/`pause`/`après`).

**Frontend — vue « Cours audio »** (`CoursFolders.jsx`)
- Toggle dans le header du modal Script TTS : `Sous-parties` (vue source historique) ↔ `Cours audio` (nouvelle vue).
- Sidebar gauche : liste des blocs cours avec numéro, durée min, statut (`Généré` / `Conservé` / `Prévu` / `Ignoré`), nb mots, indicateur « conclusion ajoutée ».
- Vue principale : texte du cours sélectionné (avec marquage closing/runtime conclusions), désactivée tant qu'aucun `course_blocs` côté API.
- Sélection initiale = bloc 1 (ou premier disponible). Bordure active passe d'un `borderLeft` à un `boxShadow` inset 1px violet (cosmétique cohérente sidebar source).

**Frontend — templates slides — polish visuel**
- `ComparisonTemplate.jsx` : suppression du `Header` interne (badge TP-CRCD / brand) — désormais géré par le shell de slide. Palette adoucie : rouge `#DC2626` → `#E07A6F`, vert `#16A34A` → `#A7B85A` ; passage à `ComparisonTemplate.module.css`.
- Ajustements typographiques / espacements / radius sur `AnalogyTemplate`, `OpinionTemplate`, `RecapTemplate`, `TipTemplate`, `TransitionTemplate`, `casestudy`, `chart`, `facilitator`, `playful`, `reflection`.
- Mineurs `StatsTemplate.jsx`, `StoryTemplate.jsx`, `RecapTemplate.jsx`, `AnalogyTemplate.jsx`.

## 2026-05-07

### feat: génération audio cours pilotée par la durée réelle Edge TTS (runtime fit + carryover)

**Symptôme** — un cours cible 45 min sortait à 50 min en mode Edge TTS. Le découpage 7 blocs reposait uniquement sur un budget de mots calé à 192 wpm Fish Audio, alors qu'Edge TTS lit à ~170 wpm → ratio 1.13× sur la durée. Conséquence supplémentaire : si le script journée dépasse le budget total, le surplus était absorbé par le bloc 7 au lieu d'être reporté proprement au jour suivant.

**Nouveau modèle (Edge TTS uniquement, Fish Audio inchangé)** — le texte de la journée est traité comme une file ordonnée de chunks. Chaque bloc cours consomme la file progressivement en mesurant la durée réelle Edge TTS et stoppe **avant** dépassement. Conclusion courte ajoutée. Surplus reporté au bloc suivant ou au jour suivant.

**Architecture** — 5 étapes commitées séparément pour faciliter le review :

1. **Helpers de découpe** (`content_generation_service.py`) — `_max_chunk_words_for_remaining` (paliers adaptatifs 600 / 300 / 150 / 0 mots selon la marge restante), `_split_text_natural` (paragraphes → phrases, **jamais de split intra-phrase** : une phrase plus grosse que le plafond reste entière), `_split_chunk_for_runtime_fit` (préserve `slide_id`, recalcule `word_start` / `word_end`).

2. **Conclusion audio** — `_synthesize_short_conclusion_audio(basic_tts=True)` génère un MP3 court depuis un template configurable (`EDGE_TTS_CONCLUSION_TEMPLATE`, défaut "Très bien, on va s'arrêter ici pour cette partie. On reprendra la suite dans la prochaine.").

3. **Runtime fit** dans `_synthesize_course_audio_synced_to_slides` — nouveaux paramètres `prepended_chunks`, `conclusion_margin_sec` (défaut 90 s, env `EDGE_TTS_CONCLUSION_MARGIN_SEC`), `runtime_fit`. Boucle `while` qui :
   - calcule `remaining_sec = target_sec - margin - cursor_sec` à chaque itération ;
   - récupère le plafond de mots adaptatif ;
   - sub-chunke JIT le chunk courant si nécessaire (frontière naturelle) ;
   - estime la durée du sous-chunk via `observed_wpm` (bootstrap 170, recalculé à mesure : `total_words_generated * 60 / total_duration_generated`) ;
   - stoppe et reporte intégralement le sous-chunk si `cursor + estimated > target - margin + 2s` (tolérance arrondi MP3) ;
   - injecte la conclusion via `_synthesize_short_conclusion_audio` quand stop volontaire ;
   - étend le `end_time` du dernier timing slide pour couvrir la conclusion (le frontend continue d'afficher la slide pendant la transition).
   Retour augmenté d'un 6e élément `unconsumed_chunks`. `fit_method = "slide_sync_edge_runtime_fit"`.

4. **Boucle orchestration** (`generate_audio_from_script`) — tampon `intra_day_carryover_chunks` propagé entre blocs cours. Bascule auto `clean → dirty` si carryover en attente sur un bloc qui était propre. Après le dernier cours : si tampon non vide, fusion avec le `carryover_out` statique (runtime EN PREMIER, statique APRÈS) puis `_store_cross_day_carryover(folder_id, next_folder_id, fused_text)`. Si pas de `next_folder_id` → log `WARNING PIPELINE_AUDIO_OVERFLOW_LOST` avec word count perdu. Logs structurés `PIPELINE_AUDIO_BLOC_RUNTIME` et `PIPELINE_AUDIO_RUNTIME_CARRYOVER`.

5. **Tests** (`backend/tests/test_audio_runtime_fit.py`) — 7 tests unittest avec mocks déterministes sur `convert_to_speech_basic`, `_mp3_duration_seconds_no_ffprobe` et `_synthesize_short_conclusion_audio`. Couvre : stop avant dépassement, conclusion ajoutée + extension du timing, prepended_chunks consommés en premier, mode par défaut sans cascade, ID3 unique après concat, helpers (palier adaptatif + frontière naturelle gardée).

**Garanties** — `voice_duration ≤ target_sec + 2s` (tolérance technique MP3). Aucun split intra-phrase. Le bloc 7 n'absorbe plus le surplus. Fish Audio strictement inchangé (pas de `runtime_fit`, pas de `prepended_chunks`). Mode mock inchangé.

**Calibration** — `MAX_CHUNK_WORDS` 600 / 300 / 150 fixés en constantes module ; à ajuster en env si besoin lors d'un futur tuning.

### fix: éditeur audio — proxy backend + race condition cleanup

**Symptôme** — l'éditeur affichait toujours `Impossible de charger l'audio : Failed to fetch` malgré le fix headers (`05d37cb`). Network montrait pourtant 200 + 17.6 Mo téléchargés. Console : aucune erreur CORS visible (juste une erreur d'extension Chrome `content.js`). Deux paires de requêtes identiques observées dans Network → indice de remount du composant React.

**Hypothèses non discernables à distance**

1. **CORS post-flight bloqué côté JS** — Azure Blob répond 200 mais sans `Access-Control-Allow-Origin`, le browser bloque le body côté JS et propage `TypeError: Failed to fetch`. Plausible mais pas confirmé (Chrome n'a pas affiché l'erreur dans Console).
2. **Race condition React** — `wavesurfer.js:319-321` attache un `AbortController` au fetch interne. Quand le useEffect se ré-exécute (re-mount, dépendance changée), `ws.destroy()` abort le fetch → `AbortError` que Chrome sérialise en `TypeError: Failed to fetch`. Le `.catch` dans `AudioEditor.jsx` ne filtrait pas ce cas et collait un message d'erreur sur la 1re tentative annulée, persistant même après que la 2e tentative ait chargé l'audio avec succès.

**Fix défensif (couvre les deux hypothèses)**

1. **Proxy backend** — `AudioEditor.jsx` charge maintenant le MP3 via la route `/api/hr/cours-folders/<id>/audio-stream/<filename>` (route `stream_audio_file` existante) au lieu de l'URL SAS Azure Blob directe. Plus de surface CORS à gérer côté Storage. WaveSurfer reçoit l'URL backend avec `fetchParams: { credentials: 'include' }` pour la session, et `blobMimeType: 'audio/mpeg'` en sécurité. Cache buster `?v=Date.now()` dans l'URL pour éviter de servir un cache stale après cut/replace.
2. **Backend `stream_audio_file`** — `Content-Disposition` quote correctement le filename via `os.path.basename`, ajout de `Cache-Control: no-store`. `Accept-Ranges` reste mais WaveSurfer 7 ne fait pas de Range request (vérifié dans `wavesurfer.js`), donc pas besoin d'implémenter `206 Partial Content`.
3. **Race condition** — flag `cancelled` dans le useEffect d'`AudioEditor.jsx`, `setError(null)` + `setLoading(true)` au début pour reset l'état d'erreur au remount, filtrage explicite des `AbortError` dans le `.catch` (ne pas afficher une erreur pour un cleanup normal).

**Trade-off à connaître** — le proxy fait transiter ~17 Mo via App Service France au lieu d'aller direct au blob régional. Latence d'ouverture de l'éditeur passe de ~4s à ~10-30s. Acceptable pour usage admin (cible : régénération de plateforme HR), à surveiller. `Cache-Control: no-store` force le retéléchargement à chaque ouverture — si un jour la latence devient gênante, remplacer par `private, max-age=300`.

### fix: headers MP3 Azure Blob (audio/mpeg + inline) pour éditeur audio

**Symptôme** — après le fix du 302:01, l'éditeur audio affichait toujours `Impossible de charger l'audio : Failed to fetch` alors que côté Network on voyait bien la requête au blob répondre **200 + 17.6 Mo téléchargés**. Test de vérif : "Ouvrir dans un nouvel onglet" sur l'URL SAS → Chrome **télécharge** le fichier au lieu de l'ouvrir avec le player audio natif.

**Cause** — les blobs uploadés via `azure_blob_service.upload_blob` n'avaient aucun `content_settings` explicite. Azure servait donc les MP3 avec un Content-Type par défaut (`application/octet-stream`) et sans Content-Disposition. Conséquence : Chrome traite la réponse comme un téléchargement, et WaveSurfer (`MediaElement` backend par défaut en v7) refuse de la consommer comme source audio → erreur générique `Failed to fetch` même si le fetch HTTP a réussi à 200.

**Fix en deux temps**

1. **Nouveaux uploads** — `_content_settings_for_blob(blob_path)` retourne le bon `ContentSettings` selon l'extension : `.mp3` → `audio/mpeg` + `inline`, `.json` → `application/json; charset=utf-8`, `.txt` → `text/plain`, `.pdf` → `application/pdf`. Appliqué dans `upload_blob` via `content_settings=...`.

2. **Blobs existants (rétroactif, sans re-upload)** — la route `/api/hr/cours-folders/<id>/audio-url/<filename>` ajoute `content_type` et `content_disposition` aux paramètres de `generate_blob_sas`. Ces deux options se traduisent en query string SAS `rsct` et `rscd` qui **override les headers du blob au moment du download**, sans toucher au blob lui-même. Donc les MP3 du job 5 déjà uploadés avec le mauvais Content-Type sont servis correctement dès la génération de la prochaine SAS URL.

**Bonus inclus** — garde-fou côté `create_platform_from_module` : refuse la création si `voice_type == "mock"` (module silencieux de test). Listing modules : `reusable: false` pour les modules mock. Évite le scénario où une plateforme partirait en prod avec uniquement du silence.

### fix: MP3 Edge TTS à 302:01 et waveform muette — retrait du padding silence incompatible

**Symptôme** — sur la plateforme, les `cours_*.mp3` du job 5 (TP DENKNDEED) affichaient une durée délirante de 302:01 au lieu de 45:00 / 60:00, et la forme d'onde restait plate (aucune voix audible) dans l'éditeur audio.

**Root cause** — le fix précédent `30ee86d` (avoid ffprobe for edge tts sync) avait introduit `_silent_mp3_approx_no_ffmpeg` qui répète `backend/assets/silence_1s.mp3` en bytes pour padder/préfixer la voix Edge TTS jusqu'à `target_sec`. Or les deux flux ont des paramètres MPEG incompatibles :

- Edge TTS : MPEG-2 Layer 3, **24 000 Hz**, mono, **48 kbps**
- silence_1s.mp3 : MPEG-2 Layer 3, **22 050 Hz**, mono, **8 kbps**

Concaténer ces frames hétérogènes en bytes crée un MP3 que les décodeurs (ffprobe, et surtout WaveSurfer côté navigateur) ne savent pas mesurer correctement — ils estiment la durée à partir du bitrate du premier header, donnant une valeur très éloignée de la réalité (`[mp3] Estimating duration from bitrate, this may be inaccurate`). Décodage hétérogène → waveform plate.

**Fix** — en mode `basic_tts` (Edge TTS), `_synthesize_course_audio_synced_to_slides` ne préfixe plus avec un silence d'amorce et ne padde plus jusqu'à `target_sec`. Les chunks Edge TTS sont concaténés via `concat_mp3_bytes` (nouveau, dans `basic_tts_service.py`) qui retire les ID3v2 et ID3v1 intermédiaires pour ne garder qu'un seul header. Conséquences :

- Le MP3 final est un flux MPEG-2 L3 24 kHz homogène, mesurable correctement par tous les lecteurs.
- La durée du fichier == durée parlée réelle (plus de cible 45 min remplie de silence).
- `fit_method` passe à `slide_sync_edge_no_padding` pour traçabilité.
- `concat_mp3_bytes` est aussi utilisé dans `convert_to_speech_basic` lui-même (textes longs splittés en plusieurs chunks Edge TTS) → un seul header ID3 à la fin au lieu d'un par chunk.

**À régénérer** — les MP3 du job 5 déjà uploadés dans `documentstts/audiostts` sont corrompus de manière permanente. Relancer la phase audio via "Reprendre depuis Audio" pour réécrire les blobs avec le nouveau code.

## 2026-05-06

### fix: route continue-after-text mal décorée + diagnostic stale + labels Edge TTS

**Backend — bug critique du décorateur Flask**

Le décorateur `@formation_bp.route(".../continue-after-text", methods=["POST"])`
était attaché à `_get_folder_info_for_resume` au lieu de
`continue_after_text`, parce que le helper avait été inséré entre le
décorateur et la fonction cible dans un commit précédent. Conséquence :
toute requête sur `/continue-after-text` exécutait le helper qui
retourne un `dict`, pas une `Response` Flask → **502 Bad Gateway** côté
client. Cause unique des 502 observés depuis ce matin sur les boutons
"Depuis : …". Décorateur déplacé juste avant `def continue_after_text`.

**Backend — labels "gTTS" → "Edge TTS"**

Cohérence avec la migration moteur faite plus tôt : les libellés visibles
utilisateur dans les logs et messages d'event passent de "gTTS" à
"Edge TTS" (mode_label, mode_suffix, message des events). Ajout d'un
champ `tts_engine: "edge-tts"` à côté du `voice_type: "gtts"` (clé DB
historique conservée) pour clarifier qui est l'identifiant et qui est
le moteur réel.

**Frontend — diagnostic stale au clic + labels**

Reset de `pipelineDiagnostic` (`setPipelineDiagnostic(null)`) au début
de `handleContinueAfterText` et `handleLaunchAudio` : sans ça, le
panneau "Diagnostic pipeline" continuait d'afficher les events du
précédent run jusqu'au prochain fetch. Avec ce reset, le panneau se
vide dès le clic puis affiche les nouveaux events au fur et à mesure.

Labels UI "gTTS" → "Edge TTS" (boutons "Edge TTS voix basique",
"Slides + Edge TTS", `voiceLabel('gtts')` retourne "Edge TTS — voix
basique gratuite").

### fix: state "Reprendre depuis…" coincé après crash TTS

Le useEffect qui libère `continuingAfterTextFolders[folder_id]` (et
réactive les boutons "Depuis : …") ne reset que quand
`reviewDone && audioClean`. Mais après un crash TTS, `dirty_segments=18`
reste, donc `audioClean=false`, et le state reste à `true` pour toujours
→ les boutons sont définitivement grisés sur ce job, l'utilisateur ne
peut plus relancer.

Ajout d'un 2ᵉ cas de reset : si `job.status === 'audio_error'`, on
libère aussi le state (le run est terminé en échec, on doit pouvoir
relancer). Le useEffect dépend désormais aussi de `job?.status`.

### feat: 4ᵉ étape "Slides" séparée de TTS dans Reprendre depuis…

Précédemment, "Depuis : TTS" englobait à la fois la régénération des
slides et la synthèse audio. Or les deux sont jointes par la persistance
du deck slides en DB (`script_slide_decks`) mais séparables : si le deck
existe, `generate_audio_from_script` le réutilise tel quel ; s'il manque
et `auto_generate_slides=True`, il est régénéré.

Le bouton "Reprendre depuis une étape" propose désormais 4 boutons :

- **Volume** : reset complet → volume → conformité + Word 2 → slides + TTS
- **Conformité** : conformité + Word 2 → slides + TTS
- **Slides** : supprime le deck existant → régénère les slides → TTS sync
- **TTS** : conserve les slides existantes → relance uniquement le TTS dessus

Backend : ajout de `_delete_slide_deck_for_resume(folder_id, content_job_id)`
qui purge `script_slide_decks` pour le folder, et insertion de la
condition `if from_step_idx <= 2` (≤ slides) avant le TTS pour décider de
supprimer ou non le deck. Logs `PIPELINE_RESUME_STEP_SLIDES_RESET` /
`SKIP` pour traçabilité.

### feat: TTS basique migré de gTTS vers edge-tts (Microsoft Edge, voix neurales)

**Pourquoi**

gTTS utilise l'API non officielle de Google Translate, qui se rate-limit
agressivement (~50k chars/h, soit ~12% du volume d'une journée pipeline).
Même avec retries 30s→60s→120s, Google reste bloqué et la pipeline crashe
en `429 Too Many Requests`. Voir l'incident audio job 7 du 06/05/2026.

**Solution**

Réécriture de `basic_tts_service.py` pour utiliser edge-tts (la même API
backend que Microsoft utilise dans le navigateur Edge pour la lecture
audio). Avantages :

- Sans clé API, gratuit, voix neurales fr-FR (DeniseNeural par défaut).
- Beaucoup plus tolérant que gTTS sur le volume.
- Qualité audio largement supérieure (voix neurales vs voix gTTS robotique).
- Configurable via `EDGE_TTS_VOICE` (Henri, Vivienne, Remy disponibles).

**Détails techniques**

- Edge-tts utilise asyncio + websockets en interne. Pour rester compatible
  avec eventlet+monkey_patch (Flask/SocketIO), la coroutine est encapsulée
  dans `eventlet.tpool.execute` qui isole l'event loop dans un vrai thread.
- Signature de `convert_to_speech_basic` strictement identique : aucun
  caller n'a besoin d'être modifié.
- Speed converti en rate edge-tts natif (`speed=1.28` → `rate="+28%"`),
  pydub speedup retiré (plus nécessaire, edge-tts gère nativement).
- Défaut `BASIC_TTS_SPEED=1.0` (voix neurales déjà naturelles, vs 1.28
  pour gTTS qui était lent).
- `requirements.txt` : `gTTS>=2.5.0` → `edge-tts>=7.2.0`.

**Impact**

- Identifiants stables (`tts_mode="gtts"`, colonne `voice_type="gtts"`)
  conservés tels quels — ce sont des clés d'API et de DB historiques pour
  "TTS basique gratuit", l'implémentation derrière a juste changé.
- Labels visibles utilisateur dans les events pipeline mis à jour
  ("BASIC gTTS" → "BASIC edge-tts").

### fix: reprise pipeline — accept 200/202, reset status stale, logs détaillés

**Frontend (`FormationPipeline.jsx`)**

`handleContinueAfterText` accepte désormais tout `2xx` (`resp.ok`)
au lieu de strictement 202. Corrige l'affichage "Reprise aval :
Erreur 200" qu'on observait quand un proxy Azure normalise le code
HTTP de réponse. Le check sur `data.error` reste pour intercepter
les vraies erreurs métier renvoyées en 200.

**Backend (`formation_routes.py`) — reset agressif et logs détaillés**

`continue_after_text` libère désormais le verrou `_EXECUTION_STATE`
si l'état précédent dit "running" mais qu'il n'y a probablement
plus de greenlet actif (typique après crash + redémarrage gunicorn).
L'utilisateur a explicitement demandé une nouvelle relance, donc
on lui rend la main.

Reset agressif du status job DB : si `audio_running`, `audio_error`
ou `audio_completed`, on remet à `tts_launched` avant de spawn le
nouveau greenlet. Ça évite que l'UI continue d'afficher la
progression d'un précédent run crashé.

Logs structurés `PIPELINE_RESUME_*` à chaque étape (REQUEST,
SPAWN, RUN_START, STEP_RESET_*, STEP_VOLUME_*, STEP_REVIEW_*,
STEP_TTS_*, RUN_DONE, RUN_FAILED). Chaque log porte
`formation_job_id`, `folder_id`, `from_step`, durée et compteurs
métier (segments_reviewed, patches_applied, total_words). Les SKIP
sont aussi loggés explicitement quand `from_step` saute une étape.

### feat: reprise pipeline depuis n'importe quelle étape + retry gTTS plus tolérant

**Backend — `continue_after_text` accepte `from_step` (`formation_routes.py`)**

L'endpoint `/api/formation/<job>/content/<folder>/continue-after-text`
accepte désormais un paramètre `from_step` (`"volume"` par défaut,
`"review"`, ou `"tts"`) qui permet de reprendre la pipeline aval
depuis l'étape choisie en sautant celles qui précèdent. La suite
s'enchaîne automatiquement jusqu'au TTS+slides synchronisé. Nouveau
helper `_get_folder_info_for_resume` qui lit `platform_id` et
`content_job_id` sans déclencher le reset de l'état aval (utile
quand on saute la phase reset+volume).

**Frontend — section déroulable "Reprendre depuis une étape" (`FormationPipeline.jsx`)**

Sortie du bouton "Continuer après le texte" et du sélecteur de
modèle de la zone TEXTE GÉNÉRÉ. Remplacés par un encart déroulable
juste en dessous, avec 3 boutons : `Depuis : Volume`, `Depuis :
Conformité`, `Depuis : TTS`. Chacun appelle `handleContinueAfterText`
avec le `from_step` correspondant. La zone TEXTE GÉNÉRÉ reste pour
les actions de consultation (Voir, Slides, Word, Word 2, Rapport).

**Backend — retry gTTS pipeline plus tolérant (`content_generation_service.py`)**

Défauts de `_basic_tts_pipeline_retry_kwargs` passés de
`max_retries=1`/`base_wait=20s` à `max_retries=3`/`base_wait=30s`.
Backoff exponentiel : 30s → 60s → 120s (max ~3.5 min d'attente par
chunk avant abandon). Évite les crashs `429 Too Many Requests` quand
Google met plus de 20s à lever le rate limit sur du volume (7 blocs
× 4 chunks par journée). Toujours configurable via
`BASIC_TTS_PIPELINE_MAX_429_RETRIES` et
`BASIC_TTS_PIPELINE_429_BASE_WAIT_SEC`.

### feat: traçabilité pipeline avec IDs explicites (formation_job_id / content_job_id / folder_id)

Refonte de la traçabilité pour rendre les logs Azure et l'UI
diagnostic exploitables sans avoir à deviner à quel niveau
hiérarchique appartient un `job=X`.

**Logs structurés (`content_generation_service.py`)**

Tous les préfixes `PIPELINE_CONTENT_*`, `PIPELINE_AUDIO_*`,
`PIPELINE_REVIEW_*` portent désormais
`formation_job_id=… content_job_id=… folder_id=…` au lieu d'un
unique `job=…` ambigu (qui pouvait référencer le job formation OU
le job content_generation selon le contexte).

`get_job_from_db` (lecture du job content_generation depuis le
folder) joint désormais `cours_folders` pour exposer
`formation_job_id` et `folder_name` directement, évitant aux
appelants de devoir refaire la jointure.

**Labels API (`formation_pipeline_service.py`)**

`get_job` et `list_jobs` exposent désormais `job_label` (`Job #X`)
et `platform_label` (`PX`) prêts à afficher.

**Routes (`formation_routes.py`)**

`list_content` et `formation_pipeline_diagnostic` renvoient
`folder_label` (`FX`), `platform_id`, `formation_job_id`,
`content_job_id` pour chaque dossier — finie l'ambiguïté entre
les deux niveaux d'IDs.

**UI (`FormationPipeline.jsx`)**

Helpers `formatJobIdentity(job)` et `formatFolderIdentity(folder)`
qui standardisent l'affichage `Job #X · PY · TPname` et
`FX · Texte #Y · Nom`. Détection visuelle des folders qui
n'appartiennent **pas** au job sélectionné (`belongsToSelectedJob`)
avec bandeau rouge — complète la réparation des orphelins côté
backend par une alerte côté UI.

### fix: résolution robuste du folder dans `continue_after_text` (formation_routes.py)

La route `continue_after_text` retombait en erreur quand le folder
demandé était orphelin (`cours_folders.formation_job_id IS NULL`) ou
mal rattaché — typiquement après un crash/reprise de pipeline ou une
réparation incomplète.

Quatre helpers ajoutés :

- `_completed_text_folder_candidates(job_id)` : folders rattachés au
  job qui ont vraiment un texte `completed` (jointure
  `content_generation_jobs` + comptage `content_generation_segments`).
- `_requested_text_folder_state(job_id, folder_id)` : état texte d'un
  folder précis, même non-completed et même si `formation_job_id` est
  NULL.
- `_claim_single_completed_orphan_folder(job_id, requested)` : rattache
  un unique folder completed orphelin du même `platform_id` quand le
  lien historique est cassé. Pose `formation_job_id` via UPDATE atomique
  (clause `WHERE id=? AND formation_job_id IS NULL`) pour éviter le vol
  de folder.
- `_resolve_continue_after_text_folder(job_id, requested_folder_id)` :
  orchestrateur — tente la résolution directe, déclenche
  `repair_orphan_content_folders(job_id)` du service en filet de
  sécurité, puis fallback sur le claim d'orphelin si nécessaire.

Trace structurée `PIPELINE_FOLDER_REPAIR` émise quand un orphelin est
réparé, pour audit dans les logs Azure.

### feat: liste des jobs enrichie + deep-link `?job=` (FormationPipeline.jsx)

`JobCard` montre désormais des pills **Job #X** et **PX** (platform_id),
le nom de la plateforme bien plus visible, et la date de création
formatée en heure Paris (`formatJobTimestamp`).

Helper `setPipelineJobInUrl(jobId)` qui synchronise le job sélectionné
dans `?job=…` via `pushState` / `replaceState`. Au chargement, un
`useEffect` lit `?job=` et restaure la sélection si l'ID correspond à
un job présent. Permet de bookmarker / partager l'URL d'un pipeline
précis et de revenir dessus après reload.

## 2026-05-05

### chore: marqueur `LOGGING_BOOT v2` dans `configure_logging()`

Ajout d'un log `WARNING` au démarrage qui imprime le niveau root effectif
+ le niveau effectif de chaque logger SDK museli. Permet de vérifier
visuellement dans les logs Azure App Service que la version corrigée
de `configure_logging()` est bien chargée par le worker.

### fix: logs Azure noyés par le SDK — root logger DEBUG → INFO + SDK museli

`utils/logger.py` configurait `logging.basicConfig(level=DEBUG)`, ce qui
allumait *tous* les loggers du système. Conséquence : les SDK Azure
(`azure.core.pipeline.policies.http_logging_policy`,
`urllib3.connectionpool`, etc.) déballaient chaque requête HTTP avec
headers + corps — ~30 lignes par lecture de container Blob. Les logs
métier `PIPELINE_*` ajoutés dans le commit précédent étaient donc
illisibles dans Azure App Service.

Fix :

- Root logger en `INFO` par défaut, override possible via `LOG_LEVEL`
  (env var App Service) pour debug ponctuel.
- Liste explicite de 11 loggers tiers verbeux (`azure*`, `urllib3*`,
  `msrest`, `msal`, `openai`, `httpx`) forcés à `WARNING` après
  `basicConfig` — ils ne parlent plus que sur erreur réelle.
- `force=True` sur `basicConfig` pour re-configurer même si un import
  l'a déjà appelé.

### feat: observabilité Azure + retries gTTS bornés + relances review propres

Trois axes pour rendre la pipeline débloquable et diagnostiquable depuis les
logs Azure App Service.

**Observabilité (`formation_observability_service.py`,
`content_generation_service.py`)**

- Helpers `_compact_for_log` + `_emit_pipeline_event_log` : chaque
  `log_pipeline_event` est désormais aussi écrit en JSON compact dans
  stdout (préfixe `PIPELINE_EVENT`), niveau ajusté (`error`/`warning`/`info`)
  selon le statut. Les rapports persistés sortent un `PIPELINE_REVIEW_REPORT`.
- Logs structurés ajoutés autour des étapes de génération de texte :
  `PIPELINE_CONTENT_SUBPART_START`, `PIPELINE_CONTENT_SEGMENT_START/DONE/SKIP`,
  `PIPELINE_REVIEW_SEGMENT_START`. Permet de retrouver un blocage dans
  `az webapp log tail` sans avoir à lire la DB.

**Retries gTTS bornés (`content_generation_service.py`,
`script_slide_generation_service.py`)**

- Helper `_basic_tts_pipeline_retry_kwargs()` qui force pour la pipeline :
  `BASIC_TTS_PIPELINE_MAX_429_RETRIES=1` et
  `BASIC_TTS_PIPELINE_429_BASE_WAIT_SEC=20`. Pire cas : 20 s d'attente sur
  un 429 Google au lieu des ~31 min précédents (60+120+240+480+960 s).
- `progress_callback` propagé jusqu'à `convert_to_speech_basic` dans tous
  les chemins (slides synchronisées + bloc cours + pauses), pour que le
  diagnostic affiche les sub-events ("gTTS chunk 3/5 — 429 Google,
  attente 20s") au lieu de rester figé sur "génération pause contextuel".
- En mode test gTTS, les pauses/Q&A passent en `_fallback("mode test gTTS")`
  → audio recyclé/silence au lieu d'un appel LLM + TTS coûteux.

**Relances review propres (`formation_routes.py`,
`claude_code_mission_service.py`)**

- `_delete_active_review_artifacts(job_id, position)` purge les rapports
  actifs d'une journée avant relance aval (les archives `_done` sont
  conservées mais filtrées par cutoff côté lecture).
- Helpers `_parse_report_timestamp` / `_report_is_after_cutoff` /
  `_db_review_report_is_complete` /
  `_latest_continue_after_text_started_at` : la route de lecture filtre
  les rapports antérieurs au dernier `continue_after_text_started`,
  évitant d'afficher un rapport périmé après une relance.

### feat: refonte du panneau diagnostic pipeline (FormationPipeline.jsx)

`PipelineDiagnosticPanel` enrichi pour rendre le suivi de la synthèse audio plus
lisible :

- Carte "En cours maintenant" — dernier événement audio + barre de progression
  playlist TTS (step/total parsé depuis `audio_progress`).
- Carte "Audio prêt" — ratio segments propres / total avec barre verte.
- Filtres événements (Audio / Review / Tout) — par défaut sur Audio, jusqu'à
  18 événements affichés (au lieu de 8).
- Audit santé : entrées (`segments_completed`, `audio_tts_files`,
  `pre_review_snapshotted`, `module_persistant`, etc.) traduites en libellés FR
  via `healthCheckLabel`.
- Helper `eventData(event)` qui parse `data` ou `data_json` (string ou objet).
- Renommage `audio dirty` → `audio à générer` dans le bandeau totaux.

### fix: `_build_course_blocs_from_segments` ne propageait pas `llm_model` → appel Anthropic résiduel

Dans `generate_audio_from_script()`, l'appel à `_build_course_blocs_from_segments` n'incluait pas le
paramètre `model=llm_model`. Conséquence : si le bloc 7 d'un cours dépassait son budget TTS (cas
"dernier dossier"), `_reduce_last_bloc_to_budget` recevait `model=None` et tombait sur
`default_model()` → appel Anthropic malgré le modèle affiché "deepseek-v4-pro" dans les events.

Fix chirurgical : ajout de `model=llm_model` dans l'appel à `_build_course_blocs_from_segments`
(`content_generation_service.py` ligne ~1975).



### fix: timestamps diagnostic en heure Paris (était UTC)

`formatEventTime` dans `FormationPipeline.jsx` parsait les `created_at` SQLite
sans timezone, ce qui faisait que JS les interprétait comme heure locale alors
que la DB stocke en UTC (`CURRENT_TIMESTAMP`). Résultat : un événement qui
arrivait à 13:01 Paris s'affichait "11:01" dans le diagnostic.

Désormais, `formatEventTime` ajoute explicitement `Z` à la string SQL pour
forcer le parsing UTC, puis appelle `toLocaleTimeString('fr-FR', { timeZone:
'Europe/Paris' })`. Affichage cohérent avec l'heure de l'utilisateur.

### feat: dropdown modèle LLM sur "Continuer après le texte" + persistance

Le bouton **Continuer après le texte** est maintenant accompagné d'un
`<select>` qui permet de choisir explicitement le modèle LLM pour la relance
aval (DeepSeek Pro / DeepSeek Flash / Sonnet / Haiku). Initialisé depuis
`job.auto_pilot_model` si présent, sinon **DeepSeek Pro** par défaut.

Le choix est :
- envoyé dans le payload de `POST /api/formation/<job_id>/content/<folder_id>/continue-after-text`
- **persisté** côté backend dans `auto_pilot_model` (via `update_job`), pour que
  les futurs clics ou redémarrages auto-pilot retrouvent le bon provider
  sans qu'il faille le repasser explicitement

Conséquence : un job historique sans `auto_pilot_model` (NULL en DB) peut être
forcé en DeepSeek depuis l'UI sans toucher aux variables d'environnement Azure.

### feat: nouveau template slide `Framework` (modèle conceptuel circulaire)

Inspiré du pattern "5 forces de Porter" : anneau coloré segmenté + cœur central
texte + N satellites (4 ou 6) avec titre + description courte. Pensé pour les
modèles conceptuels denses (frameworks stratégie, piliers d'une démarche, leviers).

- `frontend/src/components/slides/templates/FrameworkTemplate.jsx` : SVG ring
  segmenté (palette pastel orange/turquoise/sarcelle/vert/jaune/corail), cœur
  blanc avec titre central, satellites positionnés par calcul d'angle.
- Placement elliptique adaptatif (`distanceX` ≠ `distanceY`, factors par zone) :
  satellites latéraux ancrés gauche/droite du cercle ; satellites verticaux
  ancrés au-dessus / en-dessous de leur arc, alignés vers le bord extérieur de
  la slide (text-align gauche pour côté gauche, droite pour côté droit).
- 2 exemples ajoutés à `TestSlides.jsx` : *Les 4 forces de Porter* (4 satellites
  + cœur) et *Les 6 leviers de la performance* (6 satellites + cœur).
- Style cohérent avec les autres templates : fond crème `#FFF9E6`, header badge
  rouge + brandName, Fredoka pour les titres / Poppins pour le corps.

Visible sur `/test-slides` (route publique).

### fix: provider LLM — fallback robuste quand `auto_pilot_model` est null + traçabilité events audio

Suite du fix précédent : un job historique sans `auto_pilot_model` persisté
(NULL en DB) faisait retomber `_resolve_pipeline_api_model(job)` sur `None`,
ce qui propageait `llm_model=None` jusqu'aux services de transition qui
finissaient par appeler `default_model()` → fallback Anthropic dès qu'une
clé `ANTHROPIC_API_KEY` était configurée. Les jobs DeepSeek historiques
plantaient donc encore sur "credit balance too low".

`_resolve_pipeline_api_model` chaîne désormais 4 fallbacks :
1. modèle explicite passé en argument
2. `auto_pilot_model` du job
3. env var `FORMATION_LLM_PROVIDER` ou `LLM_PROVIDER` (`deepseek` →
   `deepseek-v4-pro`, `anthropic` → `sonnet`)
4. `DEEPSEEK_API_KEY` présente sans `ANTHROPIC_API_KEY` → `deepseek-v4-pro`

Et tous les `log_pipeline_event` de la phase audio (`audio_folder_started`,
`audio_folder_completed`, `audio_folder_failed`, `step_failed`) reçoivent
maintenant `model=_resolve_pipeline_api_model(job)` — visible directement
dans la modale de détail (champ "Modèle LLM"), pour vérifier en un coup
d'œil quel provider a été utilisé.

### fix: cohérence provider LLM — transitions/closings respectent le modèle du job

Quand la pipeline était lancée avec DeepSeek (`auto_pilot_model="deepseek-v4-pro"`),
les services de transition (`break_transition_service`, `closing_transition_service`)
et de closing de bloc cours appelaient quand même `default_model()` au runtime,
qui retombait sur Claude/Anthropic dès qu'`ANTHROPIC_API_KEY` était définie.
Résultat : la phase audio plantait sur `invalid_request_error: credit balance
too low` côté Anthropic alors que le job tournait sur DeepSeek.

Désormais :
- `generate_audio_from_script(folder_id, …, llm_model=...)` accepte un paramètre
  explicite (`backend/services/content_generation_service.py`).
- `_apply_closing_transitions(blocs, api_speed, model=...)` et
  `_build_contextual_break_audio(..., llm_model=...)` propagent ce modèle aux
  services de transition.
- Les 3 call sites de `generate_audio_from_script` dans `formation_routes.py`
  (`launch_audio`, `continue_after_text`, étape audio auto-pilot) passent
  désormais `llm_model=_resolve_pipeline_api_model(job)` qui lit
  `auto_pilot_model` de la DB.

Conséquence : un job lancé en DeepSeek reste 100 % DeepSeek pour toutes les
étapes (texte, review, transitions, closings). Idem Anthropic pour un job
Anthropic.

### feat: modale détails par événement dans le diagnostic pipeline

Click sur n'importe quelle ligne du panneau **Diagnostic pipeline** (zone
*derniers événements*) → ouvre une modale qui affiche tous les champs
structurés : étape, dossier, modèle LLM utilisé, durée, type d'événement, ID,
message complet, erreur (avec stacktrace si présente), données JSON
(`data_json`) formatées.

Utile pour comprendre précisément un échec (ex. erreur API providers, segments
en revue partielle) sans avoir à fouiller la DB ou les logs Azure.

Fichier : `frontend/src/pages/FormationPipeline.jsx` (composants
`PipelineDiagnosticPanel` + nouveau `EventDetailModal`).

### fix: ordre chronologique des événements dans le diagnostic

`recentEvents = events.slice(-8).reverse()` retournait les 8 plus *anciens*
événements (le backend les renvoie déjà en ordre ASC), puis les inversait,
donnant un affichage non-chronologique. Désormais `events.slice(-8)` simplement
— les 8 plus récents en ordre ASC (du plus ancien en haut au plus récent en
bas), avec tie-breaker sur `id ASC` pour les événements à timestamp identique.

### feat: observabilité durable de la pipeline (rapports + événements)

Les rapports de conformité ne pouvaient plus être lus en prod Azure (filesystem
local non fiable, le modal *Rapport de révision conformité* affichait
*"Aucun rapport trouvé"* malgré une review effectuée). On bascule l'observabilité
en DB, accessible via API.

**Nouvelles tables** (`backend/database/db.py`) :
- `content_review_reports` : snapshot durable par exécution de review (job_id,
  folder_id, source, summary_json, report_json, created_at) + index
  `(job_id, folder_id, created_at)`.
- `formation_pipeline_events` : journal append-only des transitions importantes
  de pipeline (job_id, folder_id, step, event_type, status, message, model,
  duration_ms, data_json, error) + index sur `(job_id, created_at)`. Pensé pour
  alimenter un futur dashboard qualité.
- Colonne `text_content_pre_review` sur `content_generation_segments` : conserve
  le texte avant review pour pouvoir diff/restaurer.

**Nouveau service** (`backend/services/formation_observability_service.py`) :
helpers d'écriture/lecture pour les deux tables, avec `ensure_observability_tables()`
en cas de redémarrage tardif.

**Nouveaux endpoints** (`backend/routes/formation_routes.py`) :
- `GET /api/formation/<job_id>/events` — journal d'événements du pipeline
- `GET /api/formation/<job_id>/diagnostic` — diagnostic complet du job

**Helpers ajoutés** : `_build_db_review_report` (résout le bug "Aucun rapport
trouvé"), `_write_api_review_report`, `_reset_folder_downstream_to_generated_text`,
`_next_folder_in_formation`, `_make_audio_progress_logger`, `continue_after_text`
(continue la pipeline après validation manuelle du texte).

### fix: health service — folders d'un job filtrés par `formation_job_id`

`compute_health(job_id)` joignait `cours_folders` sur `platform_id`, ce qui
agrégeait à tort *tous* les folders de la plateforme (potentiellement plusieurs
formations en parallèle). Désormais filtré sur `cf.formation_job_id = ?`.

Fichier : `backend/services/formation_health_service.py`.

### feat: gTTS — speedup post-traitement configurable

`convert_to_speech_basic` accepte maintenant un paramètre `speed` (par défaut
lu depuis `BASIC_TTS_SPEED`, défaut **1.28**). Le MP3 gTTS est passé dans
`pydub.effects.speedup` après concat des chunks pour se rapprocher d'un débit
*cours* (gTTS étant lent par défaut). Fallback silencieux si pydub indisponible.

Fichier : `backend/services/basic_tts_service.py`.

## 2026-05-04

### feat: slides PPT générées depuis le script (sans audio) + protection admin

Nouveau pipeline de génération de slides qui part directement du **texte final
stocké en DB** (résultat de la pipeline formation), sans avoir besoin d'un MP3
préexistant ni de transcription Whisper.

**Backend** :
- Nouveau service `script_slide_generation_service.py` : produit un deck de
  slides à partir du `final_text` d'un folder, avec contrôle de densité
  (`max_slides`, `pace=dense|normal|synthesis`) et stats/timeline cohérentes
  avec le format attendu par le front.
- Nouvelle route `POST /api/slides/generate-from-script` (admin only via
  `session["is_admin"]`) — body `{folder_id, job_id?, max_slides, pace, model?}`.
- `GET /api/slides/data?folder_id=…` peut désormais récupérer le dernier deck
  généré pour un folder donné (admin only).
- Le mode de génération courant (`audio_legacy` / `audio_v3` / `script`) est
  exposé via `generation_mode` dans la réponse JSON.

**Frontend** :
- `frontend/src/App.jsx` : `/generated-slides` est désormais une route protégée
  admin (`ProtectedAdminRoute`).
- `GeneratedSlides.jsx` et `TestSlides.jsx` retravaillés pour consommer le
  nouveau endpoint, afficher le mode de génération et permettre de lancer la
  génération depuis le script.

Fichiers : `backend/routes/slides_routes.py`,
`backend/services/script_slide_generation_service.py`,
`frontend/src/App.jsx`, `frontend/src/pages/GeneratedSlides.jsx`,
`frontend/src/pages/TestSlides.jsx`.

### fix: auto-pilot watchdog pour locks zombies

L'auto-pilot ne dépend plus seulement du boot recovery ponctuel. Un watchdog
périodique démarre avec le backend et vérifie toutes les 60 secondes les jobs
auto-pilot activés, non terminés, sans erreur enregistrée, avec lock absent ou
périmé.

**Impact** :
- Si un worker meurt pendant une étape longue (KB, content, audio), le lock devient
  périmé après le TTL existant de 5 minutes.
- Le watchdog relance alors `_tick_auto_pilot(job_id)` sans attendre un redémarrage
  complet du backend.
- Les jobs avec `auto_pilot_error` restent volontairement exclus pour éviter une
  boucle infinie de retries sur une vraie erreur applicative.

Fichiers : `backend/routes/formation_routes.py`,
`backend/services/formation_pipeline_service.py`, `backend/main_app.py`.

### feat: transitions Q&A/pauses contextuelles par dossier

Les fichiers Q&A et pauses ne sont plus forcément de simples MP3 statiques
recyclés : la pipeline peut générer une intro/outro contextuelle à partir du
bloc cours précédent et du prochain bloc cours.

**Mécanique** :
- Nouveau service `break_transition_service.py` : génération JSON `{intro, outro}`
  pour `qa`, `pause` et `pause_midi`, avec fallback statique si le LLM échoue.
- Les Q&A annoncent le temps de questions dans le chat, puis l'outro raccorde vers
  la suite du programme.
- Les pauses courtes annoncent uniquement la pause en intro ; l'outro dit que la
  pause est terminée et réouvre vers le prochain cours.
- La pause déjeuner reste sobre : son intro ne reçoit pas le contexte du matin et
  ne résume pas le bloc précédent.
- Les fichiers sensibles au changement d'ordre été/hiver restent neutres en outro :
  `pause_12h10_12h20.mp3`, `qa_13h05_13h15.mp3` et
  `pause_midi_13h15_14h45.mp3` n'annoncent pas l'élément suivant.
- Les durées sont transmises au service ; seules les durées fiables sont dites à
  l'oral (`cinq minutes`, `dix minutes`, `quinze minutes`, etc.). Pour une durée
  atypique non reconnue, le prompt interdit de mentionner une durée précise.

**Câblage** :
- Chemin actif `/formation-pipeline` : `generate_audio_from_script()` génère la
  playlist complète dans `audiostts/platform-{platform_id}/folder-{folder_id}/playlist/`,
  en respectant la playlist effective de la plateforme (`hiver`/`ete`).
- Chemin legacy `generate_playlist_for_folder()` : même génération contextuelle,
  avec fallback `audioqapause` en cas d'échec.
- Le wiring des transitions est factorisé dans `break_transition_service.py` via
  `build_break_transition_texts()` : les deux chemins audio injectent seulement
  leur façon de lire le texte d'un bloc.
- `fill_from_folder` copie d'abord les MP3 contextualisés du dossier, puis retombe
  sur `audioqapause` uniquement pour les fichiers manquants.
- `closing_transition_service.py` clôt maintenant les blocs cours sans annoncer
  directement `questions`, `pause` ou `chat`, pour laisser cette fonction au
  fichier Q&A/pause suivant. Les ouvertures pédagogiques ne supposent pas que le
  prochain fichier lu est forcément le prochain cours.

Détails : `memoire/04-solutions/break-transitions-contextuelles.md`.

## 2026-04-30

### feat: carryover bloc 7 → folder suivant (+ rebalancing LLM du dernier jour)

Quand un bloc 7 dépasse son budget TTS malgré le cap, on ne le tronque pas et on
ne fait pas planter la pipeline : **on reporte les paragraphes en débord vers le
folder suivant**.

**Mécanique** :
- Stockage dans `content_generation_jobs.carryover_out_text` (source) +
  `carryover_in_text` (cible). Migration de colonnes ajoutée à `db.py`.
- `_handle_last_bloc_overflow` détecte le débord et choisit la fin de paragraphe
  (ou phrase fallback) la plus tardive sous le cap pour tronquer proprement.
- `_format_carryover_for_next_course()` préfixe une intro fixe au prochain cours :
  *"Avant d'entrer dans la suite de ce cours, on reprend le point que nous
  n'avons pas terminé **au cours dernier**…"*
- Jamais le mot "hier" — l'intro reste valable même si la formation tient sur
  des jours non-consécutifs.

**Cas du dernier folder (pas de J+1)** : `_reduce_last_bloc_to_budget(bloc, model)`
appelle un LLM pour **remanier** le texte du dernier bloc à ~90 % du budget :
condense, fusionne les exemples redondants, garde toutes les notions, **n'ajoute
aucune nouvelle idée**, termine par une vraie conclusion de cours. Refus avec
ValueError si le résultat dépasse encore.

**Hiérarchie de fallback finalisée** :
1. Cap budget cascade (forward) — bloc 1..6 ne déborde pas.
2. Backward redistribution — bloc 1..6 sous-rempli aspire des paragraphes du suivant.
3. **Carryover bloc 7 vers J+1** — déterministe, paragraphes verbatim.
4. **Rebalancing LLM dernier jour** — si pas de J+1.
5. Closing contextuel — fill du gap résiduel sur tous les blocs dirty.

Détails : `memoire/04-solutions/carryover-jour-a-jour-bloc-7.md`.

### feat: blocs cours — redistribution backward + closing contextuel adaptatif

Suite logique du cap budget : quand un bloc finit avec un gap audio important, on
agit en deux temps avant le TTS plutôt que de laisser du silence ou tronquer.

**Passe 2 — Redistribution backward (déterministe, gratuite).**
`_redistribute_undershoot_backward` dans `content_generation_service.py` : si un bloc
N a un gap > 30 s, on tire des **paragraphes complets** du bloc N+1 vers le bloc N
tant que ça rentre dans son budget mots. Préserve l'intégrité des unités d'idée
(jamais de paragraphe coupé), zéro appel LLM. Marque les blocs touchés `dirty=1`
(audio à régénérer).

**Passe 3 — Closing contextuel (LLM ou template selon gap).**
Nouveau service `closing_transition_service.py`. Pour le gap résiduel après passe 2 :

| Gap résiduel    | Registre                  | Cible mots | Source       |
|-----------------|---------------------------|------------|--------------|
| < 15 s          | Aucun (silence padding)   | 0          | —            |
| 15–45 s         | Phrase de clôture courte  | 30–100     | Template     |
| 45–120 s        | Transition pédagogique    | 130–360    | LLM Sonnet   |
| 120–300 s       | Recap + respiration       | 360–700    | LLM Sonnet   |
| Bloc 7 (final)  | Conclusion de journée     | selon gap  | LLM Sonnet   |

Cap absolu : `MAX_CLOSING_WORDS = 700` (≈ 4 min audio). Au-delà, le résidu reste
silence — un gap > 5 min signale un volume_safety insuffisant, pas un closing à
rallonge.

Le closing est concaténé au texte du bloc avant le seul appel Fish Audio. Distinct
des pauses dynamiques (qui auraient enrichi le fichier de pause) : ici on enrichit le
fichier cours, donc 1 TTS par bloc, pas de cache cross-fichier.

Garde prod ajoutée : le closing est plafonné au **budget mots restant** du bloc.
Si le bloc est déjà au budget prudent TTS, aucun closing n'est ajouté, ce qui évite
un échec du pré-check juste avant Fish Audio.

Désactivé en mock et en `basic_tts` (gTTS a une calibration différente). Si le LLM
échoue, fallback statique par taille de gap.

Détails : `memoire/04-solutions/closing-bloc-cours-contextuel.md`.

### fix: découpage TTS — cap budget par bloc, cascade des paragraphes en surplus

**Problème** : `_choose_natural_boundary` cherchait la fin de paragraphe la plus proche de la cible mots, fenêtre symétrique (cible ± 700 mots). Si la fin de paragraphe la plus proche tombait à `cible + 700`, le bloc finissait au-dessus du budget TTS et le pré-check `_synthesize_course_audio_to_fit` le rejetait — pipeline auto-pilot stoppée.

**Solution déterministe (zéro appel LLM réactif)** : chaque bloc reçoit un hard cap mots calé sur `_estimated_words_budget_for_course(target_sec, api_speed)`. `_choose_natural_boundary` filtre désormais les candidats à `b ≤ cap_w` — jamais au-dessus. Les paragraphes en surplus tombent automatiquement dans le bloc suivant, qui refait le calcul avec son propre budget. Effet cascade naturel : bloc 1 sous-rempli → bloc 2 hérite → … → bloc 7 absorbe le reste.

**Pourquoi pas un raccourcissement LLM ?** — Cette approche aurait coûté un appel API par bloc en débord, risqué de couper une notion clé jugée à tort secondaire, et introduit de la non-reproductibilité. Le décalage paragraphe est gratuit, déterministe, et préserve verbatim les unités d'idée pédagogiques.

**Bloc 7** : seul à ne pas avoir de cap (il absorbe le reste). S'il dépasse son budget, c'est que `total_words > total_budget` ; ressort de `volume_safety` en amont, pas du découpage.

Fichiers : `backend/services/content_generation_service.py` — `_choose_natural_boundary` (paramètre `word_budget_max`), `_build_course_blocs_from_segments` (calcul du budget par bloc, log enrichi).

### fix: TTS auto-pilot — plus de coupure brute en pleine phrase

- Le découpage des 7 fichiers cours privilégie désormais une fin de paragraphe proche de la cible de durée (unité d'idée), puis seulement une fin de phrase en fallback. Les doubles sauts de ligne sont conservés dans le texte envoyé au TTS.
- Le TTS Fish Audio n'est appelé qu'une seule fois par bloc (`FORMATION_TTS_SPEED`, défaut `0.90`) ; le speedup local est désactivé par défaut (`FORMATION_TTS_LOCAL_MAX_SPEEDUP=1.0`) pour éviter une voix trop rapide/aiguë.
- Pré-check avant appel Fish Audio : si le bloc dépasse le budget de mots prudent du créneau (`FORMATION_TTS_PREFLIGHT_SAFETY`, défaut `0.96`), aucun appel payant n'est lancé et l'étape échoue proprement.
- Les prompts from-scratch passent de ~5 000 à ~3 300 mots par passe (~60k mots/jour) pour générer plus court en amont, avec une voix plus posée.

### feat: révision conformité en 5 salves ciblées (anti-dilution attention)

**Problème** : envoyer les 27 règles en 1 seul appel API provoque de la dilution d'attention — le LLM (Claude ou DeepSeek) en oublie systématiquement. Les règles #9, #10, #14 notamment n'étaient jamais vérifiées.

**Solution** : `run_content_review` dans `content_generation_service.py` fait désormais **5 appels API séquentiels par segment** (1 par groupe thématique) au lieu d'1 :

| Groupe | Règles | Thème |
|---|---|---|
| Éthique culturelle | #1, #2, #3, #9, #14 | Spirituel, alcool/musique, humour, respect des tiers |
| Éthique commerciale | #4, #5, #6, #7, #8 | Manipulation, closing, flirt, chance, célébrités |
| Légal et intégrité | #10, #11, #12, #13, #15, #16 | Cohérence, discrimination, RGPD, promesses irréalistes |
| Anti-hallucination | #17, #18, #19, #20 | Exemples fictifs, chiffres non sourcés, prudence |
| Style oral TTS | #21–#27 | Fusion syntaxique, guillemets, posture, oral |

- `_REVIEW_RULE_GROUPS` : constante partagée (même 5 groupes dans `claude_code_mission_service.py`)
- `_extract_rules_for_group(full_rules_text, rule_numbers)` : extrait les règles demandées par split regex
- `_build_review_prompt_focused(...)` : prompt focalisé avec scope exclusif annoncé clairement
- Les patches s'accumulent sur `current_text` (chaque salve patch le résultat de la précédente)
- `reviewed=1` uniquement si les 5 salves réussissent — une salve en erreur = `review_error`, PAS de `reviewed=1`

### feat: review API stricte — chunking texte + concurrence bornée

- Chaque salve découpe désormais le segment en chunks paragraph-aware (`FORMATION_REVIEW_CHUNK_WORDS`, défaut 1500 mots) pour éviter la dilution d'attention sur les segments de ~5000 mots.
- Les chunks d'une même salve sont traités en parallèle avec concurrence bornée (`FORMATION_REVIEW_CHUNK_CONCURRENCY`, défaut 2), pas en rafale complète — compatible avec la limite de concurrence dynamique DeepSeek.
- Les salves restent séquentielles : les patches de la salve N sont appliqués avant la salve N+1.
- Les retries par chunk respectent `wait_seconds` sur rate limit 429 et ne retentent pas les erreurs déterministes 400/401/403.


### fix: auto-pilot — content API : NameError j→job + génération synchrone sans thread

- **NameError corrigé** : `_execute_ap_step` utilisait `j` (inexistant) au lieu du paramètre `job` dans la boucle content API.
- **Génération synchrone** : remplace `start_generation_job` (thread background) + `_wait_folder_content_completed` (attend un thread potentiellement mort) par `run_content_generation(folder_id)` direct dans le greenlet auto-pilot. Résistant aux restarts : `run_content_generation` lit le `done_set` des segments complétés et reprend exactement où ça s'est arrêté.
- `_wait_folder_content_completed` supprimée (obsolète).

### fix: auto-pilot — prod 52 journées : 3 bugs critiques corrigés (segments attendus, content séquentiel, health-check bloquant)

- **Segments attendus** : `_determine_next_ap_step` compare désormais `completed_segs` à `nb_days × 18` (invariant 6 sous-parties × 3 passes) et non aux segments existants — évite le faux positif si des segments manquent suite à un restart partiel.
- **Content API séquentiel** : remplace `launch_tts_for_all_days` (N threads simultanés) par une boucle folder-par-folder avec `_wait_folder_content_completed` — 1 journée à la fois, idempotente, compatible 52 jours sans exploser les rate limits.
- **Health-check bloquant** : `compute_health()` avec `ok=False` lève maintenant une `RuntimeError` au lieu d'un simple warning — l'auto-pilot reste en erreur si la formation est incomplète.

### fix: auto-pilot — 3 bugs supplémentaires corrigés post-review Codex

- **content API idempotent** : `launch_tts_for_all_days` n'est plus appelée si des `cours_folders` existent déjà (évite les doublons sur restart). Attente remplacée par `_wait_segments_completed()` qui surveille les segments réels plutôt que `tts_launched` (posé dès la création des folders).
- **review segments_failed propagé** : `run_content_review()` retourne `segments_failed` — l'auto-pilot lève maintenant une erreur si > 0, au lieu d'ignorer silencieusement les échecs partiels.
- **audio force_all=False** : cohérent avec le tracking `dirty` — seuls les folders non encore générés sont traités au lieu de tout regénérer depuis zéro.

### refactor: auto-pilot formation — state machine persistée en DB (résistante aux restarts Azure)

**Problème** : l'auto-pilot était un greenlet unique vivant en RAM pendant 2-4h. Un déploiement Azure (push staging → 10 workflows CI/CD → restart App Service) le tuait silencieusement. Résultat : la review de conformité n'était jamais lancée, `segments_reviewed=0`, pas de Word 2.

**Architecture avant** : `_run_auto_pilot()` — chef d'orchestre unique, état in-memory `_AUTO_PILOT_STATE{}`, paramètres non persistés.

**Architecture après** : state machine persistée en DB + runner court par étape.

Nouveaux champs `formation_pipeline_jobs` :
- `auto_pilot_enabled` / `auto_pilot_step` / `auto_pilot_model` / `auto_pilot_tts_mode`
- `auto_pilot_use_cc` / `auto_pilot_skip_vs` / `auto_pilot_volume_done`
- `auto_pilot_error` / `auto_pilot_locked_at` / `auto_pilot_lock_owner`

Nouveaux mécanismes :
- `_tick_auto_pilot(job_id)` : exécute 1 étape, écrit l'état en DB, se respawn pour la suivante
- `_determine_next_ap_step()` : checks idempotents (skip si déjà fait)
- `_acquire_ap_lock()` / `_release_ap_lock()` : lock optimiste TTL 5 min (prévient les doublons multi-workers)
- `resume_interrupted_auto_pilots()` : appelé au boot, reprend les jobs interrompus
- Boot hook dans `main_app.py` : `eventlet.spawn(resume_interrupted_auto_pilots)`

## 2026-04-29

### feat: card "Jour X" du step 6 redécoupée en 3 sous-zones avec flèches

Refonte visuelle de chaque folder card de l'étape 6 (Génération des cours, côté API) pour matérialiser le sous-flux interne d'une journée :

- **Zone 1 — Texte généré** (accent violet `rgba(167, 139, 250, ...)`) : Voir · Word · Word 2 · Rapport
- ↓ `<FlowArrowDown height={18} />`
- **Zone 2 — Sécurité volume · cible 90k mots** (accent ambre `rgba(245, 158, 11, ...)`) : Compléter le volume via API / Volume OK
- ↓ `<FlowArrowDown height={18} />`
- **Zone 3 — Révision conformité · règles #1-#27** (accent vert `rgba(52, 211, 153, ...)`) : Réviser la conformité via API

Chaque zone : padding `8px 10px`, `borderRadius: 8px`, fond teinté à 5-6%, `borderLeft: 3px solid` à 50% d'opacité, label uppercase 10px en couleur d'accent.

Avant : tous les boutons (6) étaient dans un seul `<div display: flex flex-wrap>` qui produisait 2-3 lignes de boutons indistinctes. Après : ordre du flux visuellement explicite, l'utilisateur comprend qu'il doit valider zone par zone du haut vers le bas.

Petit ajustement parent : `alignItems: 'center' → 'flex-start'` et `flex: 1 → '1 1 220px'` sur le bloc titre pour que la colonne de zones (plus haute) ne désaxe pas le titre.

Fichier : `frontend/src/pages/FormationPipeline.jsx` (~ligne 2585-2790).

### feat: connecteurs visuels (flèches/Y-fork/Y-merge) entre étapes du pipeline

Ajout de connecteurs visuels dans `FormationPipeline.jsx` pour matérialiser le flux de données entre les cards d'étapes :

- **`FlowArrowDown`** : flèche verticale ↓ entre 2 cards consécutives.
- **`FlowSplit`** : Y-fork qui descend du tronc commun (REAC) et bifurque vers les centres des 2 colonnes (API / Claude Code local).
- **`FlowMerge`** : Y-merge inverse — les 2 colonnes remontent vers une barre horizontale puis redescendent en tronc unique vers Synthèse TTS.

Placement :
1. RNCP → REAC : `<FlowArrowDown />`
2. REAC → split : `<FlowSplit />` en mode dual, `<FlowArrowDown />` en mono.
3. Dans le grid dual, entre chaque paire (KB → Global, Global → Journées, Journées → Génération) : 2 `<FlowArrowDown />` (1 par colonne, le second conditionné par `DUAL_COLUMN_ENABLED`).
4. Fin du grid → TTS : `<FlowMerge />` en dual, `<FlowArrowDown />` en mono.
5. Dans le `StepBlockCC` du step 6 : 2 mini-flèches entre les sous-blocs Génération cours → Sécurité volume → Révision conformité.

Implémentation pure CSS (divs absolus avec `calc(25% - 10px)` pour cibler les centres de colonnes du grid `1fr 1fr` gap `40px`). Couleur `rgba(167, 139, 250, 0.35)` (violet sobre, accent du projet). Aucune dépendance ajoutée, aucun SVG.

### feat: suppression de plateforme depuis l'onglet Plateformes (en plus de Modules)

L'admin peut désormais supprimer une plateforme directement depuis sa carte (onglet Plateformes), en complément du delete module dans l'onglet Modules. Les deux entrées coexistent et sont cohérentes.

**Backend** (`backend/routes/hr_routes.py`) — `DELETE /api/hr/platforms/<id>` avec cascade :

1. `content_generation_segments` → `content_generation_jobs`
2. `formation_knowledge_base` → `formation_pipeline_jobs`
3. `cours_documents` → `cours_folders` → `cours_config`
4. **`formation_modules`** : traitement différencié selon le type de module
   - **Modules "fait main"** (`source_pipeline_job_id IS NULL`) → **DELETE** : la plateforme EST le module, ils représentent la même chose
   - **Modules pipeline** (`source_pipeline_job_id NOT NULL`) → `UPDATE source_platform_id = NULL` : produit durable réutilisable indépendamment, reste au catalogue
5. `platform_config` (la ligne elle-même)

Réponse 200 inclut `manual_modules_deleted: N` pour le feedback admin. Logs et `video_visits` préservés (audit trail). Blobs Azure non supprimés (V1 conservatrice — nettoyage manuel via portail si besoin).

**Frontend** (`frontend/src/pages/HRDashboard.jsx`) :

- **Bouton delete sur chaque PlatformCard** : icône `delete_outline` 32×32 en haut à droite, z-30 pour rester au-dessus des overlays inactif/pending/error. Backdrop-blur 4px, slate muted au repos, tinte rose `#fee2e2`/`#dc2626` au hover.
- **Modale `type === 'platform'`** distincte de la modale `type === 'module'` : deux blocs cascade (sera supprimé / préservé) qui mentionnent explicitement les modules fait main associés et la conservation des modules pipeline. Type-to-confirm sur le nom exact de la plateforme. Au succès, `fetchPlatforms()` + `fetchModules()` rafraîchissent les deux vues (les modules fait main supprimés disparaissent du catalogue).
- **Garde-fous UX** : ⏎ valide si match, ⎋ ferme, click outside ferme (sauf pendant suppression), focus auto sur l'input.

**Conformité DESIGN.md** :
- ✓ Pattern modal pour destructive irréversible
- ✓ Pas de side-stripe borders
- ✓ Eyebrow uppercase tracked 0.18em
- ✓ Slate-tinted neutrals + accent rouge ciblé uniquement sur la zone destructive
- ✓ Examiner's Violet absent (zone destructive ≠ identité brand)

Fichiers modifiés : `backend/routes/hr_routes.py`, `frontend/src/pages/HRDashboard.jsx`.

### feat: plateformes vides ("fait main") inscrites au catalogue Modules

Demande utilisateur : quand on crée une plateforme via l'option **"Plateforme vide (sans cours)"** dans la modale Nouvelle plateforme (= contenu uploadé manuellement plus tard, sans pipeline auto), elle doit aussi apparaître dans l'onglet Modules pour pouvoir être supprimée comme les modules pipeline.

**Backend** (`backend/routes/hr_routes.py:create_platform`) :

- Quand `has_content == False` (ni `module_id`, ni `formation_id`, ni `new_formation` dans le payload), on inscrit automatiquement une entrée `formation_modules` avec :
  - `tp_name` = nom de la plateforme (l'admin n'a fourni que ça)
  - `rncp_code` = `NULL`
  - `version` = `manuel-v{N}` où N = compte des modules manuels existants + 1
  - `source_pipeline_job_id` = `NULL` (clé de distinction avec les modules pipeline)
  - `source_platform_id` = la plateforme nouvellement créée
  - `status` = `validated`
- Les plateformes **déjà existantes** ne sont PAS rétroactivement inscrites (pas de migration auto) — éviter de polluer le catalogue avec P1-P4 et autres plateformes système. Si besoin, migration manuelle ciblée à faire.

**Frontend** (`frontend/src/pages/HRDashboard.jsx`) :

- Badge **"Fait main"** ajouté dans `ModulesCatalogueView` à côté des badges Validé/Brouillon, affiché quand `m.source_pipeline_job_id == null`. Slate neutre (`colors.innerBg` + `colors.textMuted` + border), eyebrow uppercase tracked 0.15em — cohérent avec le pattern badge existant, ne consomme pas l'accent Examiner's Violet (One Voice Rule preservée).
- Le delete déjà en place fonctionne tel quel sur ces modules : il les retire du catalogue. La plateforme source elle-même reste intacte (visible dans l'onglet Plateformes) — comportement cohérent avec le delete des modules pipeline.

Fichiers modifiés : `backend/routes/hr_routes.py`, `frontend/src/pages/HRDashboard.jsx`.

### feat: suppression d'un module depuis l'onglet Modules (skill impeccable)

Demande utilisateur clarifiée : la suppression doit s'exercer sur les **modules du catalogue** (onglet Modules), pas sur les cartes plateforme. La précédente itération (icône poubelle sur chaque PlatformCard) a été **revertée** au profit du bon emplacement.

**Backend** (`backend/routes/hr_routes.py`) — nouvel endpoint `DELETE /api/hr/formation-modules/<id>` :

- **Vérification préalable** : si `platform_config.source_module_id = ?` retourne ≥ 1 ligne, on refuse avec **HTTP 409** + message explicite listant les plateformes bloquantes (`{"blocking_platforms": [{id, name}, ...]}`).
- **Sinon** : `DELETE FROM formation_modules WHERE id = ?` — opération minimale, le module n'est qu'une enveloppe métadonnées (les vraies données vivent dans `formation_pipeline_jobs` + `cours_folders` rattachés à la plateforme source).
- Pipeline source, plateforme source, blobs Azure : **tous préservés**. Les promos déjà créées qui utilisent ce module continuent de fonctionner (elles ont déjà cloné le contenu).

**Frontend** (`frontend/src/pages/HRDashboard.jsx`) :

- **Composant `ModuleDeleteButton`** : icône `delete_outline` 32×32, slate au repos, fond `rgba(220, 38, 38, 0.08)` + texte `#dc2626` + border `rgba(220, 38, 38, 0.25)` au hover. Cohérent avec le pattern Audio Item delete documenté dans `DESIGN.md`.
- **Placement** : dans la rangée de chaque module de `ModulesCatalogueView`, juste à droite du bouton "Utiliser" (qui devient un container `flex gap-2` au lieu de `flex-shrink-0` simple).
- **Modale de confirmation enrichie** (max-width 480px, registre Examiner's Desk) :
  - Header : icône `delete_forever` dans tuile rose + titre "Retirer ce module du catalogue" + helper "Le module disparaît de la liste · pipeline source préservée"
  - Body : carte d'identification du module (TP + RNCP + version), bloc rouge "sera retiré" (2 items), bloc slate "préservé" (4 items dont l'info importante : les promos existantes continuent de fonctionner)
  - **Type-to-confirm** sur la clé `<TP> · <version>` (ex. `TP CRCD · 2026-v5`) — assez précis pour forcer une lecture attentive sans rendre la saisie pénible
  - Footer : "Annuler" outlined + "Retirer du catalogue" rouge (désactivé en `#fca5a5` tant que pas matché)
- **State réutilisé** : `deleteConfirmTypedName` (le state existait déjà pour la branche platform — repris pour module sans renommer pour minimiser le diff).
- **Raccourcis** : ⏎ valide si match, ⎋ annule, click-outside ferme.

**Conformité DESIGN.md** :
- ✓ Pattern modal pour destructive irréversible
- ✓ Pas de side-stripe borders (interdit par §Absolute bans)
- ✓ Eyebrow labels uppercase tracked 0.18em
- ✓ Examiner's Violet absent du destructive
- ✓ Slate-tinted neutrals + accent rose ciblé uniquement sur la zone destructive

Fichiers modifiés : `backend/routes/hr_routes.py`, `frontend/src/pages/HRDashboard.jsx`.

### tweak: API DeepSeek utilise deepseek-v4-pro (au lieu de -flash)

Sur demande utilisateur, l'option `api_deepseek` du dropdown de création de plateforme envoie désormais `model: 'pro'` (mappé vers `deepseek-v4-pro`) plutôt que `flash`. Pro = top modèle DeepSeek, qualité supérieure pour la génération de cours 90k mots / journée. Coût plus élevé mais reste largement inférieur à Anthropic Sonnet.

Fichier : `frontend/src/pages/HRDashboard.jsx` (1 ligne payload + libellé dropdown).

### feat: choix API Anthropic / API DeepSeek dans la création de plateforme

Le dropdown "Mode d'exécution des étapes IA" de la modale "Nouvelle plateforme" (HR Dashboard) propose maintenant **4 options** au lieu de 3 :

- `api` — API Anthropic (Sonnet, ~5–7$/7h)
- `api_deepseek` — **NOUVEAU** : API DeepSeek (deepseek-v4-flash) ; consomme `DEEPSEEK_API_KEY`
- `claude_code` — Claude Code local (forfait Pro/Max via OAuth)
- `test` — Mode test (DOCX/TXT pré-rédigés, ~5 min)

Implémentation : pure UI, aucune modif backend nécessaire. Lorsque l'utilisateur sélectionne `api_deepseek`, le payload `POST /api/formation/<id>/run-auto` reçoit `model: 'flash'` qui est déjà mappé côté backend (`formation_routes.py:1980-1985`) vers `api_model = "deepseek-v4-flash"`. Le client Anthropic-compatible (`anthropic_client.py:_resolve_provider`) détecte le préfixe `deepseek-` et route automatiquement vers `https://api.deepseek.com/anthropic/v1/messages` avec `DEEPSEEK_API_KEY` — même si `ANTHROPIC_API_KEY` est aussi présente dans le `.env`.

Permet à l'utilisateur de garder les deux clés (Anthropic + DeepSeek) dans son `.env` et de choisir le provider plateforme par plateforme.

Fichier modifié : `frontend/src/pages/HRDashboard.jsx` (option dropdown + helper text + body du fetch run-auto).

### feat: bouton "Compléter le volume via API" dans la card de gauche

Suite à l'uniformisation backend (auto-pilot fait volume safety dans les 2 modes), ajout du bouton manuel correspondant dans l'UI :

**Backend** (`formation_routes.py`) : `POST /api/formation/<id>/content/<folder>/volume-safety` accepte maintenant `{"mode": "api"|"cc"}`. Mode "api" → `run_volume_safety_api`, mode "cc" → `run_volume_safety` (legacy, requiert LOCAL_DEV+claude). Mode "cc" est le défaut pour rétrocompatibilité avec le bouton existant à droite.

**Frontend** (`FormationPipeline.jsx`) : nouveau bouton **"Compléter le volume via API"** sur chaque journée de la card gauche, juste avant "Réviser la conformité via API". Comportement :
- Désactivé si génération pas terminée
- Actif (orange) si déficit > 0 — appelle `volume-safety` avec `mode='api'`
- Vert "Volume OK" si total ≥ 90 000 mots
- "Enrichissement…" pendant l'opération

`handleLaunchVolumeSafety(folderId, mode='cc')` accepte un nouveau param `mode`. Le bouton CC à droite continue d'appeler `'cc'` par défaut (inchangé).

L'utilisateur a maintenant la séquence complète **dans les 2 colonnes** :
- Gauche (API) : Voir · Word · Word 2 · Rapport · **Compléter le volume via API** · Réviser la conformité via API
- Droite (CC local) : Compléter (subprocess Claude) · Réviser conformité (4 chunks)

### feat: pipeline auto-pilot uniformisée — volume safety dans les deux modes (API + Claude Code)

Avant : volume safety était gardé dans un `if use_claude_code:` qui le réservait au mode CC. Le mode API sautait totalement cette étape, donc une formation lancée en API n'avait aucune garantie d'atteindre 90k mots/journée. Demande utilisateur : harmoniser pour que les 2 modes suivent la même séquence d'étapes.

Implémentation :
1. Nouvelle fonction `run_volume_safety_api(job_id, folder_id, model)` dans `claude_code_mission_service.py`. Même invariant (90k mots/jour), même algo multi-passes (max 3) que `run_volume_safety`, mais via `_anthropic_post` au lieu de subprocess `claude`. Helper `_build_volume_safety_prompt_api` qui combine task + texte segment + règles dans un seul prompt (le mode API n'a pas de filesystem partagé entre Claude et le backend).
2. `_run_auto_pilot` (`formation_routes.py`) : dispatch dynamique selon `use_claude_code` :
   - `True` → `run_volume_safety(...)` (CC, gratuit)
   - `False` → `run_volume_safety_api(...)` (API, payant)
3. Logs différenciés (`[CC]` vs `[API]`) pour debug.

Conséquence : la séquence d'auto-pilot est maintenant identique pour les 2 branches :
1. RNCP + REAC + KB + Global + Daily + Content (texte cours)
2. **Volume safety** (CC ou API selon le mode)
3. **Révision conformité** (CC ou API selon le mode)
4. Audio TTS (Fish Audio / gTTS / mock selon le choix utilisateur)
5. Health-check final

Note coût mode API : volume safety en API consomme ~5-10$ supplémentaires sur le forfait Anthropic (Sonnet, ~5 segments × 8k tokens output × 1-3 passes par folder × N folders). C'est le prix de l'invariant 90k mots — l'utilisateur l'assume en choisissant le mode API.

Le mode TEST garde son skip_volume_safety=True pour itérer rapidement sur la review.

### feat: mode TEST skip volume safety pour itérer plus vite sur la review

Une fois validé que volume safety multi-passes fonctionne (job 14 : 94k mots atteints), le besoin a basculé sur **itérer rapidement sur la qualité de la révision conformité** (qui était catastrophique en Haiku, à valider en Sonnet).

Volume safety prend ~30-45 min en multi-passes. La review seule prend ~10-15 min. Donc en skippant volume safety en mode TEST, on divise le temps par 3 pour chaque itération sur la review.

Implémentation :
- Nouveau paramètre `skip_volume_safety: bool = False` sur `_run_auto_pilot`
- Le bloc "Sécurité volume" devient `if skip_volume_safety: log skip elif use_claude_code: ...`
- Hardcodé `True` dans `init_test_pipeline` pour le mode TEST (qui appelle `_run_auto_pilot(..., skip_volume_safety=True)`)
- Note frontend mise à jour : "Seule la révision conformité tourne (~15 min)"

Conséquence : la review tourne sur les segments du DOCX original (~60k mots, sans enrichissement). Si la qualité review est mauvaise, c'est un bug review pur — pas une interaction avec volume safety.

Pour re-tester volume safety, il faut soit :
1. Désactiver le skip dans `init_test_pipeline` (1 ligne à changer)
2. Ajouter une checkbox frontend "Aussi enrichir le volume" (~15 min de code)

### fix: mode TEST passe de Haiku à Sonnet pour volume_safety + review

Découverte sur le job 14 : avec Haiku, la review produisait des patches catastrophiques :
- **Règle #21 (fusion de phrases avec "que")** : Haiku tape `"qu"` + mot collé sans espace ni "e" — `"quimaginez"`, `"quvous"`, `"qusupposez"`, `"qune"` au lieu de `"que vous imaginez"`, etc. Mots fusionnés inintelligibles.
- **Règle #22 (discours direct → indirect)** : appliquée mécaniquement à TOUS les guillemets, génère du blabla répétitif `"on vous dit, en substance, que..."` 6 fois dans le même segment.

Sonnet a le jugement linguistique pour fusionner proprement les phrases ("Prenons un cas fictif pour illustrer une situation où vous travaillez pour une PME...") et varier les transformations de discours rapporté. Le mode TEST tourne sur le forfait CC donc Sonnet est gratuit côté API — pas de raison économique de garder Haiku.

Hardcodé `"sonnet"` dans `eventlet.spawn(_run_auto_pilot, ...)` du mode test (`formation_routes.py:init_test_pipeline`). Pour les modes API et Claude Code "normal", le modèle reste choisi par l'utilisateur via le frontend.

À noter : ce qui semblait être des troncatures à l'écran (`"vou"`, `"person"`, `"troi"`) est purement cosmétique — l'UI tronque l'affichage des replacements pour la lisibilité, mais le contenu réel en DB est complet.

### feat: volume safety multi-passes — boucle jusqu'à atteindre 90k mots (max 3 passes)

Avant : `run_volume_safety` faisait 1 passe sur les 5 segments les plus courts → gain max ~15k mots. Si déficit initial > 15k (ex. job 13 du mode test : déficit -30k), volume safety **ne pouvait pas** combler le gap, ce qui contredisait l'invariant "chaque journée doit atteindre 90k mots avant la révision".

Maintenant : boucle interne `for pass_idx in range(_VOLUME_SAFETY_MAX_PASSES=3)`. À chaque passe :
1. Re-audit du folder (le déficit a été réduit par la passe précédente)
2. Si `deficit == 0` → break early
3. Identifie les nouveaux TOP 5 segments les plus courts
4. Subprocess Claude Code pour chacun + append + UPDATE DB

Capacité max : 3 passes × 5 segments × ~3000 mots = **~45k mots** par folder, suffisant pour les déficits réalistes.

Re-assemble + upload Azure une seule fois à la fin (pas à chaque passe → économise les appels Azure).

Le résultat retourne `passes_run` et `target_reached` pour audit. Si `target_reached=False` après 3 passes, c'est un signal qu'il faudrait soit augmenter `_VOLUME_SAFETY_MAX_PASSES`, soit que les segments restants atteignent leur limite intrinsèque.

Pour les chunk dirs : nouvelle convention `pass_<n>_segment_<id>/` au lieu de `segment_<id>/` pour ne pas écraser les outputs entre passes (debuggable).

### fix: bug critique volume safety — colonne `updated_at` inexistante faisait échouer 100% des enrichissements silencieusement

Détecté lors du premier test du mode TEST (job 13, plateforme 16). `run_volume_safety` a bien tourné les subprocess Claude Code pour les 5 segments les plus courts, généré ~15 KB de contenu enrichi par segment dans leurs `output.md` respectifs, MAIS le `cursor.execute("UPDATE content_generation_segments SET ... updated_at = CURRENT_TIMESTAMP WHERE id = ?")` levait `OperationalError: no such column: updated_at` (la colonne n'existe pas dans le schéma — c'est un copier-coller depuis `content_generation_jobs` qui a cette colonne).

L'exception était capturée par le `except Exception` autour du subprocess → segment ajouté à `failed`, append en DB jamais fait. Conséquence : tous les enrichissements volume safety étaient invisibles côté DB depuis l'introduction de cette feature, alors que le code « semblait » tourner (subprocess Claude Code, output.md créé, log info "📏 Segment X enrichi").

Fix : retiré `updated_at = CURRENT_TIMESTAMP` du UPDATE. Pas besoin d'ajouter la colonne pour l'instant (aucun autre code la lit/écrit sur cette table).

Pour les jobs déjà cassés par ce bug : les `output.md` existent dans `review_queue/job_<id>/step_volume_safety/folder_<id>/segment_<id>/`. Un script de remédiation peut les rattraper en append à `text_content` + UPDATE word_count/dirty/reviewed. Pour le job 13, la review en cours travaille sur la version non-enrichie — pas de blocage, juste 60k mots au lieu de 90k cible.

### feat: mode TEST — injecte des DOCX/TXT au lieu de générer (validation pipeline en 5 min)

3ème option dans le select "Mode d'exécution des étapes IA" : **"TEST — injecte des DOCX/TXT pré-rédigés"**. Permet de valider toute la pipeline en aval (finalize + review + audio + health-check) sans payer/attendre la génération content (30-60 min, 90k mots × N journées).

**Frontend (HRDashboard)** :
- Quand `autoPilotMode === 'test'` : le select TTS est désactivé (forcé `mock`) et une zone d'upload apparaît (drag & drop + multiple files, accept `.docx,.txt`).
- Le user fournit `Math.ceil(hours/7)` fichiers (1 par journée). Validation côté front : refuse si compte ≠ attendu.
- Liste les fichiers uploadés avec taille pour confirmation visuelle.

**Backend** : nouvelle route `POST /api/formation/init-test` (multipart/form-data) qui :
1. Crée la plateforme dédiée (idem `/init`)
2. Crée le job pipeline avec **stubs** (REAC mock, global_program mock, daily_programs mock 6 sub × N jours, status='daily_validated')
3. Pour chaque doc : parse via `_read_doc_text` (`.txt` direct, `.docx` via `python-docx`), découpe en 18 chunks équilibrés en paragraphes via `_split_into_18_chunks`
4. Crée 1 cours_folder + 1 cg_job + 18 segments par journée (`status='completed', dirty=1, reviewed=0`)
5. Lance l'auto-pilot (eventlet.spawn) avec `tts_mode='mock'`
6. Auto-pilot skippe naturellement KB/global/daily/content (les `if not j.get(...)` détectent que tout est déjà fait, et `_list_content_chunks` retourne 0 chunk vu que tous les segments sont déjà completed)
7. Tourne uniquement : finalize content (assemble + DOCX + snapshot pre-review) → review (4 chunks par jour) → audio mock → health-check

**Test pratique** : avec `courstxt/formation_jour1.txt` (92k mots), le découpage produit 18 chunks de ~5000 mots chacun (taille production réelle). La review a donc du vrai contenu à patcher.

**Durée totale en mode test** : ~5-10 min (vs 30-60 min en mode normal). Cible : valider en pratique les fixes (Bug 1 finalize, Bug 2 snapshot, Bug 3 visibilité review) + les nouveaux services (pre-flight, health-check).

**Important — coût du mode test** : volume safety (enrichit les segments courts) et révision conformité (4 agents multi-rules par jour) consomment de l'IA. Pour rester gratuit côté Anthropic API, l'auto-pilot est lancé avec `use_claude_code=True` (subprocess local, forfait Pro/Max). Pré-requis backend : `LOCAL_DEV=true` + binary `claude` dans le PATH (validé par le pre-flight). Sans ça, le mode test échouera proprement au pre-flight avec un message clair plutôt que de partir sur l'API payante par surprise.

### feat: choix API Anthropic vs Claude Code dans le formulaire de création de plateforme

Le formulaire `Nouvelle plateforme` (HRDashboard) propose maintenant un select **"Mode d'exécution des étapes IA"** sous la voix TTS, avec deux options :

- **API Anthropic** (défaut) — appels directs via `ANTHROPIC_API_KEY`. Aucune dépendance locale, ~5–7$ pour une formation 7h Sonnet.
- **Claude Code local** — subprocess `claude` via le forfait Pro/Max (OAuth). Gratuit côté API mais nécessite `LOCAL_DEV=true` + binary `claude` dans le PATH du backend (vérifié par le pre-flight).

Le choix est envoyé via `use_claude_code` au `POST /api/formation/<id>/run-auto`. Avant ce commit, le frontend ne passait jamais la flag → le backend défaultait toujours à `False` (= API), ce qui empêchait d'utiliser le forfait Claude Code en pratique.

Une note explicative s'affiche sous le select selon l'option choisie pour rappeler le pré-requis backend.

### tooling: `tools/pipeline_audit.py` — audit ligne de commande de toutes les pipelines

CLI tool qui appelle `compute_health` sur tous les `formation_pipeline_jobs` en DB et donne un verdict en 1 commande :

```
python tools/pipeline_audit.py            # vue compacte tous les jobs
python tools/pipeline_audit.py --job 10   # vue détaillée d'un job (tous les checks)
python tools/pipeline_audit.py --broken   # uniquement les jobs cassés
```

Distingue 3 états :
- 🟢 OK (statut `audio_launched`/`done` ET tous les checks verts)
- 🟡 warning (incohérence mineure : snapshot pre-review manquant)
- 🔴 cassé (incohérence bloquante : segments incomplets, audio dirty=1, etc.)
- ⏳ en cours (statut intermédiaire : init/kb_ready/daily_validated/error — pas auditable comme final)

Code de sortie 1 si au moins 1 job cassé → scriptable en CI/cron pour alerter sur des régressions silencieuses.

### feat: pre-flight check + health-check de la pipeline formation

Pour aller vers le "vrai one-shot" et détecter les régressions sans devoir lancer une pipeline complète (1-2h), ajout d'un service `formation_health_service.py` exposé via deux routes :

**Pre-flight** (`POST /api/formation/<id>/preflight`) — audit AVANT lancement, valide :
- `ANTHROPIC_API_KEY` présente et au format `sk-ant-`
- `LOCAL_DEV=true` + binary `claude` dans le PATH (si `use_claude_code=True`)
- `AZURE_TTS_STORAGE_CONNECTION_STRING` + `AZURE_AUDIO_STORAGE_CONNECTION_STRING` connectables (`list_containers` 1 page)
- `FISH_AUDIO_API_KEY` présente (si `tts_mode=fish_audio`)
- France Compétences accessible (sauf si REAC déjà téléchargé)
- Job existant + état cohérent

Hook auto au début de `_run_auto_pilot` : si bloquant, lève `RuntimeError("Pre-flight bloqué — checks fatals : X, Y. detail")` avant de toucher quoi que ce soit. Évite 80% des plantages "config foireuse" qui actuellement laissent des pipelines à mi-chemin.

**Health-check** (`GET /api/formation/<id>/health`) — audit APRÈS lancement, vérifie 7 invariants :
1. `segments_completed` : N×6×3 segments en `status='completed'`
2. `cg_jobs_completed` : tous les `content_generation_jobs.status='completed'`
3. `docx_buildable` : pour chaque folder, segments + sub_parts cohérents → DOCX construisible à la volée
4. `pre_review_snapshotted` : `text_content_pre_review IS NOT NULL` partout (warning si manquant)
5. `review_consistent` : pas de segments avec `reviewed=0 AND review_error IS NULL` (preuve que la révision n'a pas été tentée)
6. `audio_tts_files` : `dirty=0` partout (audio régénéré)
7. `module_persistant` : ligne dans `formation_modules` créée

Hook auto en fin d'`_run_auto_pilot` : résultat stocké dans `_AUTO_PILOT_STATE[job_id]["health"]` pour que l'UI affiche un bandeau "santé OK" ou "N incohérences détectées" + bouton de remédiation par check (à venir côté frontend).

Tests sur jobs existants confirment :
- Job 8 (premier run CC OK) : tout vert sauf `pre_review_snapshotted` (warning normal — bug 2 du commit précédent : ce job tournait avant le fix snapshot).
- Job 11 : pre-flight tout vert, validé que la pipeline pourrait re-tourner one-shot.

### fix: pipeline auto-pilot — 3 bugs corrigés sur le flow content/review

Trois bugs identifiés en analysant les jobs 10 (TP CRCD test-7h, segments reviewed=0) et 11 (TP CRCD test-14h, cg_jobs status=idle, DOCX absents) qui étaient tous deux à `audio_launched` mais avec un état incohérent.

**Bug 1 — `_finalize_content_step` skippé si erreurs résiduelles** (`claude_code_mission_service.py:_execute_chunked`). La condition `if step_key == "content" and not progress["errors"]:` empêchait l'assemblage DOCX + snapshot pre-review + transition cg_jobs en `completed` dès qu'un seul chunk échouait sur N. Cas réel : job 11 avait 1 chunk en erreur sur 36 (rate limit 429) → aucun DOCX produit, UI bloquée à "0/2 journées terminées" malgré 35 segments OK.
Fix : finalize **toujours** appelé. Le finalize gère déjà ses propres erreurs en interne (`all_finalize_ok` flag) et ne déplace `step_content/` vers `_done/` que si 100% des assemble_and_upload réussissent.

**Bug 2 — Snapshot pre-review perdu si la review tourne avant le finalize** (`claude_code_mission_service.py:_execute_chunked`). Si la review patche les segments avant que `_finalize_content_step` ait pu snapshotter `text_content → text_content_pre_review`, la version originale est définitivement perdue. Le bouton "Word original" devient inutile.
Fix : snapshot dupliqué en début de `_execute_chunked("review")`. Idempotent (ne réécrit jamais), best-effort (un échec snapshot ne bloque pas la review).

**Bug 3 — Auto-pilot avale silencieusement les erreurs review** (`formation_routes.py:_run_auto_pilot`). Le `try/except Exception` autour de `execute_mission_locally("review")` était volontairement best-effort pour ne pas bloquer l'audio, mais sans tracker l'erreur dans `_AUTO_PILOT_STATE`, l'utilisateur voit `audio_launched` sans savoir que la conformité a sauté. Cas réel : job 10 — `review_queue/job_10/` resté vide, segments avec `reviewed=0` ET `review_error=null` (preuve que ni CC ni API n'a été appelé).
Fix : capture de l'erreur dans `_AUTO_PILOT_STATE[job_id]["review_error"]` + `review_status="failed"` (CC et API). L'UI peut maintenant afficher un bandeau "révision non faite — relancer manuellement".

Reste à faire : remédiation des deux jobs cassés (10 et 11) — relancer review pour job 10, finalize pour job 11. Bug indépendant sur le snapshot pre-review déjà perdu pour job 11 (review a tourné avant le snapshot fix).

## 2026-04-28

### PRODUCT.md créé via `/impeccable teach` — direction stratégique design

Première écriture de `PRODUCT.md` à la racine du projet (~7.3 Ko). Document strategique requis par le skill `impeccable` pour ancrer les futures décisions design.

Principales décisions captées via 2 rounds d'interview structurée :

- **Register** : `product` (le design SERT le produit, pas l'inverse — confirmé par App.jsx 100% applicatif).
- **Persona prioritaire** : **admins/formateurs** quand un choix design oppose admin et apprenant. L'opérateur prime sur l'utilisateur final (inversion par rapport au réflexe "user-first" SaaS).
- **Posture émotionnelle apprenant** : sérieux institutionnel (cadre RNCP officiel), pas chaleureux ni motivationnel.
- **Posture émotionnelle admin** : calme professionnel (Linear/Stripe-like), pas cockpit mission-control ni power-user sec.
- **Personnalité 3 mots** : rigoureuse · institutionnelle · sobre.
- **Références positives** : Coursera / edX / MIT OCW (institutionnel légitime).
- **Anti-référence principale** : Edtech "playful" (Duolingo, Memrise, Brilliant). Aucune gamification, pas de mascots, pas de confettis, pas de "streaks". Le sérieux est un produit, pas un défaut à compenser.
- **Anti-références implicites** : AI slop (carré violet + abstract icon), hero-metric SaaS, identical card grids, gradient text, glassmorphism décoratif.
- **Accessibilité** : pas d'audit WCAG complet en priorité immédiate. Sens commun (contraste ≥ 4.5:1, focus visible, sémantique HTML). À revisiter si exigence Qualiopi/RGAA tombe.

5 design principles dérivés (reproduits intégralement dans `PRODUCT.md`) :

1. L'institution avant l'expérience.
2. L'opérateur avant l'apprenant en cas de conflit.
3. Calme sans froideur académique (mariage Coursera + Linear).
4. Un RNCP, un module durable, un design durable (cohérence avec `un-rncp-un-module-durable`).
5. Anti-Duolingo strict.

DESIGN.md non encore généré — proposition à l'utilisateur de lancer `/impeccable document` pour capturer le système visuel actuel (Tailwind v4, palette violette `#8B5CF6` + slate dark `#0f172a` + light `#f8fafc`, Poppins/Fredoka/Fira Code, framer-motion, Material Icons self-hostés) afin que les futures variantes restent on-brand.

### DESIGN.md + DESIGN.json créés via `/impeccable document` — système visuel HR Dashboard

Génération du système visuel **scopé strict au HR Dashboard** (et par extension au reste du côté admin : `/admin`, `/formation-pipeline`, `/schedule-config`, `/debug`). L'apprenant-side est explicitement **hors scope** dans `DESIGN.md` — un futur agent qui veut designer `/video` ou `/recorder` ne doit pas appliquer ce système.

**`DESIGN.md`** (~22 Ko) — format Stitch officiel : YAML frontmatter (tokens machine-readable) + 6 sections markdown imposées (Overview / Colors / Typography / Elevation / Components / Do's and Don'ts). Captures :

- **Creative North Star** : "The Examiner's Desk" (le bureau de l'examinateur RNCP — civic minimalism + product calm).
- **Palette** : 1 primaire (Examiner's Violet `#8B5CF6`) + neutres slate-tinted (canvas / surface / recessed / text / border en duo dark/light) + 3 status (locked green, error red, warning amber). Aucun bleu — le `#137fec` legacy des modals AudiosModal/PDFModal est documenté comme **dette à rembourser**, pas comme rôle.
- **Typographie** : **Inter exclusive** sur la surface admin (divergence volontaire de Poppins global qui sert l'apprenant). 5 niveaux : display 24px / title 18px / body 14px / label 12px / eyebrow 10px tracked uppercase.
- **Élévation** : flat by default + tonal layering. Aucune shadow en dark, shadow très subtil sur les cartes en light. Drag-lift uniquement sur slide-to-confirm.
- **Composants signature** : Slide-to-Confirm (la seule exception au "no bounce", easing `cubic-bezier(0.34, 1.56, 0.64, 1)` autorisé), platform card, status pills, primary button, audio item, modal, pagination.
- **7 Named Rules** : The One Voice Rule, The No-Stitch-Blue Rule, The Slate-Drift Rule, The Inter-Only Rule, The Tracked-Eyebrow Rule, The Flat-by-Default Rule, The Lift-on-Grab-Only Rule.
- **Do's** (9) et **Don'ts** (13) qui citent verbatim les anti-références de PRODUCT.md (anti-Duolingo, anti-AI-slop, anti-hero-metric, anti-identical-card-grids) plus l'incident logo violet+hub d'avril 2026 documenté comme cas d'école.

**`DESIGN.json`** (~17 Ko) — sidecar Stitch v2 (extensions hors-frontmatter) :

- `colorMeta` : OKLCH canonique pour chaque couleur + tonal ramps 8 steps pour Examiner's Violet et le slate stack.
- `typographyMeta` : purpose pédagogique de chaque rôle.
- `shadows` (4) : card-lift-light, drag-lift, thumb-rest, modal-cast — chacun avec son rôle explicite.
- `motion` (5) : ease-default + ease-slide-confirm (la seule exception bounce) + 3 durées.
- `breakpoints` Tailwind v4 standard.
- `components` (6) : Primary Button, Status Pill — Locked, Platform Card, Slide to Confirm, Audio Item, Pagination Control. Chacun avec HTML self-contained + CSS expand-vanilla (Tailwind utilities expandées en propriétés literal pour rendu shadow-DOM dans le panel `impeccable live`).
- `narrative` : tiré verbatim de DESIGN.md (north star, overview, key characteristics, rules, dos, donts).

**Décisions stratégiques captées via interview structurée** (4 questions qualitatives) :

1. North Star = **The Examiner's Desk** (vs Standards Office, Operator's Console, Quiet Atelier).
2. Bleu legacy `#137fec` → **à phaser out** (documenté comme dette, pas comme rôle "info").
3. Élévation = **flat + tonal layering** (état actuel devient doctrine).
4. Composants = **outil-first sans cérémonie** (Linear / Raycast register).

**Loader vérifié** : `hasProduct: true`, `hasDesign: true`, `productPath: PRODUCT.md`, `designPath: DESIGN.md`. Les futures commandes `impeccable` chargeront ce contexte automatiquement. Tout futur travail sur le côté admin doit citer ces Named Rules avant de proposer une variation visuelle.

### `/hr-dashboard` — pagination simplifiée

Seul élément retenu de la tentative de refonte annulée : la pagination des cartes plateformes passe de "Précédent + cercles numérotés `w-8 h-8 rounded-full` + Suivant" à "Page X / Y + 2 chevrons icône-seule (rounded-xl 40×40)". Plus sobre pour 2-5 pages, l'utilisateur a validé visuellement.

### Refonte design `/hr-dashboard` — tentative annulée à la demande de l'utilisateur

Première passe de redesign HR Dashboard tentée (audit + chrome page + PlatformCard refactor en groupes hiérarchisés + empty state + pagination simplifiée + helper `CardActionTile`). **Annulée intégralement par l'utilisateur** ("reviens au design avant que tu modifies tout") — le design existant convenait. `HRDashboard.jsx` restauré à l'état pré-session (les changements logiques auto-pilot + modules modal de pré-session sont préservés).

Leçon pour une future tentative : ne pas refondre globalement sans validation incrémentale. Présenter chaque changement un par un (top nav d'abord, attendre validation, puis cartes, etc.) plutôt qu'un bloc "audit + 8 modifications simultanées". La friction venait du volume de changements appliqués d'un coup, pas nécessairement de la qualité de chacun.

### Subprocess Claude Code force désormais le FORFAIT (et non l'API à la carte)

Diagnostic en mode "watcher" sur l'étape KB en mode CC : Claude Code a renvoyé `billing_error` "Credit balance is too low" alors que le forfait Pro/Max est censé être actif. Cause trouvée dans `review_queue/job_X/step_kb/execution.log` : `"apiKeySource":"ANTHROPIC_API_KEY"`. La CLI Claude Code héritait de la variable d'env `ANTHROPIC_API_KEY` du shell parent et tapait sur le compte API à la carte (épuisé) au lieu du forfait local.

Fix dans `claude_code_mission_service.py:_run_subprocess` :
- `env = os.environ.copy()` puis suppression de `ANTHROPIC_API_KEY` et `ANTHROPIC_AUTH_TOKEN` avant le `subprocess.Popen(... env=child_env)`.
- Sans ces variables, Claude Code retombe sur le login OAuth stocké localement (`~/.claude/`) — c'est-à-dire **le forfait**.
- Logger le strip pour traçabilité : `"forfait local (env strip: ANTHROPIC_API_KEY)"`.

**Pré-requis** : il faut avoir fait `claude` interactif au moins une fois pour générer le token OAuth du forfait. Si l'utilisateur voit une erreur "not authenticated" après ce fix, c'est qu'il n'est pas loggué côté CLI — un simple `claude` dans un terminal puis `/login` règle ça.

Tous les subprocess CLI (KB, global, daily, content chunks, review chunks, volume safety) bénéficient automatiquement du fix puisqu'ils passent tous par `_run_subprocess`.

### Badge "Généré via API" masqué sur la colonne Claude Code

Petit fix UX : `ClaudeCodeStepActions` affichait le badge `generatedVia` même quand la valeur était `'api'`, ce qui faisait apparaître "Généré via API" sur la colonne droite "Claude Code Local". L'utilisateur se demande à juste titre pourquoi sa colonne CC parle d'API. Le badge est maintenant **uniquement** affiché si la dernière génération vient effectivement de Claude Code (`claude_code_haiku` ou `claude_code_sonnet`). Pour `'api'`, on s'efface — la colonne API à gauche a déjà ses propres indicateurs.

### Réactivation Claude Code pour étape KB + tolérance troncature JSON

L'étape KB avait été désactivée en mode Claude Code car le prompt visait "120-150k mots" en 1 appel — bien au-delà de la limite Sonnet 64K output, donc le JSON ressortait tronqué et l'import plantait. Réactivée maintenant que le compte Anthropic peut être économisé en utilisant Claude Code local.

**Backend** (`claude_code_mission_service.py`) :
- `_build_kb_mission` : prompt **borné à 1500-2500 mots par compétence** (× ~10 compétences ≈ 25K mots ≈ 38K tokens output, largement sous 64K). Volume "non négociable" explicite + listes au cap fixe (3 cas, 3 pièges, 8-12 termes vocab) pour éviter que Claude dépasse. Format JSON brut sans fence demandé.
- `_import_kb` : parsing **tolérant à la troncature**. Si `json.loads(output)` échoue, fallback sur `_repair_truncated_json` (du knowledge_base_service) qui referme proprement les structures `{`/`[` ouvertes et garde toutes les compétences complètes.

**Frontend** (`FormationPipeline.jsx`) :
- `CC_AUTO_EXEC_ENABLED.kb = true` (était `false`).
- `StepBlockCC stepIndex={2}` réintroduit avec `<ClaudeCodeStepActions stepKey="kb">` à la place du placeholder "API only" qui avait été ajouté en Phase A.
- Modèle par défaut Haiku (cohérent avec global/daily — KB ne nécessite pas Sonnet).

**Effet** : l'utilisateur peut désormais cliquer "Exécuter avec Claude Code" sur l'étape KB pour épargner ses crédits API Anthropic. Le subprocess local fait le job, output.md est parsé tolérant à la troncature, KB en DB.

### Fix auto-pilot — mapping raccourcis modèle + reprise après échec

Suite à un test utilisateur de l'auto-pilot, deux fixes :

**1. 404 sur `api.anthropic.com/v1/messages`** : l'auto-pilot passait `"sonnet"`/`"haiku"` (raccourcis CLI Claude Code) directement aux services API (`launch_kb_building`, `launch_global_program_generation`, etc.), qui les transmettaient au paramètre `model` de l'API Anthropic. L'API rejetait avec 404 car ces noms ne sont pas des IDs de modèles valides.
- Fix : mapping `_run_auto_pilot` → `api_model` :
  - `"haiku"` → `"claude-haiku-4-5-20251001"` (cohérent avec `HAIKU` du frontend)
  - `"sonnet"` → `None` (laisse les services utiliser leur `CLAUDE_MODEL` par défaut, soit `claude-sonnet-4-20250514`)
- Tous les `model=model` dans l'auto-pilot remplacés par `model=api_model`.

**2. Reprise auto-pilot après échec** : si l'auto-pilot plantait (ex. 404 ci-dessus), le job restait coincé en `status='error'` et il fallait recréer un nouveau job. Désormais :
- `_run_auto_pilot` détecte au démarrage si le statut est `error`/`audio_error` et **reset à un statut valide** déduit des champs concrets du job (`daily_programs_validated` → `daily_validated`, sinon `global_program_validated` → `global_validated`, etc., jusqu'à `init`). Nettoie aussi `error_message`.
- L'auto-pilot revérifie chaque étape via `if not j.get(...)` et skip celles déjà faites — donc reprise automatique à l'étape qui a planté.
- Frontend : nouveau bouton "Reprendre auto-pilot" (gradient bleu, icône autorenew) dans le bandeau rouge "Auto-pilot interrompu". Réutilise les `tts_mode` / `model` du run précédent.

### Trois entrées de pipeline + auto-pilot end-to-end

Restructuration des entrées de création de pipeline pour préparer l'expérience utilisateur finale, avec un mode auto-pilot qui enchaîne automatiquement toutes les étapes.

**Phase A — Étape KB forcée API only** (`FormationPipeline.jsx:1961`) :
- Suppression du `StepBlockCC stepIndex={2}` (Enrichissement KB en mode Claude Code).
- Remplacé par un placeholder informatif "Étape API only" (gris dashed) dans la colonne Claude Code, pour ne pas casser visuellement la grille 2-col.
- Justification : le KB s'exécute en parallèle 3 workers via API, ~5 min. Pas de plus-value à passer en CC. La séparation API/CC commence à partir de l'étape Programme global.

**Phase B — Bouton "Créer un nouveau module" + auto-pilot dans la modale Nouvelle plateforme** (`HRDashboard.jsx`) :
- Modale Catalogue Modules : bouton CTA en tête "+ Créer un nouveau module" qui ouvre la modale Nouvelle plateforme avec `formationMode='new'` pré-sélectionné. Permet de partir des Modules pour créer une formation, en miroir de l'autre flux.
- Modale Nouvelle plateforme : ajout d'une checkbox "Lancer en mode auto-pilot" + (si activé) sélecteur de voix TTS (gTTS par défaut, Mock, Fish Audio). Visibilité conditionnelle au mode "Nouvelle formation".
- `handleCreatePlatform` : si `autoPilot` activé après création du job, appel auto à `POST /api/formation/<id>/run-auto`. Ouverture de l'onglet `/formation-pipeline?job=<id>` dans tous les cas pour suivi.

**Phase C — Auto-pilot pipeline (backend + frontend)** :
- **Backend** (`formation_routes.py`) :
  - `_run_auto_pilot(job_id, tts_mode, model)` : greenlet eventlet qui orchestre REAC → KB → global (auto-validate) → daily (auto-validate) → content → audio. Stop-on-error : sur exception, le job conserve son statut error et l'auto-pilot s'arrête (l'utilisateur peut reprendre manuellement). Création/MAJ du module persistant à la fin (`voice_type` ajusté selon `tts_mode`).
  - Mécanisme : pour chaque étape async (KB, global, daily, content), `_wait_for(target_statuses, max_wait)` poll le `job.status` toutes les 3s avec timeout de sécurité (30 min KB/content, 10 min global/daily, 4h content total). Sur erreur ou status `error`/`audio_error`, lève une exception captée par le try englobant.
  - Étape REAC : reproduit en interne la logique de `_fetch_thread` (`download_reac_text` + RC + ROME en best-effort).
  - Étape audio : itère séquentiellement sur les `cours_folders` et appelle `generate_audio_from_script(force_all=True, mock=..., basic_tts=...)` selon le `tts_mode` choisi.
  - Routes : `POST /api/formation/<id>/run-auto` (lance, retourne 202), `GET /api/formation/<id>/run-auto/status` (état pour polling UI).
  - État partagé : `_AUTO_PILOT_STATE = {[job_id]: {step, status, started_at, ...}}` mémoire process. Idempotent : refuse 409 si auto-pilot déjà en cours pour ce job.
- **Frontend** (`FormationPipeline.jsx`) :
  - Hook `fetchAutoPilotStatus` + polling 5s sur `/run-auto/status` quand un job est sélectionné.
  - Bandeau bleu "Auto-pilot en cours — étape : <label>" en tête de la vue détail (icône autorenew, gradient bleu/violet, sous-titre avec tts_mode + model). Labels FR pour chaque étape (`reac`, `kb`, `global`, `daily`, `content`, `audio`).
  - Bandeau rouge "Auto-pilot interrompu" si `status === 'error'` avec étape qui a planté + message d'erreur.

## 2026-04-27

### Voix TTS persistée sur le module + badge "En cours…" supprimé en `audio_launched`

Deux fixes liés au comportement post-clôture de la pipeline :

**1. Badge "En cours…" indélogeable sur l'étape 7** :
- Avant : la step "Synthèse TTS Fish Audio" affichait en permanence un badge ambre "En cours…" même quand `job.status === 'audio_launched'` (la pipeline était pourtant terminée et le module créé). Cause : `audio_launched` était dans `POLLING_STATUSES` (légitime, on continue de poller pour récupérer la progression `audios_generated/19` par folder), mais ça déclenchait aussi l'affichage du badge.
- Fix : `FormationPipeline.jsx:879` exclut explicitement `audio_launched` du badge tout en le gardant dans le polling. Le contenu de la card affiche déjà "Synthèse audio lancée avec succès" + bandeau Module créé, le badge ambre était redondant.

**2. Persistance de la voix TTS sur le module formation** :
- Avant : si on relançait l'étape 7 avec une voix différente (ex. Fish Audio → gTTS), les MP3 dans Azure étaient écrasés (clé `platform-X/folder-Y/file.mp3`), donc le module pointait automatiquement vers les nouveaux audios — mais aucune trace en DB de la voix actuelle. Impossible de savoir d'un coup d'œil si le module avait des audios Fish Audio ou gTTS.
- Migration DB : 2 colonnes nullables sur `formation_modules` — `voice_type` (`'fish_audio' | 'gtts' | 'mock'`) et `voice_updated_at` (TIMESTAMP). Migration idempotente via `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` dans `init_db`.
- `launch_audio` (formation_routes.py) : à la création initiale du module, `voice_type` est inscrit. À chaque relance (module déjà existant via UNIQUE constraint sur `source_pipeline_job_id`), un `UPDATE` met à jour `voice_type` + `voice_updated_at` pour refléter la voix qui porte les MP3 actuels.
- Endpoint `/api/hr/formation-modules` : retourne désormais `voice_type` et `voice_updated_at`.
- Frontend : nouveau helper `voiceLabel`/`voiceColor` (Fish Audio = vert, gTTS = orange, mock = gris). Affiché dans le bandeau "Module créé" de l'étape 7 et dans la bannière "Pipeline terminée" en tête (avec mention "voix actuelle"). `handleLaunchAudio` re-fetch le module après chaque relance pour synchroniser le UI.

### Bandeau "Pipeline terminée — Clôturée" en tête de la vue détail

Quand `job.status === 'audio_launched'`, ajout d'un bandeau vert proéminent (gradient + glow) en tête de la vue détail du job (juste après l'en-tête, avant le Stepper). Il marque visuellement la clôture de la pipeline et regroupe :
- Titre "Pipeline terminée — formation prête"
- Nom du TP, nombre de journées générées, total MP3 (nb_days × 19), plateforme cible
- Rappel du module persistant créé (matérialise "1 RNCP = 1 module durable")
- Badge "CLÔTURÉE" pour confirmation rapide

Tag de statut dans l'en-tête : `audio_launched` est désormais affiché "Clôturée" au lieu du brut `audio launched`.

### Étape 6.5 — Sécurité volume (filet supplémentaire 90 000 mots/journée)

Ajout d'une étape intermédiaire entre la génération texte (étape 6) et la révision conformité (étape 6bis). **Sécurité supplémentaire** au floor par-segment de `_continue_content_until_volume` (qui s'exécute pendant la génération avec un seuil de 4000 mots/segment) — l'étape 6.5 audite par-journée et garantit qu'aucun folder n'est sous le seuil de 90 000 mots au total.

**Backend** (`claude_code_mission_service.py`) :
- `compute_volume_audit(job_id)` : calcule par folder le `total_words`, le déficit, et les N (5) segments les plus courts (par `word_count` ASC). Pure lecture, pas d'effet de bord.
- `run_volume_safety(job_id, folder_id, model)` : pour chaque segment court, lance 1 subprocess `claude` qui produit ≥1500 mots de contenu additionnel respectant les règles #1-#27. **Append-only** — le texte original n'est jamais réécrit, on concatène. Marque `dirty=1` et `reviewed=0` pour que le segment repasse en révision et regénère son audio TTS. Re-assemble + re-upload Azure pour que le Word soit à jour.
- `_build_volume_safety_chunk` : prompt qui (a) reprend le texte actuel via `input.md`, (b) reprend les règles via `rules.md`, (c) interdit explicitement de réécrire / répéter / inclure le texte de `input.md` dans `output.md`, (d) impose 200+ mots minimum mais cible 1500.

**Routes** (`formation_routes.py`) :
- `GET /api/formation/<job>/volume-audit` : retourne l'audit par folder.
- `POST /api/formation/<job>/content/<folder>/volume-safety` : spawn greenlet eventlet, retourne 202.
- `GET /api/formation/<job>/content/<folder>/volume-safety/status` : pour le polling.

**Frontend** (`FormationPipeline.jsx`) :
- Bloc "Sécurité volume — 90 000 mots/journée" inséré **dans la colonne Claude Code locale** (`StepBlockCC stepIndex={5}`), entre les deux sous-sections existantes "Génération des cours (texte)" et "Révision conformité (étape 6bis)". Cohérence de placement : la sécurité volume s'exécute via Claude Code subprocess, donc elle vit dans la colonne CC, pas en bloc autonome séparé.
- Style ambre dashed identique aux autres `ClaudeCodeStepActions` pour s'intégrer visuellement.
- Affichage par folder (compact) : Jour N — total / 90 000 (vert ≥90k, ambre 80-90k, rouge <80k) + mini barre de progression. Bouton "Compléter" (gradient ambre) conditionnel sur déficit > 0, badge "OK" sinon.
- Sélecteur de modèle (Sonnet par défaut, Haiku option).
- États dédiés : `volumeAudit`, `safetyRunning`, `safetyError`, `safetyModel`.
- useEffect : fetch audit dès qu'au moins une journée est completed ; polling 4s pendant exécution.

**Pourquoi append-only** : préserve le snapshot `text_content_pre_review` pris au finalize de l'étape 6 (= texte pur avant révision). Le bouton "Word" continue de pointer sur cette version originale, "Word 2" reflète le texte enrichi + révisé.

### Fix UI : étape 6 disparaissait après `audio_error` (textes pourtant intacts)

Symptôme reporté par l'utilisateur : capture d'écran avec badge "Terminé" sur l'étape 6 mais aucun bouton Voir/Word/Rapport — uniquement les boutons "Générer" du mode pending. Données pourtant intactes en DB (segments completed) et dans Azure (.txt blobs).

Root cause : la condition d'affichage du bloc "complété" de l'étape 6 ne couvrait que `tts_launched`, `audio_launched`, ou `ttsResult` en mémoire de session. Quand le TTS plantait (429 Google → status régressé en `audio_error`), le UI repartait sur la branche pending.

Corrections (`frontend/src/pages/FormationPipeline.jsx`) :
- Condition d'affichage étape 6 (ligne ~2031) : ajout `audio_error` + fallback robuste `contentFolders.some(f => f.content_status === 'completed')`. Tant qu'au moins une journée est marquée completed, on montre les contrôles, indépendamment du `job.status`.
- useEffect fetch contentFolders (ligne ~1098) : ajout `audio_error` à la liste des statuts qui déclenchent le chargement (sinon le fallback ci-dessus n'a pas de données à inspecter).
- Bouton "Réviser conformité (étape 6bis)" via Claude Code (ligne ~2284) : `disabled` étendu pour autoriser un lancement de révision même quand la pipeline est en `audio_error`.

Principe : "si l'étape est validée, elle est validée" — un échec d'étape ultérieure ne doit jamais masquer le résultat des étapes précédentes.

### Audit pipeline + Word 2 (post-révision) + auto-clean bandeau "en attente"

Audit complet de la pipeline bout-en-bout suite à demande utilisateur. 4 améliorations cohérentes :

**1. Bandeau "mission en attente d'import" intelligent** — `list_pending_missions` filtre maintenant les missions chunked dont `progress.status` est `done` ou `done_with_errors` sans erreurs. Le bandeau orange disparaît automatiquement quand le subprocess auto a fini son boulot (avant, il restait jusqu'à archivage explicite).

**2. Auto-archive `step_review/` à la fin du multi-agents** — `_finalize_review_step` appelle maintenant `_archive_mission(job_id, "review")` après le marquage `reviewed=1`. Le dossier passe dans `_done/<timestamp>-job<id>-review/` avec ses 4 sous-chunks (review_report.json conservés, lus par la modale via fallback `_done/`).

**3. Bouton "Word 2" — version post-révision** :
- Migration DB : nouvelle colonne `text_content_pre_review` dans `content_generation_segments` (ajoutée idempotemment via ALTER TABLE au premier `_finalize_content_step`).
- `_snapshot_pre_review(folder_ids)` : copie `text_content → text_content_pre_review` pour chaque segment completed (idempotent — n'écrase pas un snapshot existant).
- `_finalize_content_step` appelle ce snapshot juste après l'assemble_and_upload — capture l'état AVANT que la révision ne touche aux textes.
- `build_course_docx(job_id, folder_id, version="current"|"pre_review")` lit la bonne colonne. Filename suffixé `-pre-review.docx` ou `current`.
- Route `/api/formation/<job>/content/<folder>/docx?version=pre_review|current`.
- Frontend : bouton "Word" (violet) télécharge `pre_review` (= snapshot original). Nouveau bouton "Word 2" (vert) apparaît dès qu'une révision a été appliquée (`segments_reviewed > 0`) → télécharge `current` (= post-révision).
- TTS reste branché sur la DB actuelle (`text_content`) → utilise automatiquement le texte révisé.

**4. Audit pipeline complète (rappel pour l'utilisateur)** :
- Étape 3 KB : API only (Claude Code chunked KB désactivé via `CC_AUTO_EXEC_ENABLED.kb=false`)
- Étape 4 Programme global, étape 5 Programmes journée : API ou Claude Code single-chunk
- Étape 6 Génération cours : Claude Code chunked + continuation loop (cap 4000 mots/segment) + finalize (assemble + upload Azure + DOCX dispo + snapshot pre_review)
- Étape 6bis Révision conformité : Claude Code multi-agents 4 chunks (Éthique 1/2 + Éthique 2/2 + Anti-hallucination + Style oral), throttle 75s entre agents (configurable via `CC_CHUNK_DELAY_SEC`), import robuste avec fallback positionnel + résolution `(folder_id, sub_idx, passe)` au lieu de segment_id fragile, finalize (`reviewed=1` + archive)
- Étape 7 TTS : 3 modes (Fish Audio payant / gTTS gratuit / mock silence), tous lisent la DB actuelle = texte post-révision si appliquée

### Multi-agents review : 4 agents Claude Code spécialisés par groupe de règles

Demande utilisateur : éviter qu'un agent unique ne se concentre sur les violations qu'il voit le plus (#22 guillemets, #26 énumérations) et oublie #1-#17. Solution = N agents en parallèle, chacun avec son scope assigné.

**Backend — `claude_code_mission_service.py`** :
- Nouvelle constante `_REVIEW_RULE_GROUPS` : 4 groupes de règles
  1. **Éthique 1/2** : #1, #2, #3, #6, #7, #8 (spirituel, alcool, fêtes, flirt, chance, célébrités)
  2. **Éthique 2/2** : #4, #5, #11, #12, #13, #15, #16 (manipulation, discrimination, RGPD, médical)
  3. **Anti-hallucination** : #17, #18, #19, #20 (fictifs, chiffres, pédagogie)
  4. **Style oral** : #21, #22, #23, #24, #25, #26, #27
- `_list_review_chunks` retourne maintenant **4 chunks par journée** (1 par groupe) au lieu d'1.
- `_build_review_chunk` injecte le scope dans `task.md` : *"Tu vérifies UNIQUEMENT les règles {liste}. Ignore les violations hors de ton scope, un autre agent s'en occupe."*. **Pas de regex / pas de matching dans le code** — le prompt brief Claude, qui décide sémantiquement.
- `_import_review_chunk` : ne marque PLUS `reviewed=1` segment par segment (sinon le 2e agent skipperait les segments déjà touchés). Juste `dirty=1` si patch appliqué.
- Nouvelle fonction `_finalize_review_step(job_id)` appelée après la boucle complète des chunks → marque `reviewed=1` sur tous les segments.
- Le cap par segment est calculé dynamiquement selon le nombre de règles du groupe : ~5-15 patches/segment par agent. Total cumulé = jusqu'à ~40 patches/segment, bien au-delà du cap initial de 5.

**Backend — `formation_routes.py`** :
- Route `GET /api/formation/<job>/content/<folder>/review-report` agrège maintenant les **N rapports JSON des chunks multi-agents** en un rapport unique. Stats `summary` / `by_rule` / `by_segment` fusionnées. Ajout d'un champ `agent_group` sur chaque patch_detail pour tracer quel agent a proposé quoi. Ajout des champs `n_agents` et `agents_used` au rapport.

**Conséquence sur le temps** :
- 4 agents × 1 journée = 4 chunks séquentiels avec throttle 75s = ~5-6 min/journée pour la révision (vs ~1 min en single-agent).
- 4× le bootstrap CLI Claude Code = 4× la consommation tokens d'input par journée. Reste dans le quota tier max grâce au throttle anti-rate-limit existant.

**Avantage qualité** : chaque agent fait sa propre passe complète sur le texte avec son scope dédié. Pas de favoritisme. Les règles éthiques #1-#17 sont auditées avec la même profondeur que les stylistiques.

**Pour l'utilisateur actuel (job_8)** : les segments sont déjà `reviewed=1` du run précédent. Pour relancer la révision multi-agents, il faut soit reset les flags via SQLite, soit attendre la prochaine pipeline.

### Modale "Rapport de révision conformité" + endpoint dédié

Bouton "Rapport" sur chaque carte de dossier cours (à côté de "Voir" / "Word"), visible si au moins 1 segment a été audité. Ouvre une modale qui affiche :

- **Cartes summary** : segments audités / patches proposés / appliqués / rejetés / segments échoués
- **Tableau "Patches par règle violée"** : `#22 (guillemets) — 30 proposés, 22 appliqués, 8 rejetés` avec libellés humains des règles #18 / #21 / #22 / #24 / #25 / #26 / #27
- **Liste expandable par segment** : pour chaque (sous-partie, passe), détail de chaque patch avec original / replacement en diff +/− coloré, raison, statut (appliqué/rejeté + raison du rejet : "introuvable verbatim" ou "ambiguë N occurrences")
- Métadonnées : date d'import, modèle utilisé, indicateur si fallback positionnel a été déclenché

**Backend — `claude_code_mission_service.py`** :
- `_import_review_chunk` enrichi : collecte `by_rule` et `by_segment` dans la boucle d'application des patches.
- Écriture d'un `review_report.json` dans le `chunk_dir` à la fin de l'import — survit à l'archivage `_done/`.

**Backend — `formation_routes.py`** :
- Nouvelle route `GET /api/formation/<job>/content/<folder>/review-report` qui résout `folder_id → position → chunk_id` puis lit le `review_report.json` (cherche d'abord dans `review_queue/job_X/step_review/...`, fallback sur `_done/`).

**Frontend — `FormationPipeline.jsx`** :
- État `reportFolder` + bouton "Rapport" + composant `ReviewReportModal` (~180 lignes, dark theme cohérent).

### Fix solide review : résolution robuste segment_id obsolète + fallback positionnel

Bug observé : la révision a tourné, output.md valide (90 patches sur 18 segments), import "réussi" côté UI… mais en DB tous les segments sont `reviewed=0, dirty=0`. Aucun patch appliqué en réalité.

**Cause racine** : `_save_segment_db` utilise `INSERT OR REPLACE INTO content_generation_segments` → SQLite fait un DELETE+INSERT, donc le segment prend un nouvel id auto-incrémenté à chaque relance. Si l'utilisateur relance `content` entre la production de la review (par Claude Code) et son import (qui peut être différé via réutilisation `output.md`), les `segment_id` du JSON output deviennent **obsolètes** : ils référencent des segments qui n'existent plus en DB. L'`_import_review` legacy matchait par segment_id brut → tous les patches ignorés silencieusement (juste log warning).

**Cas réel job_8** : segment_ids du output.md = 89-106. Segment_ids actuels en DB après plusieurs relances content = 37-52. Aucune correspondance → 0 patch appliqué malgré 90 proposés.

**Fix — nouveau `_import_review_chunk` autonome** (ne délègue plus à `_import_review`) :
1. Construit un mapping `chunk_segment_id → index` depuis `chunk['segments']` au moment de l'import.
2. Pour chaque review : résout l'index dans le chunk via mapping, **fallback positionnel** si tous les ids du output sont absents du chunk (= content relancé entre temps) — la i-ème review correspond au i-ème segment, ordre stable `sub_idx ASC, passe ASC`.
3. Résout `(folder_id, sub_idx, passe)` → segment ACTUEL en DB via `JOIN content_generation_jobs cj ORDER BY cj.id DESC LIMIT 1` — gère le cas où plusieurs cg_jobs existent pour un même folder (situation anormale observée en DB), prend le plus récent.
4. Applique les patches avec `count == 1` strict (idem legacy).
5. Logue explicitement le mode `via_positional_fallback` dans le retour.

**Garde-fou de scope** : vérifie que `folder_id` du chunk appartient bien à la `platform_id` du job pipeline (rejette tout output.md malveillant ou mal scopé).

**Récupération du job_8 actuel** : re-cliquer "Exécuter avec Claude Code" sur la révision → réutilisation gratuite de `output.md` existant → `_import_review_chunk` détecte ids obsolètes → fallback positionnel → applique les 90 patches sur les segments actuels.

### Fix volume content chunked : prompt scratch complet + continuation loop

Bug observé : 1ère génération chunked complète rendait **58 731 mots** (3263/segment) au lieu des **90 000 ciblés** (5000/segment), soit 65% de la cible. Même problème qu'avait connu le mode API en avril (38k vs 90k) et qui avait été résolu côté API par 2 fixes que je n'avais pas répliqués sur le mode chunked.

**Cause #1** : `_build_content_chunk` envoyait un task.md ultra-léger (~30 lignes : "vise 4500-5500 mots"). Le mode API utilise `prompt-generation-tts-scratch.md` (2892 lignes par template) avec un bloc encadré **"VOLUME EXIGÉ — NON NÉGOCIABLE / MINIMUM 5000 mots"** répété 5 fois. Sans cette pression rhétorique, Claude Code traite la cible comme une suggestion et s'arrête à 3000 mots.

**Cause #2** : pas de continuation loop. Le mode API (`_generate_segment_text` ligne 277) refait 1-2 appels supplémentaires "tu as écrit X mots, continue, atteins 5000+" si la 1ère génération est sous le seuil. Mon mode chunked s'arrêtait au 1er rendu.

**Fix #1 — `_build_content_chunk`** : charge maintenant le vrai template via `_get_passe_prompts(from_scratch=True)` (le même que le mode API), fait les remplacements `{NOM_DU_TITRE_PROFESSIONNEL}` / `{NOM_DE_LA_SOUS_PARTIE}` / `{CONTENU_DU_MODULE}`. Pour passe 2/3, ajoute la consigne de continuité avec passes précédentes. task.md devient ~800 lignes (ce qu'envoyait déjà le mode API à Anthropic).

**Fix #2 — `_continue_content_until_volume`** : nouvelle fonction qui, après chaque chunk, vérifie le word_count. Si <4000 mots, crée un sous-dossier `_cont_N/` avec un task.md de continuation (input.md = 6000 derniers caractères du texte précédent), lance un subprocess `claude` dédié, concatène le résultat. Max 2 continuations. Sur 429 ou erreur : on garde l'état courant (no fail-fast, aligné mode API).

Conséquence sur le temps : si tous les chunks atteignent 5000+ au 1er coup, pas de surcoût. Si plusieurs chunks nécessitent 1 continuation : ~+30s/chunk affecté. Pire cas (2 continuations × 18 chunks) : ~+18 min/journée.

**Pour récupérer le job actuel** : les segments existants à 3263 mots/passe restent en DB. Pour les régénérer avec le nouveau prompt + continuation, il faut soit supprimer ces segments en DB et relancer, soit accepter le déficit et continuer. À discuter selon priorité.

### Fix finalize manquant en fin de mode chunked content

Bug observé après un premier run réussi : 18/18 segments en DB, mais l'UI affichait "Génération : 0/1 journées terminées", bouton "Reprendre" actif, bouton "Word" cliquable mais ne téléchargeait rien, et bandeau "1 mission(s) en attente d'import · content".

**Cause** : le mode chunked se terminait après avoir sauvegardé les 18 segments via `_save_segment_db`, mais il ne reproduisait pas les 3 dernières étapes que fait `run_content_generation` à la fin en mode API :
1. `_assemble_and_upload(folder_id, platform_id, cg_job_id)` — concatène les 18 segments en 1 texte, l'uploade sur Azure (= DOCX téléchargeable via le bouton Word).
2. `_update_job_db(cg_job_id, status="completed", total_words=N)` — marque le content_generation_job complet.
3. Archive du dossier `review_queue/job_X/step_content/` vers `_done/` (libère le bandeau d'alerte).

**Fix** : nouvelle fonction `_finalize_content_step(job_id, model)` qui fait ces 3 étapes pour chaque journée, idempotente (skip les cg_jobs déjà completed), n'archive que si tous les assemble_and_upload ont réussi.

**Récupération d'un job déjà chunked sans finalize** : cliquer "Exécuter avec Claude Code" → comme tous les segments sont déjà completed en DB, `_list_content_chunks` retourne 0 chunks, le code passe direct dans la branche `total == 0` qui appelle `_finalize_content_step` → finalize propre sans nouveau coût Anthropic.

### Throttle anti-rate-limit + retry 429 sur le mode chunked Claude Code

Premier test du mode chunked en local : 429 Anthropic dès le 2e chunk. Cause : le bootstrap Claude Code consomme à lui seul ~47k tokens d'input par invocation (chargement tools/MCP/skills), et le cache prompt n'est **pas réutilisé** entre subprocess séparés (chaque `claude -p` démarre une nouvelle `session_id`). Total ~92k input/chunk sur Haiku → dépasse le quota 50k/min dès la 2e exécution consécutive.

**Backend — `claude_code_mission_service.py`** :
- Nouvelle exception `_RateLimitError` levée par `_run_subprocess` quand le log contient `"api_error_status":429` ou équivalent.
- Boucle de retry dans `_execute_chunked` : tentative initiale + 2 retries avec backoff exponentiel (90s, 180s).
- Sleep configurable entre chunks via env `CC_CHUNK_DELAY_SEC` (défaut **75s**) — laisse le quota Anthropic se réinitialiser entre 2 invocations CLI.
- `progress.json` enrichi : `status` peut valoir `running` / `throttling` / `rate_limited` / `done` / `done_with_errors`, plus `sleep_until` (timestamp ISO) pour indiquer la fin de la pause.
- Sous eventlet+monkey_patch, `time.sleep` yield aux autres greenlets — pas de blocage du backend pendant les pauses.

**Frontend — `FormationPipeline.jsx`** :
- Affichage sous la barre de progression : "⏸ Pause anti-rate-limit (75s)…" pendant le sleep entre chunks, "⏳ Rate limit atteint — attente avant retry…" si 429 détecté.

**Conséquence sur le temps de génération** :
- content 1 journée = 18 chunks × (~80s exécution + 75s pause) ≈ **45 min/journée** (vs ~24 min sans throttle, mais avec 429 garantis).
- review 1 journée = 1 chunk = ~10s, pas de pause significative.

**Override possible** : `export CC_CHUNK_DELAY_SEC=0` pour désactiver le throttle (utile si upgrade tier Anthropic), `CC_MAX_429_RETRIES=N` pour ajuster le nombre de retries.

### Subprocess Claude Code chunked pour "Génération cours" + "Révision conformité"

Extension du mode subprocess CLI aux étapes 6 (content) et 6bis (review). Ces deux étapes ne tiennent pas en 1 seul appel CLI :
- **content** : ~90 000 mots de sortie par journée, dépasse la limite de 64k tokens output Sonnet.
- **review** : input volumineux (~117k tokens pour 1 journée), saturation sur plusieurs journées.

Solution : **boucle séquentielle de N appels `claude -p`**, 1 par chunk, avec orchestration côté backend.

**Backend — `backend/services/claude_code_mission_service.py`** :
- `execute_mission_locally()` devient un dispatcher : `_execute_single` pour global/daily/kb (legacy 1 mission), `_execute_chunked` pour content/review.
- `_run_subprocess(mission_dir, model, log_path, log_mode)` : helper extrait du flow legacy, lance `claude -p` sur 1 task.md, vérifie output.md.
- `_list_content_chunks(job)` : 18 chunks par journée (6 sous-parties × 3 passes), skippe ceux déjà `completed` en DB → idempotent / reprise après crash.
- `_list_review_chunks(job)` : 1 chunk par journée, skippe les journées dont tous les segments sont déjà `reviewed=1`.
- `_build_content_chunk` / `_build_review_chunk` : produisent task.md + input.md + rules.md par chunk. Pour content, injection des passes précédentes pour continuité narrative.
- `_import_content_chunk` : output.md = texte brut → `_save_segment_db` (réutilise le code existant). `_import_review_chunk` délègue à `_import_review` legacy.
- `_ensure_content_pipeline_structure(job)` : crée folders + `content_generation_jobs` en `idle` si absents (idempotent), pour ne pas dépendre d'un lancement préalable du mode API.
- `progress.json` écrit pendant la boucle (`{current, total, status, errors, current_chunk}`) → exposé via `list_pending_missions` pour l'UI.
- Pas de fail-fast : si un chunk échoue, on log et on continue les autres. Relancer "Exécuter" reprend les chunks ratés (skip par DB pour content, par `reviewed=1` pour review).

**Frontend — `frontend/src/pages/FormationPipeline.jsx`** :
- Flags : `CC_AUTO_EXEC_ENABLED = { global: true, daily: true, content: true, review: true, kb: false }`.
- `ClaudeCodeStepActions` affiche une **barre de progression chunked** sous le bouton (lit `pendingMission.progress`) : `"5/18 · day_1_sub_0_passe_2"` + indicateur d'erreurs si chunks échoués.
- Polling existant via `fetchPendingMissions` toutes les 4s — la mécanique de `_EXECUTION_STATE` (running/done/error) ne change pas, c'est `progress.json` qui informe l'UI du détail intra-greenlet.

**Estimations temps** :
- content 1 journée = 18 chunks × ~80 sec = ~24 min (équivalent au mode API).
- review 1 journée = ~10 sec. 4 journées = ~40 sec.

**Reste désactivé** : `kb` (~120-150k mots de sortie, nécessitera un chunking par compétence le jour où on l'active).

### Subprocess Claude Code activé pour étape "Programme journée"

Après validation en prod du subprocess sur "Programme global", extension à l'étape "Programmes journée". Tout l'outillage backend était déjà en place (`_build_daily_mission` + `_import_daily` dans `claude_code_mission_service.py`), seul le flag frontend `CC_AUTO_EXEC_ENABLED.daily` bloquait l'activation côté UI.

**Frontend** :
- `frontend/src/pages/FormationPipeline.jsx:460` : `daily: false → true`
- Le bouton "Exécuter avec Claude Code" du bloc "Programmes journée (local)" devient cliquable (modèle Haiku par défaut, Sonnet sélectionnable).
- `kb`, `content`, `review` restent désactivés — chunking dédié à concevoir avant activation (volume input/output trop grand pour un seul appel CLI).

**Comment tester** : valider un Programme global, descendre au bloc "Programmes journée (local)", cliquer "Exécuter avec Claude Code" → subprocess `claude -p ... --model haiku` → écriture `daily_programs` + statut `daily_ready` dans `formation_pipeline_jobs`.

## 2026-04-24

### Bouton "Exécuter avec Claude Code" — subprocess auto + import KB/content implémentés

Après validation utilisateur, implémentation du workflow "un clic et Claude Code travaille tout seul". Le workflow manuel export/import reste dispo en bouton secondaire pour les cas où on veut intervenir.

**Backend** :

- Nouvelle fonction `execute_mission_locally(job_id, step_key, model)` dans `claude_code_mission_service.py` :
  1. Export la mission (ou réutilise si déjà exportée)
  2. Lance `subprocess.run(['claude', '-p', prompt, '--model', <haiku|sonnet>, '--dangerously-skip-permissions'])` avec timeout 1h, `cwd=racine_projet`.
  3. Vérifie que `output.md` a été créé, sinon erreur claire.
  4. Appelle `import_mission_result` automatiquement pour finaliser dans la DB.
- Route `POST /api/formation/<job>/missions/<step_key>/execute` — spawn un greenlet eventlet, retourne **202** immédiatement. État stocké dans `_EXECUTION_STATE[(job_id, step_key)]` : `{status: 'running'|'done'|'error', model, error, result}`. Conflit 409 si une exécution est déjà en cours pour cette étape.
- `list_pending_missions` enrichi : remonte `execution_status` et `execution_error` en overlay sur chaque step_key (même si pas de fichiers `review_queue/` encore).
- Garde-fou `shutil.which('claude')` au démarrage de l'exécution : erreur claire si le binaire n'est pas trouvé ("Installe Claude Code CLI…").

**Imports `kb` et `content` désormais implémentés** :

- `_import_kb` : parse output.md (JSON array de compétences), DELETE l'ancienne KB du job, INSERT batch dans `formation_knowledge_base` avec tous les champs (`definition_pedagogique`, `contexte_terrain`, `etudes_de_cas`, `pieges_frequents`, `vocabulaire_metier`, `liens_connexes`), status `'completed'`, total_words calculé. Job passe en `status='kb_ready'` avec `kb_generated_via='claude_code_<model>'`.
- `_import_content` : parse output.md (`{days: [{day_number, segments: [{sub_part_index, passe, text}]}]}`), matche les journées aux `cours_folders` par position, upserte chaque segment via `_save_segment_db` (qui pose `dirty=1, reviewed=0, review_error=NULL`).
- Plus de `_import_not_implemented_v1`, plus de 501. Les 5 étapes (kb, global, daily, content, review) sont maintenant toutes importables bout-en-bout.

**Frontend** :

- Nouveau handler `handleExecuteMission({stepKey, model})` — POST sur `/missions/<step_key>/execute`, puis `fetchPendingMissions` pour refresh.
- Effet de polling continu toutes les 4s tant qu'au moins une mission a `execution_status='running'` — le polling s'arrête automatiquement quand tout est `done`/`error`/`idle`.
- `ClaudeCodeStepActions` refondu :
  - **Bouton principal** (gradient ambre) : *"Exécuter avec Claude Code"* / *"Claude Code travaille…"* pendant l'exécution.
  - **Messages d'état inline** : 🟡 en cours (avec estimation "quelques min à ~30 min") · 🟢 terminé et importé · 🔴 erreur avec message.
  - **Bouton secondaire** (petit, gris) : *"Exporter manuellement"* pour les cas où l'utilisateur veut intervenir avant que Claude Code touche quoi que ce soit.
  - Import manuel gardé dans un panneau qui n'apparaît que si `has_output` et pas en cours d'exécution.

**Sécurité / gating** :

- Route 403 si `LOCAL_DEV != 'true'` côté backend.
- `--dangerously-skip-permissions` passé à `claude` — documenté comme acceptable en contexte solo local, explicitement non utilisé en prod.
- Timeout 1h par exécution pour éviter des greenlets zombies en cas de freeze.

**Pour activer chez toi** :

1. `LOCAL_DEV=true` dans `backend/.env` (si pas déjà fait).
2. Redémarre le backend.
3. Vérifie que `which claude` retourne bien un chemin (OK sur ta machine : `/Users/amelle/.local/bin/claude`).
4. Sur `/formation-pipeline`, colonne droite, clique le gros bouton ambre **"Exécuter avec Claude Code"** de l'étape que tu veux. Attends 5-30 min selon l'étape et le modèle. L'UI passera automatiquement en vert "Terminé et importé" et l'étape côté API se mettra à jour avec le badge "Généré via Claude Code <model>".

### Fixes audit — 6 bugs corrigés avant que la feature soit considérée utilisable

Audit externe a identifié 6 bugs dans la chaîne review API + missions Claude Code ajoutées plus tôt dans la journée. Tous corrigés.

**Fix #1 — L'UI ne ment plus sur la conformité**

`_parse_patches_response` retourne désormais `(patches, parse_error)` au lieu d'un simple `patches=[]`. `run_content_review` distingue maintenant 3 cas :
- **JSON invalide** (parse_error) → écrit dans `review_error`, **pas** `reviewed=1`. UI affiche "Révision partielle — N en erreur reviewer" au lieu d'un faux vert.
- **Patches proposés mais tous rejetés** (ancres introuvables ou ambigus) → Claude a identifié des violations qu'il n'a pas su pointer → `review_error` (pas conforme). L'UI reste en état "à retenter".
- **Vraie conformité** (0 patch proposé) OU **audit partiel réussi** (≥1 patch appliqué) → `reviewed=1`, `review_error=NULL`. Seul ce cas affiche 🟢 "Conformité révisée".

**Fix #2 — L'import kb/content ne fait plus croire qu'il a marché**

- `_import_not_implemented_v1` lève maintenant `NotImplementedError` au lieu de `return {ok: false}`.
- Route `/missions/<step_key>/import` retourne **HTTP 501** avec `{error, not_implemented: true}` pour ces étapes.
- Frontend : `handleImportMission` vérifie `!resp.ok` ET affiche l'erreur (préfixe "Import non implémenté :") ; **ne supprime pas** la mission de `pendingMissions`, **ne ferme pas** la modale. L'utilisateur voit bien que rien n'a été importé.
- Archivage : déplacé après l'appel de l'importer → si `NotImplementedError` remontée, la mission reste en `review_queue/job_X/step_Y/` (pas déplacée vers `_done/`).

**Fix #3 — Plus de `dirty=1` abusif qui forcerait du TTS payant inutile**

Dans `_import_review` (import de résultat reviewer Claude Code) : `dirty=1` **uniquement** si au moins un patch a été appliqué sur ce segment. Les segments sans patches appliqués reçoivent juste `reviewed=1, review_error=NULL`. Économie de re-synthèses Fish Audio identiques.

**Fix #4 — La review Claude Code ne peut plus modifier des segments d'autres formations**

Garde-fou SQL à l'import : chaque `segment_id` renvoyé par Claude Code doit appartenir à un `content_generation_job` dont le folder est dans la **plateforme du job pipeline** en cours. Join explicite `content_generation_segments → content_generation_jobs → cours_folders → platform_id`. Segments hors scope → loggés (`⚠️ segment_id=X ignoré (inexistant ou hors plateforme Y)`) et **pas** touchés. Cohérent avec le scope plateforme du reste du code (launch_audio, etc.) mais sans fuite cross-job possible.

**Fix #5 — `generated_via` vraiment bout-en-bout**

- `get_job()` (`formation_pipeline_service.py:892`) SELECT maintenant `kb_generated_via`, `global_program_generated_via`, `daily_programs_generated_via` + les retourne dans le dict.
- `update_job(**kwargs)` a ces 3 colonnes dans son allowlist.
- **Tagging automatique côté flux API** :
  - `knowledge_base_service.py:680` → `update_job(status='kb_ready', kb_generated_via='api')`
  - `formation_pipeline_service.py:500` → programme global tagué `'api'`
  - `formation_pipeline_service.py:678` → programmes journée tagués `'api'`

Les badges "Généré via API" / "Claude Code Haiku" / "Claude Code Sonnet" dans `ClaudeCodeStepActions` s'afficheront maintenant correctement — auparavant toujours vides.

**Fix #6 — Cascade d'aval sur réimport global**

`_import_global` invalide maintenant les étapes aval : si on réimporte un programme global alors que les journées étaient validées, le réimport :
- Reset `global_program_validated = 0` (l'utilisateur doit relire et revalider)
- Efface `daily_programs = '[]'` et `daily_programs_generated_via = NULL`
- Reset `daily_programs_validated = 0`

La réponse d'import inclut `cascade_invalidated: [...]` pour indiquer ce qui a été effacé. L'utilisateur doit refaire l'étape 5 avant de pouvoir continuer.

`_import_daily` reset aussi `daily_programs_validated = 0` (plus léger — les segments de l'étape 6 restent tels quels, pas de reset automatique massif).

**Vérifications** : Python syntax OK sur 5 fichiers modifiés, JSX parse OK, backend rechargé (pid 84638). Route review répond 403 sans auth (attendue).

### 3ᵉ voie audio : gTTS (voix basique gratuite) dans l'étape 7

Ajout d'une **3ᵉ option de synthèse audio** dans l'étape 7 (pied commun, visible peu importe la colonne où le texte a été généré) : gTTS (Google Text-to-Speech, API web gratuite). Complète les 2 options existantes :

| Bouton | Coût | Qualité | Usage |
|---|---|---|---|
| **TTS test silence (gratuit)** | 0€ | MP3 silence 1s | Tester le flux sans rien écouter |
| **TTS voix basique (gratuit)** | 0€ | Voix gTTS naturelle | **NOUVEAU** — écouter le rendu réel sans payer Fish |
| **TTS payant** (Fish Audio) | ~9$/journée | Studio S2-Pro | Production finale |

**Backend** :

- `backend/requirements.txt` : `gTTS>=2.5.0`. Installé dans le venv local (confirmation : MP3 de 39 KB produit en ~2s pour une phrase test, header `fff3` = MPEG-1 Layer 3 valide).
- Nouveau service `backend/services/basic_tts_service.py` — fonction `convert_to_speech_basic(text, lang='fr')`. Découpe le texte en chunks de 4000 caractères (limite gTTS ~5000), appelle gTTS par chunk, concatène les MP3 en bytes (concat naïve fonctionne car gTTS produit des MP3 avec headers cohérents — même principe que le silence_1s embarqué en mode mock).
- `generate_audio_from_script(folder_id, ..., mock=False, basic_tts=False)` — nouveau paramètre `basic_tts`. Priorité : `mock` > `basic_tts` > Fish Audio par défaut. Pas de padding à la durée cible en mode gTTS (durée plus courte que les créneaux cours, acceptable en test). Fallback sur estimation de durée si pydub/ffmpeg échoue en mesure.
- `POST /api/formation/<job>/launch-audio` accepte désormais `basic_tts: true` en plus de `mock: true`. Les 2 sont mutuellement exclusifs (400 si les deux sont envoyés).
- Réponse enrichie : `basic_tts` dans le JSON de retour, suffix `(gTTS — voix basique gratuite)` dans le message.

**Frontend** :

- `handleLaunchAudio(mock, basicTts)` prend maintenant 2 booléens indépendants et envoie `{mock, basic_tts: basicTts}` au backend.
- **3 boutons** dans l'étape 7, disponibles sur les 2 états (pré-lancement et relance) :
  - 🟢 *Lancer le TTS (Fish Audio)* — vert success
  - 🟠 *TTS voix basique (gratuit)* — ghost ambre/orange, icône `graphic_eq`
  - ⚪ *TTS test silence (gratuit)* — neutral dashed
- Tooltips clairs sur chaque bouton : coût, qualité, cas d'usage.

**Pour tester** : depuis un job avec textes générés, cliquer "TTS voix basique (gratuit)". Le greenlet produit 7 MP3 via gTTS uploadés sur Azure. Écoute possible via la playlist habituelle.

### Refonte UI : vraie **2 colonnes parallèles alignées** (remplace le compromis "panneaux empilés")

Suppression du compromis précédent (panneau Claude Code ajouté sous chaque étape API) au profit d'un layout 2 colonnes alignées ligne par ligne, comme dans le wireframe initial du mémo.

**Technique** :

- Nouveau composant **`StepBlockCC`** — variant light de `StepBlock` avec styling ambre distinct (pour la colonne Claude Code). Même API props que `StepBlock` mais rendu plus compact (pas de badges "Terminé" dupliqués côté CC, label plus court).
- **Wrapper CSS grid** autour des étapes 3-6 (stepIndex 2-5) :
  - `gridTemplateColumns: DUAL_COLUMN_ENABLED ? '1fr 1fr' : '1fr'` — bascule automatique selon env.
  - `grid-auto-flow: row` (défaut) : chaque paire `<StepBlock>/<StepBlockCC>` se place automatiquement sur la même ligne.
  - **Séparateur vertical central** en `position: absolute`, trait sobre `rgba(255,255,255,0.12)` 1px (pas de gradient violet ni de halo — choix confirmé par l'utilisateur).
- **Labels de colonnes** au-dessus du grid : "⚙️ API Cloud · Anthropic" (bleu) et "💻 Claude Code local · forfait" (ambre).
- Les étapes 1-2 (Recherche RNCP, Téléchargement REAC) restent en **en-tête commun** au-dessus du split. L'étape 7 (TTS Fish Audio) reste en **pied commun** en-dessous. Cohérent avec le mémo.

**En dev (`DUAL_COLUMN_ENABLED = import.meta.env.DEV`)** : les 4 `<StepBlockCC>` conditionnels apparaissent en colonne droite, avec dropdown Haiku/Sonnet + bouton "Exporter la mission" + sous-panneau "Mission en attente" + bouton "Importer le résultat".

**En prod build** (`DUAL_COLUMN_ENABLED = false`) : `gridTemplateColumns: '1fr'` = stack vertical normal comme avant la refonte. Les `<StepBlockCC>` conditionnels ne sont jamais rendus. Zéro régression visible pour la prod.

**Alignement ligne par ligne** : si l'étape 3 API fait 400px de haut, son pendant Claude Code occupe la cell correspondante et reste collé en haut (`align-items: start` par défaut du grid). Les étapes 4 API et 4 CC commencent donc à la même grid-row, même si leurs contenus ont des hauteurs différentes.

### Phase 2 + 3 : UI Claude Code local + endpoints export/import missions

Refonte UI de `/formation-pipeline` pour matérialiser la dichotomie API / Claude Code local (Phase 2), et ajout des endpoints backend d'export/import de missions (Phase 3). Gating strict côté dev uniquement.

**Compromis UI retenu** : pas de 2 colonnes parfaitement parallèles côte à côte (qui aurait impliqué une refonte JSX massive avec risque élevé de casse). À la place, chaque étape coûteuse (Enrichissement KB, Programme global, Programmes journée, Génération cours, Révision 6bis) reçoit un **panneau Claude Code clairement distinct** en-dessous du contenu API existant, séparé par un trait ambre pointillé. Même intention visuelle que le wireframe, avec une structure plus robuste.

**Frontend** (`frontend/src/pages/FormationPipeline.jsx`) :

- Composant `StepDualLayout` (non utilisé en V1 mais en place pour une future refonte stricte 2 colonnes).
- Composant `ClaudeCodeStepActions` réutilisable : dropdown **Haiku/Sonnet** par étape (défauts Haiku pour KB/global/daily, Sonnet pour content/review), bouton "Exporter la mission", badge `Généré via <origine>`, sous-panneau "Mission en attente" avec bouton "Importer le résultat".
- Gating `DUAL_COLUMN_ENABLED = import.meta.env.DEV` — la colonne Claude Code n'apparaît qu'en mode Vite dev (`npm run dev`), invisible en build production.
- Nouveau composant `ClaudeCodeMissionModal` — affiche après clic "Exporter la mission" : chemin des fichiers, commande `claude --model <haiku|sonnet>` à copier, instruction à donner en session Claude Code, bouton "Importer le résultat" / "Plus tard".
- **Bandeau "N missions Claude Code en attente d'import"** en haut de la page quand des missions ont été exportées mais pas encore réimportées. Évite qu'une mission soit oubliée.
- State `pendingMissions` synchronisé via `GET /api/formation/<job>/missions/pending` au chargement et après chaque export/import.
- Handlers `handleExportMission({stepKey, model})` et `handleImportMission({stepKey})`.

**Backend** :

- Nouveau service `backend/services/claude_code_mission_service.py` — 350+ lignes. 5 builders d'export (un par stepKey : kb, global, daily, content, review) qui écrivent `task.md` + `input.md` + (optionnel) `rules.md` + `meta.json` dans `review_queue/job_<id>/step_<key>/`. 5 importers correspondants, avec stratégies variables :
  - `global` : output = markdown brut → stocké dans `formation_pipeline_jobs.global_program`, statut passe à `global_ready`, `global_program_generated_via='claude_code_<model>'`.
  - `daily` : output = JSON array → stocké dans `formation_pipeline_jobs.daily_programs`, statut `daily_ready`.
  - `review` : output = JSON `{reviews: [{segment_id, patches}]}` — applique les patches par match textuel unique (même logique que Phase 1), `reviewed=1` à la fin.
  - `kb` et `content` : **not implemented V1** — export fonctionne, import renvoie un message clair demandant de finaliser manuellement (parsers lourds à venir en V2).
- Archivage auto de chaque mission importée dans `review_queue/_done/<timestamp>-job<id>-<step>/` pour traçabilité.
- Nouvelles routes (toutes gardées par `_require_admin` + gating `LOCAL_DEV=true` sur env var backend) :
  - `POST /api/formation/<job>/missions/<step_key>/export` → 201 + JSON mission
  - `POST /api/formation/<job>/missions/<step_key>/import` → 200 + JSON résultat
  - `GET /api/formation/<job>/missions/pending` → 200 + dict missions en attente
- **Migration DB** (`backend/database/db.py`) : 3 colonnes `kb_generated_via`, `global_program_generated_via`, `daily_programs_generated_via` sur `formation_pipeline_jobs` (pattern idempotent ALTER TABLE). Valeurs : `'api'` / `'claude_code_haiku'` / `'claude_code_sonnet'`.
- **`.gitignore`** : `review_queue/` ajouté (missions éphémères, jamais commit).

**Gating production** :

- Backend : routes renvoient 403 si `LOCAL_DEV != 'true'` dans `os.getenv`. Pas défini par défaut → prod Azure désactivée automatiquement.
- Frontend : `DUAL_COLUMN_ENABLED = import.meta.env.DEV` — false en build production (Vite). Même sur une prod où LOCAL_DEV serait à true par erreur, le frontend build ne rendrait pas les panneaux.

**Pour activer en local** : ajouter `LOCAL_DEV=true` dans `backend/.env`, redémarrer le backend (watchmedo s'en charge), recharger la page dans le navigateur (Vite dev).

Reste **non implémenté (V2+)** : parsers complets pour KB et content (aujourd'hui import = marquer `generated_via` + laisser l'utilisateur finir manuellement), subprocess `claude` auto depuis backend (Phase 4 explicitement repoussée), refactor strict 2 colonnes parallèles alignées.

### Fix : distinguer échec reviewer ≠ conformité révisée (colonne `review_error`)

Bug de conception dans la V1 initiale : si l'appel Claude reviewer plantait sur un segment, je marquais `reviewed=1` quand même pour éviter que le polling frontend tourne à l'infini. Mais l'UI affichait alors *"Conformité révisée"* alors que le segment n'avait PAS été audité — mensonge critique.

**Fix appliqué** :

- **DB** : nouvelle colonne `review_error TEXT` sur `content_generation_segments`. Sémantique : NULL = pas d'erreur (jamais audité ou audité OK). Non-NULL = message d'erreur de la dernière tentative reviewer. Un segment en erreur reviewer reste `reviewed=0` — il n'est PAS marqué comme conforme.
- **`run_content_review`** : en cas d'exception Claude, écrit l'erreur dans `review_error` et laisse `reviewed=0`. En cas de succès (patches ou pas), met `reviewed=1 ET review_error=NULL` (le succès invalide toute ancienne erreur). Relancer la route sélectionne naturellement les segments `reviewed=0` → inclut les retry des erreurs.
- **`mark_segment_modified` et `_save_segment_db` et route d'édition UI** : reset `review_error=NULL` en plus de `reviewed=0 ET dirty=1` (un texte modifié invalide toute erreur reviewer précédente).
- **Route listing** : renvoie `segments_review_errors` en plus de `segments_reviewed`.
- **Frontend** : condition de fin de polling = `(reviewed + review_errors) >= completed`. **Trois états d'affichage distincts** :
  - 🟢 *"Conformité révisée (N segments)"* — tout audité, zéro erreur
  - 🟠 *"Révision partielle — X audités, **N en erreur reviewer** (relancer pour retry)"* — avec badge d'erreur bien visible
  - ⚪ Progression partielle ou en cours
- **Bouton** : texte/icône change en *"Retenter (N en erreur)"* quand des segments ont une `review_error`, permet retry sans passer par un autre endpoint.

La V1 ne ment plus sur la conformité : un segment non audité reste clairement signalé comme tel, et l'utilisateur peut retry.

### Phase 1 implémentée : reviewer conformité via API Claude sur étape 6

Scope strict Phase 1 tel que cadré : bouton "Réviser la conformité via API" sous chaque carte dossier-cours dans `/formation-pipeline` (étape 6). Pas de refonte double colonne, pas de workflow Claude Code, pas de subprocess, pas de pipeline auto.

**Backend** :

- **Migration DB** (`backend/database/db.py`) — colonnes `reviewed INTEGER DEFAULT 0` et `generated_via TEXT` ajoutées sur `content_generation_segments` (pattern idempotent try/except ALTER TABLE, cohérent avec les migrations existantes).
- **Helper central** `mark_segment_modified(job_id, sub_idx, passe)` dans `content_generation_service.py` qui remet `dirty=1 AND reviewed=0`. Règle critique : tout changement de `text_content` doit passer par là (ou inclure `dirty=1, reviewed=0` dans l'UPDATE, comme fait dans `_save_segment_db` via l'INSERT OR REPLACE et dans la route d'édition segment UI `hr_routes.py:2265`).
- **Fonction `run_content_review(folder_id, model=None)`** — boucle sur segments `status='completed' AND reviewed=0`, pour chacun : appel reviewer Claude Sonnet, parse JSON tolérant (extrait le premier `{...}`), application des patches par **match textuel unique** (`text.count(original) == 1` seulement), log des rejets (introuvable / ambigu). Max 5 patches par appel. Marque `reviewed=1` à la fin de chaque segment quel que soit le résultat — **y compris en cas d'échec d'appel Claude** — pour éviter que le polling frontend tourne à l'infini. Best-effort V1 : un segment en erreur garde son texte inchangé, à re-réviser il faut le modifier.
- **Extraction des règles** — `_load_review_rules()` lit `prompt-generation-tts-scratch.md`, extrait le bloc "CONTENU — RÈGLES ABSOLUES" → "décroche, les apprentissages ne passent pas" (les règles sont identiques dans les 3 passes, une seule extraction suffit). Mise en cache par mtime.
- **Route** `POST /api/formation/<job>/content/<folder>/review` — spawn un greenlet eventlet, retourne 202. Cohérent avec `launch-audio` et `resume-content`.
- **Route listing enrichie** `GET /api/formation/<job>/content` — ajoute `segments_reviewed` pour chaque folder, permet le polling de progression côté front.

**Frontend** (`frontend/src/pages/FormationPipeline.jsx`) :

- State `reviewingFolders: {[folderId]: true}` + `reviewError`.
- Handler `handleReviewFolder(folderId)` — POST sur la route, ajoute le folder au set. Polling dédié (3s) tant que le set n'est pas vide. Folder retiré automatiquement du set quand `segments_reviewed >= segments_completed` pour ce folder (effect déclenché à chaque refresh `contentFolders`).
- Bouton **"Réviser la conformité via API"** dans chaque carte folder de l'étape 6, à côté de "Voir" et "Word". Style `ghost` (violet discret). Désactivé si pas encore généré, pendant la révision, ou si tous les segments sont déjà révisés.
- **Affichage statut révision** sous le compteur de mots : *"Révision en cours — X/Y segments audités"* (ambre) → *"Conformité révisée (N segments)"* (vert) → *"X/Y segments déjà révisés"* (gris, partiel).

**Prompt reviewer** — consigne stricte : TU NE RÉÉCRIS PAS LE TEXTE, renvoie uniquement un JSON `{"patches": [...]}` avec `{original, replacement, rule_violated, reason}`. `original` trouvable verbatim, 3-40 mots. Si conforme → `{"patches": []}`. Contraintes "max N patches", "correction minimale", "pas de préférence stylistique personnelle".

Tests effectués : backend reload via watchmedo OK, route disponible (403 sans auth = attendu), JSX parse esbuild OK. Test complet sur un dossier réel à faire par l'utilisateur depuis l'UI (pas push, formation en cours).

### Décision architecture : pipeline formation **double colonne** (API cloud + Claude Code local)

Élargissement de la décision précédente (initialement "3 boutons pour l'étape 6 uniquement") vers une architecture UI unifiée : `/formation-pipeline` devient une **page à deux colonnes** séparées par une ligne stylée, avec les mêmes étapes dupliquées à gauche (API cloud) et à droite (Claude Code local).

**Choix actés** après cadrage croisé :

- **Un seul job partagé**, pas deux — artefacts communs, trace d'origine via colonne `generated_via` (`'api'`, `'claude_code_haiku'`, `'claude_code_sonnet'`) sur chaque table d'artefact.
- **Étapes 1-2 en en-tête commun** (recherche RNCP + téléchargement REAC — sans appel Claude), **étape 7 en pied commun** (TTS Fish Audio — pas dans la dichotomie API/Claude Code).
- **Mixage libre par étape** — ex : KB en Haiku local, programme global en API, cours en Sonnet local. Badge d'origine affiché dans les deux colonnes pour auditer.
- **Dropdown Haiku/Sonnet par étape** côté Claude Code (pas global). Défauts : Haiku pour KB/programme/journée, Sonnet pour génération cours et révision.
- **V1 export/import manuel** — pas de subprocess `claude` auto depuis le backend (trop fragile : permissions, logs interactifs, reprise après crash). Workflow : clic "Exporter mission" → `review_queue/<job>/<step>/{task.md, input.md, rules.md}` → commande `claude --model haiku` dans terminal → import résultat via second bouton.
- **Restriction prod** : colonne droite affichée uniquement si `LOCAL_DEV=true` est défini côté backend. Azure App Service garde l'UI en mono-colonne automatiquement. Pas de check `shutil.which('claude')` en V1 — le workflow export/import est indépendant de la présence locale du binaire (il le deviendra seulement si on implémente un jour le subprocess auto).
- **Format reviewer maintenu** : patches `{original, replacement, rule_violated, reason}` par match textuel unique, max 5 par appel.
- **Règle critique** : toute modification d'un segment (régénération, patch reviewer, édition manuelle) remet `reviewed=0` ET `dirty=1` via un helper DB centralisé `mark_segment_modified(segment_id)`.

**Phases d'implémentation** : (1) étape 6 + 6bis API/Claude Code, (2) refonte UI 2 colonnes, (3) étapes 3/4/5 côté Claude Code, (4) pipeline auto optionnelle.

Mémo renommé et élargi : `pipeline-review-3-boutons.md` → `pipeline-dual-api-et-claude-code.md`. Prochaine étape : wireframe détaillé à valider avant toute écriture de code.

### ~~Décision architecture : pipeline de révision conformité en 3 boutons~~ — **REMPLACÉE par la décision "double colonne" ci-dessus**

> ⚠️ Cette décision antérieure (même journée, 2026-04-24) a été élargie quelques heures plus tard après cadrage croisé UX : au lieu d'ajouter 3 boutons séquentiels à l'étape 6 uniquement, la bonne forme est **2 pipelines côte à côte** (API à gauche, Claude Code local à droite) couvrant toutes les étapes coûteuses. Le principe de révision conformité reste, mais il est intégré dans la colonne droite (étape 6bis) plutôt que matérialisé par un 3ᵉ bouton à part.
>
> **Ce qui est conservé de cette décision** : format reviewer `{original, replacement, rule_violated, reason}` par match textuel unique, max 5 patches par appel, flag DB `reviewed=1` pour idempotence, règle `mark_segment_modified` qui remet `reviewed=0` ET `dirty=1`, workflow export/import manuel (pas de subprocess).
>
> **Ce qui change** : le périmètre (étape 6 uniquement → toutes les étapes coûteuses), l'UX (3 boutons séquentiels → 2 colonnes parallèles), le nom du mémo (`pipeline-review-3-boutons.md` supprimé → `pipeline-dual-api-et-claude-code.md`).

### Prompt TTS scratch — nouvelle RÈGLE #27 "REGISTRE ORAL, PAS ÉCRIT"

Création d'une 7ᵉ règle de style oral (famille #21-#27) qui rappelle à Claude que le texte généré sera lu par Fish Audio S2-Pro, donc écouté et non lu. Pas de style soutenu/littéraire/ampoulé, mais registre **professionnel oral** — un formateur qui parle à sa classe, pas un rapport qu'on récite.

Contenu de la règle (structuré en sections) :

- **Niveau de langue** : courant + vocabulaire métier précis. Pas de synonymes précieux.
- **Syntaxe oralisée** : phrases courtes à moyennes, pas d'imbrications sur 3 niveaux, pas d'inversions stylistiques, pas de périphrases savantes.
- **Temps verbaux** : présent de narration + passé composé par défaut. **AUCUN passé simple**. Subjonctifs courants OK, subjonctifs rares ("qu'il eût été") proscrits.
- **Tournures à éviter** : "il convient de", "il sied de", "il y a lieu de", "force est de constater", "nonobstant", "d'aucuns diraient", "eu égard à", "aux fins de", "au titre de", "susmentionné".
- **Connecteurs naturels à utiliser** : "donc", "alors", "du coup", "c'est-à-dire", "en fait", "concrètement", "l'idée c'est que", "et puis", "par contre", "en gros".
- **Redondance contrôlée autorisée** : l'auditeur ne peut pas revenir en arrière → reformuler ou rappeler un concept-clé quelques paragraphes plus loin est une ressource, pas une faute.
- **Réserves — le registre reste professionnel** : pas de "ouais/truc/machin", argot, verlan, familiarité excessive ("les gars"), "quoi" en fin de phrase, "genre", "style", "bah/ben/euh".
- **Test mental** : *"Si je la dis à haute voix à un apprenant, est-ce que ça sonne naturel sans être relâché ?"* Rapport lu → reformuler en oral. Conversation de bistrot → resserrer en professionnel.

Ajout dupliqué dans les 3 passes (sandwich). Mise à jour cohérente des deux références "6 règles (#21-#26)" → "7 règles (#21-#27)" (titre de section + récap final).

### Prompt TTS scratch — interdits étoffés : "catastrophe naturelle", jurements par autre qu'Allah, superstitions

Trois ajouts dans les 3 passes (sandwich, `replace_all`) :

1. **RÈGLE #1, tiret "personnifient/divinisent"** — ajout de *"catastrophe naturelle"* avec justification inline (*attribue l'événement à la nature comme agent*). Liste complète maintenant : Mère nature, la roue tourne, à tes souhaits, dame chance, la providence, le sort en est jeté, c'est écrit, karma, les astres s'alignent, main du destin, catastrophe naturelle.
2. **RÈGLE #2, tiret "jurer par autre qu'Allah"** — étoffé avec liste de formules proscrites ("je te jure sur ma mère", "la vie de ma mère", "la tête de oim", "sur la tombe de", "par La Mecque", "croix de bois croix de fer", "je te jure", "je jure que", "juré craché", "parole d'honneur") + remplacements sans jurement ("je t'assure", "vraiment", "je peux te le confirmer", "c'est un fait avéré", "sincèrement").
3. **RÈGLE #2, tiret "expressions superstitieuses"** — étoffé avec 3 sous-listes à puce : porte-malheur prétendus (vendredi 13, chat noir, passer sous une échelle, miroir brisé, sel renversé, parapluie ouvert à l'intérieur), porte-bonheur prétendus (trèfle à 4 feuilles, toucher du bois, patte de lapin, fer à cheval, souffler les bougies pour que le vœu se réalise, étoile filante), formulations implicites (ça porte malheur/bonheur, je croise les doigts, conjurer le sort, ça nous portera chance).

### Prompt TTS scratch — RÈGLE #1 étendue aux expressions qui personnifient une force abstraite

Ajout dans la RÈGLE #1 (section "CONTENU 100% PROFESSIONNEL" — la partie où `shirk` est nommé) d'un nouveau tiret interdisant explicitement les expressions qui personnifient ou divinisent une force abstraite : **"Mère nature"**, **"la roue tourne"**, **"à tes souhaits" / "à vos souhaits"**, "dame chance", "la providence", "le sort en est jeté", "c'est écrit", "karma", "les astres s'alignent", "main du destin". Remplacements factuels fournis ("la nature", "les circonstances", "statistiquement", "dans ce cas de figure"). Cas spécifique de l'éternuement : ne rien dire plutôt que "à tes souhaits".

Appliqué dans les 3 passes (sandwich) via `replace_all`. Complète la RÈGLE #7 qui couvrait déjà "chance/destin/univers/énergie/karma" au niveau lexical, ici on cible les **tournures idiomatiques** qui personnifient.

### Prompt TTS scratch — retrait des repères "pause" des exemples de repères horaires autorisés

Décision éditoriale : le cours oral ne doit pas utiliser de repère horaire qui dépend de **la pause** ("après la pause", "avant la pause de midi"). Raison : le formateur parle naturellement en termes plus génériques ("plus tôt dans la journée", "tout à l'heure"). Les repères "ce matin", "cet après-midi", "tout à l'heure", "dans le bloc précédent" / "dans le prochain bloc" sont conservés (pas liés à la pause).

9 remplacements appliqués (3 zones × 3 passes) — stratégie sandwich oblige : le bloc "Tu peux donc / Ce qui est autorisé" apparaît en début, milieu et fin de chaque passe, et le fichier contient 3 passes. `"après la pause" / "avant la pause de midi"` → remplacés par `"plus tôt dans la journée"` partout.

### Épuration en-tête `prompt-generation-tts-scratch.md` — retrait des références au mode legacy

L'en-tête documentaire du prompt (lignes 1-13) référençait à plusieurs reprises `prompt-generation-tts-direct.md` (mode expansion legacy HR Dashboard) : *"Contrairement aux passes d'expansion…"*, *"IDENTIQUES à prompt-generation-tts-direct.md…"*. Remplacé par une description autonome qui dit uniquement **ce que le fichier fait**, sans comparaison avec l'autre mode.

Rappel : cet en-tête n'est **pas** envoyé à Claude — `_parse_passe_prompts_from_file` (`content_generation_service.py:78`) découpe le fichier sur `## PASSE N —` et n'envoie que le corps de chaque passe. Ce ménage est donc uniquement cosmétique (lisibilité humaine du fichier). Aucun changement de comportement côté génération.

### Fix : alignement mock — `content_generation_service.py:790` protégé comme `playlist_tts_service.py:700`

**Contexte** : le fix du 23 avril avait protégé `_measure_duration_ms` en mode mock uniquement dans `playlist_tts_service.generate_playlist_for_folder` (ligne 700). Mais la fonction **réellement** appelée par l'étape 7 de `/formation-pipeline` (`/launch-audio?mock=true`) est `content_generation_service.generate_audio_from_script` — qui conservait la ligne `final_duration = _measure_duration_ms(final_bytes) / 1000` sans garde mock (`content_generation_service.py:790`).

**Conséquence latente** (local OK grâce à ffmpeg Homebrew, Azure KO) : sur Azure App Service, le greenlet serait planté après l'upload du 1er bloc MP3 silence, laissant le job en `audio_error`. Plateforme + module tout de même créés (les updates sont synchrones dans `launch_audio` hors greenlet).

**Fix appliqué** (3 lignes, pas de push) :

```python
if mock:
    final_duration = 1.0
else:
    final_duration = _measure_duration_ms(final_bytes) / 1000
```

Le chemin mock complet (`launch-audio → generate_audio_from_script → _generate_silence_mp3 → upload → logger`) est maintenant **intégralement ffmpeg-free**, en accord avec le fix sur `generate_playlist_for_folder`.

### Note : analyse croisée avec Codex — validation du plan de fix TTS mock

L'utilisateur a soumis le bug TTS silencieux à Codex en parallèle pour cross-check. Codex a confirmé les 2 causes principales (`/launch-audio` qui répond 200 avant exécution du greenlet ; `_measure_duration_ms` qui appelle pydub/ffmpeg en mode mock). Codex a ajouté une suggestion de skip `_pad_audio_to_duration` en mock, mais vérification faite dans le code : **ce chemin n'est déjà pas emprunté en mock** (le mock saute directement à `_generate_silence_mp3(1)` sans padding). Le vrai bug résiduel est uniquement `_measure_duration_ms` ligne 700 après l'upload. Plan final validé et appliqué — voir entrée "Fix : TTS mock" ci-dessous.

**Leçon transverse** : un catch `except Exception` dans une boucle sans `sys.stdout.flush()` sur Azure App Service = debug quasi impossible (logs pas toujours flushés avant recyclage worker). Pattern à systématiser : flush explicite + `traceback.format_exc()` + status métier distinct de la réponse HTTP sur les flows async.

## 2026-04-23

### Fix : TTS mock — retrait de la dépendance pydub/ffmpeg résiduelle + debug greenlet

**Diagnostic** (après analyse croisée avec Codex) : le TTS mock ne produit aucun MP3 sur Azure malgré le fix `silence_1s.mp3` embarqué. Deux causes confirmées dans le code :

1. **`_measure_duration_ms` appelé même en mock** (`playlist_tts_service.py:700`) : après l'upload du blob, le code appelle `AudioSegment.from_mp3(final_bytes)` via `_measure_duration_ms()` — qui requiert ffmpeg, absent d'Azure App Service. Le greenlet plante donc au 1er fichier cours, après l'upload mais avant `generated_files.append(...)`. Résultat : les blobs apparaissent parfois à moitié, jamais complets.
2. **Route `/launch-audio` répond 200 avant exécution du greenlet** : `eventlet.spawn(...) → update_job("audio_launched") → return 200` est synchrone. DevTools voit 200, l'UI affiche "Synthèse lancée avec succès", mais le worker async peut planter après sans que le frontend le sache.

**Fixes appliqués** :

- `playlist_tts_service.py:700` : en `mock=True`, on hardcode `final_duration = 1.0` au lieu d'appeler `_measure_duration_ms`. Zéro dépendance pydub/ffmpeg dans tout le chemin mock maintenant (`_pad_audio_to_duration` était déjà skippé car le mock saute directement à `final_bytes = _generate_silence_mp3(1)`).
- `formation_routes.py:_run_audio` : premier `logger.info("🚀 SPAWN greenlet ...")` AVANT le `try`, avec `sys.stdout.flush()` explicite, pour prouver que le greenlet démarre vraiment. Plus `traceback.format_exc()` dans le catch pour voir la stack complète dans Log Stream Azure si une exception persiste.
- `formation_routes.py:_run_audio` : en cas d'exception, `update_job(job_id, status="audio_error", error_message=f"folder {folder_id}: {e}")`. L'UI peut désormais détecter l'échec au lieu de rester bloquée sur "audio_launched".

**Ce qui reste à faire (V2)** : transition explicite `audio_launched` → `audio_ready` quand TOUS les greenlets ont fini avec succès (nécessite coordination multi-greenlets). Pour V1, on garde `audio_launched` comme état "spawné" et on bascule seulement en `audio_error` si un greenlet plante — le succès se déduit de la présence des blobs.

### Feat : module formation persistant V1 — matérialisation de "1 RNCP = 1 module durable"

**Décision architecturale** : séparation explicite des 3 couches Factory (pipeline_jobs, process jetable) / Catalog (formation_modules, produit persistant) / Consumer (platform_config, instance de promo). Nouvelle table `formation_modules` (id, rncp_code, tp_name, version `{year}-v{n}`, status, source_pipeline_job_id UNIQUE, source_platform_id) créée dans `backend/database/db.py` avec migration rétroactive pour les jobs `audio_launched` / `completed` existants.

**Auto-création au `audio_launched`** : `INSERT OR IGNORE` dès que `launch_audio` passe le job en `audio_launched`, status `validated` par défaut. L'UNIQUE sur `source_pipeline_job_id` garantit l'idempotence des relances TTS.

**Modale "Nouvelle plateforme"** : le select liste désormais les modules validés (via `GET /api/hr/formation-modules`) plutôt que les formations pipeline internes. Création `{name, module_id}` → clone Azure serveur-side des blobs de la `source_platform_id`. Mode legacy `{name, formation_id}` conservé pour compat.

**UI** : bannière "Module créé et disponible" sur `/formation-pipeline` quand le job est `audio_launched`, bouton "Modules" dans le header HR Dashboard ouvrant la modale catalog, badge source_module_id sur les cartes plateforme.

**Point d'observation** : en fin de session, le TTS (mock ET payant) ne produit pas de MP3 sur Azure malgré `force_all=True` et le fix ffmpeg (`silence_1s.mp3` embarqué dans `backend/assets/`). Les requêtes `POST /api/formation/jobs/{id}/launch-audio` renvoient bien 200 mais le greenlet async échoue silencieusement. À diagnostiquer à la reprise (logs Azure App Service filtrés sur la fenêtre juste après le click).

**Références** : `memoire/04-solutions/module-formation-persistant-v1.md`.

### Fix : admin par plateforme — scoping complet des routes admin locales + `/api/internal/set-lock`

**Décision produit** : le HR Dashboard reste le cockpit central sur P1, mais chaque plateforme a désormais sa propre page admin accessible depuis un bouton « Admin » sur la carte plateforme du HR Dashboard. L'admin clique → nouvel onglet sur `{frontend_url}/login-admin?p={id}` → login → `/admin?p={id}` → session admin créée localement sur le backend de la bonne plateforme (isolation naturelle par App Service).

**Helper backend** `_get_platform_id()` dans `admin_routes.py` avec priorité explicite : header `X-Platform-Id` → query `?platform_id` ou `?p` → session → fallback 1 avec warning log. Ce helper remplace les `session.get("platform_id", 1)` cachés partout et surtout les appels `get_heure_debut_cours()` / `set_heure_debut_cours()` sans argument qui retombaient silencieusement sur `platform_id=1`.

**8 routes admin fixées** (scoping par `platform_id`) :
- `GET /api/admin/logs` — `WHERE platform_id=?` + `get_heure_debut_cours(platform_id)`
- `GET /api/admin/course-time` — `get_heure_debut_cours(platform_id)`
- `POST /api/admin/config_cours` — `set_heure_debut_cours(..., platform_id)`
- `GET /api/admin/export_excel` — `WHERE platform_id=?`
- `POST /api/admin/simulate-current-time` — écrit dans `state.simulated_time_offsets[platform_id]` (dict multi-tenant déjà en place dans `time_service.py:17`)
- `POST /api/admin/reset-simulation` — `state.simulated_time_offsets.pop(platform_id, None)`
- `POST /api/admin/force-logout-finished-users` — **critique** : `WHERE platform_id=? AND (depart IS NULL OR depart='')` + `socketio.emit(..., room=f"platform_{pid}")` (avant : broadcast global qui déconnectait TOUTES les plateformes)
- `POST /api/internal/set-lock` — refuse 400 si `platform_id` absent du body, `UPDATE platform_config ... WHERE id=?` (avant : hardcodé `WHERE id=1` → bug B2 du rapport d'audit)

**2 appelants de `set-lock` mis à jour** dans `hr_routes.py` (`toggle_lock` et `backup-and-unlock`) pour passer `platform_id` dans le body JSON, cohérent avec la nouvelle contrainte du endpoint.

**Frontend `LoginAdmin.jsx`** : lit `?p=` au mount et `setPlatformId(pParam)` avant toute requête (sinon sur un domaine Azure distinct le localStorage est vide → retour silencieux sur '1'). Passe le login à `apiFetch` pour que `X-Platform-Id` soit injecté automatiquement. Redirige vers `/admin?p={pid}` pour que l'URL survive un refresh en navigation privée.

**Frontend `Admin.jsx`** : lecture `?p=` au mount (même pattern que `Index.jsx`). Migration des 4 fetchs admin-critiques (`/api/admin/logs`, `/api/admin/export_excel`, `/api/admin/config_cours`, `/api/admin/force-logout-finished-users`) vers `apiFetch`. Les fetchs `/api/admin/upload-pdf` et `/api/admin/indexer-status` restent en fetch direct — ces routes utilisent des env vars globales et sont isolées par déploiement.

**Frontend `HRDashboard.jsx`** : bouton « Admin » (outline, icône `admin_panel_settings`) sur chaque carte plateforme active → `target="_blank"` vers `{frontend_url}/login-admin?p={id}`. Zero bouton admin visible côté élève (UX propre).

**Référence audit** : `AUDIT_MULTI_TENANT.md` (bugs B1, B2 du rapport) et `memoire/04-solutions/admin-par-plateforme.md`.

## 2026-04-22

### Discussion : accès admin par carte depuis le HR Dashboard

Clarification d'UX multi-tenant : privilégier un bouton **Admin** sur chaque carte plateforme du HR Dashboard P1 plutôt qu'un bouton admin visible sur l'interface apprenant. Le HR Dashboard reste le cockpit central admin-only ; chaque bouton ouvrirait l'admin local de la plateforme cible (`frontend_url/login-admin`) dans un nouvel onglet.

### Feat : prompts TTS refondus (règles #21-#26) + `/schedule-config` pointe sur scratch.md

Audit méthodique des dérives éditoriales observées dans les cours générés
par Claude (anecdotes fabriquées, métaphores musicales, "je vois que vous
êtes installés", "Imaginez un exemple. X.", énumérations mécaniques,
guillemets de discours direct inaudibles en TTS). Ajout de **6 règles
de style oral #21-#26** dans `prompt-generation-tts-direct.md` + stratégie
**sandwich** (rappel critique en tête / bloc détaillé au milieu / vérif
finale en fin) pour garantir que Claude n'oublie pas les interdictions
en cours de génération.

**Nouvelles règles** (appliquées aux 3 passes) :
- **#21** Fusion syntaxique : `"Imaginez qu'une personne…"` (pas
  `"Imaginez un exemple. Une personne…"`)
- **#22** Zéro guillemet de discours direct rapporté — TTS ne les
  prononce pas, discours indirect obligatoire
- **#23** Posture dialogale — 4 outils (questions rhétoriques,
  vérifications compréhension, invitations réflexion, métadiscours),
  1 interpellation tous les 150-250 mots
- **#24** Chutes isolées — zéro connecteur ouvreur (`"Et voilà…"`) ni
  méta-commentaire (`"Comme vous pouvez le voir…"`) sur les punchlines
- **#25** Format cours à distance — pas de visuel (`"je vois"`), pas
  de physique (`"notez"`), pas d'interaction retour (`"vous m'entendez ?"`).
  **Autorisés** : `"bonjour à tous"`, `"ce matin"`, `"après la pause"`.
- **#26** Pas d'énumérations mécaniques — tissage narratif avec 10
  patterns de transition + 5 commentaires de relief

**Paradigme clarifié** : ni présentiel physique, ni asynchrone, ni radio
journalistique. **Cours à distance / classe virtuelle en ligne** diffusé
à heure fixe sur la playlist horodatée (simulation de direct audio).

**Unification `/schedule-config` ↔ pipeline formation** : `hr_routes.py` +
`knowledge_base_service.py` pointent désormais sur
`prompt-generation-tts-scratch.md` (au lieu de `prompt-generation-tts-direct.md`)
pour que l'édition dans l'UI impacte directement la pipeline `from_scratch`.

**Synchronisation scratch.md ← direct.md** : script Python one-shot qui
réécrit scratch.md en copiant exactement les règles #1-#26 + tous les blocs
éditoriaux de direct.md, ne gardant de spécifique que les consignes de passe
(Fondation/Pratique/Maîtrise vs Expansion/Enrichissement). Taille scratch.md :
115 k chars, ~38 k par passe.

**Pas encore fait** : regénération des segments texte déjà en DB avec le
nouveau prompt (décision "option B : tout effacer + regénérer" prise en
début d'audit mais non exécutée pendant qu'on auditait).

### Meta : vault Obsidian complété après audit global

Ajout de deux notes wiki dans `/Users/amelle/Downloads/kit-deuxieme-cerveau/wiki/Intelligence/` : `audit-global-fiabilite-projet.md` (synthèse opérationnelle de l'audit global) et `risques-rate-limit-generation-tts.md` (risque Anthropic sur génération texte longue). Mise à jour de `parallelisme-enrichissement-kb.md` pour corriger l'ancien récit "3 workers par défaut" après l'incident 429 output-tokens, ajout d'un lien post-audit dans `pipeline-tts-19-mp3.md`, puis mise à jour de `wiki/index.md` et `wiki/log.md`.

### Meta : clarification méthode Karpathy appliquée au vault Obsidian

Clarification demandée sur la méthode Karpathy utilisée par la mémoire Obsidian : pattern **LLM Wiki / Second Brain** avec séparation `raw/` immuable, `wiki/` distillé et `CLAUDE.md` comme mode d'emploi, plus opérations `ingest`, `query`, `lint` et `save`.

### Audit : analyse globale du projet Le Socrate

**Livrables** : `AUDIT_PROJET_GLOBAL.md` + `memoire/02-problemes/audit-global-fiabilite-projet.md`.

Audit statique complet du repo après lecture du vault Obsidian : architecture backend/frontend, pipeline formation/TTS, SQLite, workflows Azure, tests, sécurité admin, hygiène de workspace. Vérifications locales : `python -m compileall backend` OK ; `npm run lint` KO (59 erreurs, 12 warnings) ; `npm run build` KO (Node 20.11.1 trop ancien pour Vite 7 + dépendance optionnelle Rollup manquante).

**Priorités identifiées** : fixer les bugs multi-tenant déjà documentés, remplacer l'admin hardcodé `admin/secret123`, brancher `content_generation_service.py` sur le client Anthropic anti-429 avec limite globale de concurrence, rendre la pipeline formation idempotente sur relance, nettoyer `.gitignore`/artefacts locaux, et séparer les tests Playwright local vs staging.

### Meta : consignes de session Codex alignées sur `.claude/claude.md`

Lecture confirmée de `.claude/claude.md` et auto-load de `wiki/index.md` du vault Obsidian. Les règles de transparence des lectures, de simplicité/changements chirurgicaux, de vérification pilotée par le but et de journalisation `CHANGELOG.md` sont prises comme contexte de travail pour la session Codex, dans la limite des outils disponibles ici.

### Audit : architecture multi-tenant (4 bugs + 5 incohérences + 6 optimisations)

**Livrable** : `AUDIT_MULTI_TENANT.md` à la racine.

**Scope** : backend (`db.py`, `main_app.py`, routes admin/hr/video/formation, `time_service`, sockets) + frontend (`api.js`), après lecture du vault (`wiki/Context/architecture-multi-tenant.md`, `memoire/02-problemes/hr-dashboard-heure-cours-figee-p2-p3.md`).

**Findings principaux** :
- **4 bugs confirmés** : admin local ignore `platform_id` (lit/écrit toujours P1), `/api/internal/set-lock` hardcodé `WHERE id=1`, `approve_deletion` ne supprime le blob Azure que pour P1, SocketIO `participants_update` leak cross-tenant sur `connect` (`broadcast=True`).
- **~6 risques latents** : defaults `platform_id=1` dans `time_service`, `auth_routes`, `main_app`, `video_routes`, `formation_routes`, `socketio_handlers` — écriture silencieuse sur P1 en cas d'oubli.
- **5 incohérences** : 3 chemins distincts d'extraction `platform_id`, 2 fonctions de création de plateforme (dont une seule crée les containers Azure), 84 appels `fetch` frontend qui contournent `apiFetch`, prompt TTS global partagé, `UPDATE platform_config SET playlist_mode = NULL` sans WHERE.
- **6 optimisations** : paralléliser `get_platforms` (8 appels Azure séquentiels), paralléliser `auto_schedule`, ajouter index DB sur `platform_id`, cacher `platform_config`, factoriser SAS URLs, middleware `@require_platform` pour tuer la famille de bugs defaults=1.

**Pas de code modifié** — diagnostic pur, prêt à traiter en 3 paquets (bug-fix / middleware / perf).

### Fix : principe cardinal "ne pas mentir" dans le prompt scratch + cache mtime

**Symptôme** : le contenu généré par la pipeline formation (`from_scratch=True`) contenait des **anecdotes personnelles fabriquées** au prétérit ("Il y a quelques années j'ai reçu un appel...", "J'ai entendu une voix..."), des noms d'entreprises inventés, des statistiques précises non sourcées, etc. Cours malhonnête + pollution du RAG.

**Root cause** : `prompt-generation-tts-scratch.md` ne contenait **pas** les règles anti-hallucination déjà présentes dans `prompt-generation-tts-direct.md` (#17 à #20). Pire, la passe 1 disait explicitement "L'accroche : une anecdote" — incitation active à inventer.

**Fix dans `prompt-generation-tts-scratch.md`** — ajouté aux 3 passes :
1. **Principe cardinal** en tête : "ne jamais mentir, sur aucun sujet". Test mental : "si un élève me demandait ma source, qu'est-ce que je répondrais ?". Si la réponse honnête est "je l'ai inventé" → reformuler en hypothétique ou supprimer.
2. **7 applications concrètes** (R1-R7) avec exemples ❌/✅ :
   - R1 : interdit de raconter un vécu au prétérit ("j'ai reçu/entendu/vu")
   - R2 : tournures hypothétiques obligatoires ("imaginez", "supposons", "prenons un cas fictif")
   - R3 : pas de noms d'entreprises/personnes fictifs qui sonnent vrai
   - R4 : pas de chiffres précis non sourcés (flouter ou supprimer)
   - R5 : pas d'études fictives (Harvard, Mehrabian, Ipsos)
   - R6 : pas de règles juridiques/fiscales/médicales présentées comme vérité — rediriger vers un professionnel
   - R7 : posture pédagogique assumée à l'oral ("l'important c'est la logique, pas le cas")
3. Ligne "L'accroche : une anecdote" remplacée par "une situation hypothétique annoncée comme telle, ou une question".

**Fix dans `content_generation_service.py`** — cache mtime :
- `_get_passe_prompts` vérifie maintenant `os.path.getmtime()` du fichier source avant de renvoyer le cache. Si le `.md` a été modifié depuis la dernière lecture, recharge automatiquement.
- Avant : il fallait redémarrer le backend pour que les modifs de prompt prennent effet (watchmedo ne watch que `*.py`). Maintenant : édition `.md` → prochain appel recharge automatiquement.

**Limite connue** : les segments déjà générés en DB avant ce fix contiennent du texte produit avec l'ancien prompt — potentiellement pollués par des mensonges inventés. À régénérer si utilisés pour le RAG ou le programme officiel.

### Feat : pipeline formation séparée en "génération cours" + "synthèse TTS" + PDF LaTeX

**Contexte** : l'étape 5 de `/formation-pipeline` ("Génération TTS") faisait en réalité uniquement la phase texte (18 appels Claude par journée). Le vrai TTS Fish Audio nécessitait d'aller cliquer manuellement dans le HR Dashboard par dossier. Confusant, et pas de validation du texte avant de déclencher la coûteuse synthèse Fish Audio.

**Changement UX** : 5 étapes → **7 étapes** dans le stepper :
- Étape 5 (renommée) : **"Génération des cours (texte)"** — identique techniquement à avant, juste labels corrigés.
- Étape 6 (nouvelle) : intégrée dans la 5, liste chaque journée générée avec boutons **"Voir"** (modal de relecture scrollable) et **"Télécharger PDF"** (programme officiel).
- Étape 7 (nouvelle) : **"Synthèse TTS Fish Audio"** — bouton qui lance `generate_audio_from_script` sur tous les dossiers en parallèle (un greenlet eventlet par journée).

**PDF LaTeX** — template XeLaTeX mutualisable :
- `backend/templates/formation_cours.tex.j2` : cover (TP, RNCP, journée), TOC auto, 6 sections par sous-partie, headers/footers, accent violet `#8B5CF6`, polyglossia français (césures correctes), police Palatino système macOS (pas de dep tlmgr).
- `backend/services/formation_pdf_service.py` : `build_course_pdf(job_id, folder_id) -> (bytes, filename)`. Assemble les segments DB, strip les tags Fish Audio (`[pause]`, `[warm]`) destinés au TTS, échappe caractères LaTeX spéciaux, compile en 2 passes XeLaTeX dans un tempdir.
- Délimiteurs Jinja2 customisés (`((*...*))`, `((( ... )))`) pour ne pas entrer en conflit avec la syntaxe LaTeX (`%`, `{`, `}`).

**Backend** — 3 nouvelles routes dans `backend/routes/formation_routes.py` :
- `GET /api/formation/<job>/content` — liste les dossiers cours avec progression texte (segments completed, mots, statut).
- `GET /api/formation/<job>/content/<folder>/pdf` — télécharge le PDF (Content-Disposition attachment).
- `GET /api/formation/<job>/content/<folder>/text` — texte brut assemblé pour la modal de relecture.
- `POST /api/formation/<job>/launch-audio` — vérifie que tous les textes sont `completed` puis spawn les greenlets Fish Audio. Passe le job en statut `audio_launched`.

**Nouveau statut** `audio_launched` (après `tts_launched` qui reste "textes lancés", pour compat jobs existants).

**Scope** : local uniquement pour l'instant (xelatex installé localement). Pour le prod Azure, il faudra ajouter LaTeX au startup App Service quand on en aura besoin — à reconsidérer plus tard. Les PDF servent à deux usages : programme officiel de formation (imprimable, présentable) et alimentation du RAG (texte extractible, structure claire pour le chunking).

### Refacto : client Anthropic partagé + protection 429 étendue au pipeline complet

**Contexte** : après le fix rate-limit pour la KB (ci-dessous), les autres étapes de la pipeline (programme global, découpage journée, refine) restaient vulnérables au même problème — le découpage est parallélisé en batches de 5 jours, donc sur un TP de 35 jours, **7 threads × 8000 tokens output simultanés** saturent le bucket 10 k/min de Haiku.

**Fix** — mutualisation dans un util partagé `backend/utils/anthropic_client.py` :
- Expose `AnthropicRateLimitError(wait_seconds)`, `parse_retry_after(resp)`, `post_message(messages, max_tokens, model)`.
- Lève `AnthropicRateLimitError` sur 429 avec délai parsé depuis `retry-after` HTTP puis les `anthropic-ratelimit-*-reset` ISO 8601, fallback 60 s.
- Cap auto `max_tokens=8000` pour Haiku (limite modèle).
- Logs unifiés (warning ⏳ pour 429, error ❌ pour autres HTTP).

**Branchements** :
- `services/knowledge_base_service.py` : `_claude_post` local réduit à un wrapper qui injecte le modèle. La logique dupliquée (`AnthropicRateLimitError`, `_parse_retry_after`) est supprimée (source unique dans l'util).
- `services/formation_pipeline_service.py` : idem pour `_claude_post`. Les 3 call-sites (`_generate_global_program_thread`, `_split_batch`, `refine_content`) passent de 3 retries aveugles (`sleep(10/15)`) à **5 retries avec sleep exact** sur 429 (et fallback inchangé pour les autres erreurs).

**Impact** : le découpage journée sur gros TP (≥ 10 jours) devient aussi fiable que l'enrichissement KB. Le programme global aussi.

### Fix : enrichissement KB échoue — rate-limit Anthropic 429 en cascade

**Symptôme** : `/formation-pipeline` → clic "Enrichissement KB" → job marqué `kb_ready` mais UI affiche "0 compétences enrichies / 0 mots". Logs backend : `429 rate_limit_error: 10,000 output tokens per minute` sur Haiku.

**Cause** : `KB_ENRICH_CONCURRENCY=3` × `max_tokens=8000` = 24 000 tokens output réservés simultanément, vs. limite 10 000/min du bucket output-tokens Haiku. Les retries utilisaient un `sleep(10)` aveugle qui ne laissait pas le bucket se remplir (les autres workers continuaient à tirer dessus). 3 retries épuisés → compétence marquée `error`.

**Fix** dans `backend/services/knowledge_base_service.py` :
1. `KB_ENRICH_CONCURRENCY` par défaut **1** (au lieu de 3) — un seul appel réserve déjà 80 % du bucket Haiku, toute parallélisation est contre-productive sur ce tier. Toujours configurable via env var pour les tiers plus hauts.
2. Nouvelle exception `AnthropicRateLimitError(wait_seconds)` — `_claude_post` lit `retry-after` HTTP puis les `anthropic-ratelimit-*-reset` ISO 8601, fallback 60s.
3. Retries passés de 3 à 5, avec sleep **exact** = `wait_seconds` sur 429 (au lieu de 10s aveugle). Les autres erreurs gardent le sleep 10s linéaire.

**Impact** : latence enrichissement ↑ (sérialisé), mais taux de succès ~100 % au lieu de ~30-60 %. Principe "1 RNCP = 1 module durable" : amorti sur toutes les promos, on privilégie la fiabilité sur la vitesse.

## 2026-04-21

### Meta : Karpathy behavioral guidelines inlinées dans `.claude/CLAUDE.md`

Les 4 règles comportementales Karpathy (`.claude/skills/Karpathy_skill.md`) étaient techniquement un "skill" invoqué à la demande — donc pas toujours actives. Inlinées dans `.claude/CLAUDE.md` pour qu'elles s'appliquent à **chaque** session, sans dépendre d'un match de description.

**4 règles** :
1. Réfléchir avant de coder (énoncer hypothèses, présenter interprétations multiples, pousser si simple existe).
2. Simplicité d'abord (minimum de code, pas de features non demandées, pas d'abstractions pour usage unique).
3. Changements chirurgicaux (chaque ligne modifiée trace à la demande, ne pas "améliorer" le code adjacent, matcher le style existant).
4. Exécution pilotée par le but (critères de succès vérifiables, plan bref pour tâches multi-étapes).

**Alternative rejetée** : hook SessionStart qui aurait lu le fichier skill externe — plus complexe (touche `settings.json`) pour un gain marginal vs. inline.

Le fichier skill original reste en place à `.claude/skills/Karpathy_skill.md` (pas supprimé) — au cas où on voudrait l'invoquer explicitement ailleurs.

### Fix : téléchargement REAC cassé — `PyPDF2` manquant dans le venv

**Symptôme** : bouton "Télécharger les sources" de `/formation-pipeline` en état `error`. `error_message` en DB = `REAC: No module named 'PyPDF2'`.

**Cause** : `PyPDF2==3.0.1` est bien déclaré dans `backend/requirements.txt` ligne 12, mais pas installé dans le venv actif à `./venv/` (racine projet). Probablement un `pip install -r` qui a sauté cette ligne, ou un venv recréé sans réinstaller toutes les deps.

**Fix** : `./venv/bin/pip install PyPDF2==3.0.1`. L'import `import PyPDF2` vit dans le corps de la fonction `download_reac_text()` (pas au top du module), donc un clic suffit pour retenter — pas besoin de redémarrer le backend.

**Note venv** : le venv est à la racine du projet (`./venv/`), pas dans `./backend/venv/` — à surveiller si jamais on ajoute un script de bootstrap.

### Meta : règle de transparence sur les `Read` (vault + fichiers non-évidents)

Ajout d'une règle dans `.claude/CLAUDE.md` : à chaque `Read` dans le vault Obsidian (toujours) ou d'un fichier du repo non mentionné par l'utilisateur (non-évident), Claude annonce en une ligne avant le tool call *où* il va et *pourquoi*.

**Format** : `→ je lis `wiki/Intelligence/<note>.md` (raison courte)`.

**Motivation** : l'utilisateur avait remarqué que les `Read` du vault se faisaient "en silence" — il ne se rendait pas compte des connaissances que Claude mobilisait pendant une réponse. Cette règle rétablit la visibilité sans alourdir la réponse (une ligne max, pas de paragraphe).

**Périmètre** :
- Toujours annoncer pour les Reads du vault `/Users/amelle/Downloads/kit-deuxieme-cerveau/...`
- Annoncer pour les Reads de fichiers repo non mentionnés par l'utilisateur
- Pas besoin d'annoncer si le fichier est explicitement dans la demande en cours (ex. "modifie `hr_routes.py`")

### Meta : capture zéro friction vers `raw/daily/` — fermeture du gap LeSocrate → vault

Jusqu'ici, la connaissance produite en session Claude Code (LeSocrate) n'arrivait dans le vault Obsidian que si l'utilisateur le demandait explicitement ou lançait une session vault pour `/save`. Ajout d'une règle dans `.claude/CLAUDE.md` qui matérialise la **capture zéro friction** du pattern Karpathy : sur signal de fin de session, Claude dépose automatiquement **deux fichiers** dans `raw/daily/` :

1. **Dump brut fidèle** — copie du transcript JSONL natif (`~/.claude/projects/.../*.jsonl`) vers `raw/daily/YYYY-MM-DD-<session-uuid>-session.jsonl`. Archive byte-à-byte immuable.
2. **Résumé insights lisible** — `raw/daily/YYYY-MM-DD-<session-uuid>-insights.md` avec frontmatter YAML (date, tags, type: daily, status: active, source: session-uuid) et 10-15 points clés max.

Au fil de l'eau, les triggers de proactivité déposent **en plus** un fichier ciblé `raw/daily/YYYY-MM-DD-<slug>.md` pour que `/ingest` retrouve le contexte même sans clôture formelle.

**Tranchage entre deux options discutées** :
- Option A (filtrer, ne mettre que l'important) — rejetée car biais de jugement à chaud + recrée la friction que `raw/` élimine.
- **Option B retenue** (tout + résumé) — `raw/` est immuable et pas cher, la distillation est le rôle de `/ingest`. Matche la philo Karpathy *"rien n'est trop brut pour raw/"*. Les deux fichiers donnent : archive complète (assurance) + résumé (accélérateur).

**Limite technique levée** : découverte du transcript JSONL natif de Claude Code dans `~/.claude/projects/-Users-amelle-Desktop-SocrateReprise-LeSocrate/<uuid>.jsonl` — copie byte-à-byte possible, pas besoin de reconstituer la conv de mémoire.

**Dossier `raw/daily/` créé** dans le vault (n'existait pas). Le tri `raw/ → wiki/` reste strictement réservé à `/ingest` lancé depuis une session Claude Code dans le dossier du vault — on ne rompt pas cette règle.

### Meta : audit archi Claude Code + auto-load vault + triggers naturels + dégraissage CLAUDE.md

Audit de la config Claude Code vs. l'archi cible **CLAUDE.md (identity) + Obsidian (how I think) + NotebookLM (research)** — variante sans Pinecone. Trois écarts identifiés et corrigés :

**1. Auto-load du vault au démarrage** — ajout d'une règle en tête de `.claude/CLAUDE.md` : "À chaque début de session, lire `/Users/amelle/Downloads/kit-deuxieme-cerveau/wiki/index.md` sans attendre de demande". Matérialise la flèche `identity · on start` du diagramme qui n'était que partielle (CLAUDE.md auto-loaded, mais pas le vault).

**2. Triggers langage naturel → skills vault** — tableau de mapping ajouté dans `.claude/CLAUDE.md`. L'utilisateur peut écrire "charge le contexte", "ingère", "save", "lint", "query X", "notebooklm" en langage naturel (sans slash) et Claude déclenche la skill correspondante via l'outil `Skill`. Annonce en une ligne avant invocation. Si ambigu (ex. "save" = sauver un fichier ?), demande avant.

**3. Dégraissage CLAUDE.md racine : 407 → 100 lignes** — respecte enfin le principe `rules · voice · < 200 lines` du diagramme. Stratégie : tout ce qui était déjà distillé dans le vault Obsidian a été remplacé par un pointeur vers la page wiki correspondante (pipeline TTS 19 MP3, infra Azure 3 comptes Blob, multi-tenant, stack, conventions). Gardés : principe RNCP = 1 module durable, commandes dev essentielles, 8 règles critiques ne jamais enfreindre, rappel multi-tenant, CI/CD, styling.

**Rationale** : un CLAUDE.md trop long noie l'essentiel (identity/voice/règles comportementales) sous les détails techniques qui vivent mieux dans le vault. L'archi 3 nodes repose sur une séparation claire : identity auto-loaded vs. reasoning/knowledge on-demand. Les 407 lignes précédentes dupliquaient ~80% du wiki Context+Intelligence.

**Non-traité (conscient)** :
- Route `NotebookLM → agent` inverse du skill `/notebooklm` (qui est export vault → NotebookLM). Le flow d'entrée (insights NotebookLM → Claude Code) passe en pratique par `raw/` du vault + `/ingest`, pas directement.
- Double système de mémoire `~/.claude/projects/…/memory/` + vault Obsidian : cohabitation assumée pour l'instant (auto-memory Claude Code = court terme cross-session, vault = durable thématique). Règle implicite mais pas encore arbitrée.

### Meta : mise en place du pattern LLM Wiki de Karpathy dans le vault Obsidian

Création d'une structure documentaire externe au repo pour capter la connaissance opérationnelle du projet, complémentaire au dossier `memoire/` (qui reste cible du mémoire académique).

**Emplacement** : `/Users/amelle/Documents/Obsidian Vault/`

**Structure créée** :
- `CLAUDE.md` à la racine du vault — schéma du pattern : 3 couches (raw immuable / wiki distillé / CLAUDE.md), opérations canoniques **Ingest / Query / Lint**, règles d'or pour le LLM.
- `raw/` — sources immuables (le LLM y lit, n'y écrit jamais).
- `wiki/index.md` — catalogue content-oriented avec catégories canoniques : **Sources / Entities / Concepts / Meta**.
- `wiki/log.md` — append-only, préfixe grep-able `## [YYYY-MM-DD] <type> | <titre>`.

**Itération** : première version posée avec catégorisation par thème projet et log sans préfixe structuré, puis patchée après relecture contre la spec Karpathy (ajout explicite Ingest/Query/Lint, préfixe log grep-able, catégories canoniques sources/entities/concepts, immutabilité de `raw/`).

**Pivot** : découverte du **Kit Deuxième Cerveau** (L'Atelier de l'Automatisation) qui fournit le même pattern mieux outillé — 6 slash commands prêts (`/prime`, `/ingest`, `/save`, `/query`, `/lint`, `/notebooklm`), frontmatter YAML obligatoire, structure wiki/Context-Intelligence-Resources-Daily. Migration vers ce kit (`~/Downloads/kit-deuxieme-cerveau/`) avec ancien vault `~/Documents/Obsidian Vault/` laissé dormant.

**Installation** :
- 6 skills copiés dans `~/.claude/commands/` (dossier créé à l'occasion).
- Bootstrap ingest du projet Le Socrate dans le wiki : 12 pages créées (3 Context + 7 Intelligence + 2 Resources), `wiki/index.md` et `wiki/log.md` mis à jour. Stratégie non-duplication — les 13 fichiers `memoire/` du repo restent la source canonique, le wiki synthétise + cross-référence.

**Pont vault ↔ repo** : `.claude/CLAUDE.md` du repo patché pour pointer Claude Code (sessions lancées dans LeSocrate) vers `/Users/amelle/Downloads/kit-deuxieme-cerveau/` comme source de contexte distillé. Instructions : lire `wiki/index.md` d'abord (panneau de direction), puis les pages `Context/` / `Intelligence/` / `Resources/` pertinentes avant refactor d'un service, touche d'infra Azure, ou arbitrage d'architecture. Ancienne section "Mon Projet / Profil Dev" (jamais implémentée en pratique) remplacée. Règle : maintenance du vault (`/ingest`, `/save`, `/lint`) reste réservée aux sessions Claude Code lancées dans le dossier du vault.

**Proactivité + détection fin de session** : `.claude/CLAUDE.md` étendu avec deux règles :
- **Proactivité** — dès qu'une décision d'archi, un problème diagnostiqué, une solution substantielle, un pattern durable, ou un insight non-trivial émerge en conversation, Claude écrit immédiatement (dans la foulée) vers `memoire/`, CHANGELOG, ou vault wiki. Règle du seuil "encore utile dans 3 mois ?" pour éviter le bruit. Vérification systématique d'un doublon existant avant création. Annonce transparente de chaque écriture.
- **Détection fin de session** — pas de trigger automatique, Claude surveille les signaux de clôture (explicite : "save" ; remerciement final : "merci" ; désengagement : "à demain" ; projection : "on reprendra sur X"). Signal explicite → exécute le save. Signal implicite → propose une synthèse + demande validation avant d'écrire.

Effet attendu : le vault et `memoire/` grandissent organiquement pendant les sessions sans attendre un "save" final, et le save final devient majoritairement une synthèse.

**Rationale** : séparer la capture brute (zéro friction) de la distillation (savoir réutilisable) pour accélérer la reprise de contexte en session et capitaliser les réponses aux queries comme nouvelles pages wiki.

## 2026-04-18

### Feature : parallélisme enrichissement KB (3 workers, speedup ×3)

Couche 1 d'enrichissement accélérée via `concurrent.futures.ThreadPoolExecutor` : **~12 min → ~4 min** pour 10 compétences Haiku.

**Backend** (`backend/services/knowledge_base_service.py`) :
- Import `concurrent.futures.ThreadPoolExecutor, as_completed`
- Constante `KB_ENRICH_CONCURRENCY` (env var, défaut `3`) — sweet spot entre gain de temps et rate-limits Anthropic Tier 1 (~50 000 tokens input/min)
- Lock global `_DB_WRITE_LOCK` protège `save_enriched_competence` et `mark_competence_error` contre les accès SQLite concurrents
- `_build_kb_thread` refactoré : boucle for séquentielle → pool de workers avec `as_completed`
- Fonction interne `_enrich_one(c)` encapsule appel Claude + save DB + error handling

**Checkpointing préservé** : chaque worker écrit indépendamment en DB, la logique résumable (skip des `completed`) fonctionne inchangée en cas de crash/restart.

**Documentation** : `memoire/04-solutions/parallelisme-enrichissement-kb.md` (audit complet : options, trade-offs, rate-limits, impact UX).

## 2026-04-17

### Fix : HR Dashboard — heure du cours P2/P3 figée après reload

**Symptôme rapporté** : dans le HR Dashboard, la modification de l'heure du cours pour P2 (Formation 2 TPCE) ou P3 (Formation 3 TPCE) affichait bien un message "enregistré", mais au refresh l'heure repassait à l'ancienne valeur (bloquée au 13 avril 2026).

**Cause** : asymétrie entre l'endpoint service-to-service POST et GET sur les backends distants :
- `POST /api/internal/config-cours` (`admin_routes.py:243-244`) lit `platform_id` depuis le body → écrit correctement la ligne `cours_config WHERE platform_id=2` sur la BDD locale de P2.
- `GET /api/internal/course-time` (`admin_routes.py:266`) appelait `get_heure_debut_cours()` **sans argument** → défaut `platform_id=1` → relisait une ligne stale dans la BDD locale de P2 (celle créée à l'init, jamais mise à jour depuis le Dashboard RH).

Résultat : l'écriture ciblait `platform_id=2` (OK), mais la lecture ramenait `platform_id=1` (ancienne valeur) → illusion que rien n'a été sauvegardé.

**Fix** :
- `backend/routes/hr_routes.py:1088` : l'appel proxy GET passe désormais `?platform_id={pid}` en query string.
- `backend/routes/admin_routes.py:259-277` : `internal_get_course_time()` lit `platform_id` depuis `request.args` et le passe à `get_heure_debut_cours(platform_id)`.

Symétrique à la correction POST déjà faite précédemment (cf. entrée du 293 du CHANGELOG).

### Clarification architecturale : 1 RNCP = 1 module durable

Principe fondamental du projet explicité et documenté :
- La pipeline formation est exécutée **une seule fois par RNCP**
- Elle crée **1 plateforme = 1 module audio durable** réutilisé pour toutes les promos du même TP
- `nb_days` est **intrinsèque au RNCP** (défini par le REAC officiel), pas un paramètre variable par promo
- Les promos = sessions utilisateurs distinctes dans `logs`, pas de régénération audio

**Conséquences sur les prochaines couches** :
- Optimisations "cache par RNCP" ou "scaling par promo" rejetées : réutilisation native, pas besoin d'ajouter de cache
- Couche 2 (alerte densité) : ratio calculé une fois à la création du pipeline, fixe par RNCP
- Couche 3 (squelette pédagogique) : construit selon `nb_days` intrinsèque, pas paramétrable par job
- Couche 4 (RAG Obsidian) : corpus par RNCP amorti sur toutes les promos, d'autant plus pertinent

**Fichiers modifiés** :
- `CLAUDE.md` : nouvelle section "Principe architectural fondamental" en tête de fichier
- `memoire/01-architecture/un-rncp-un-module-durable.md` (nouveau) : documentation complète du principe
- `memoire/README.md` : entrée ajoutée au méga-menu

### Fix : Couche 1 tolère les réponses JSON tronquées (max_tokens atteint)

Problème identifié lors du premier test réel (job 5, 10 compétences Haiku) :
- 2 compétences sur 10 ("Adopter un comportement orienté vers l'autre" et "Résolution de problème") marquées en erreur après 3 retries
- Logs : `Unterminated string starting at: line 96 column 23 (char 25096)`
- Cause : Haiku 4.5 plafonné à `max_tokens=8000` (~24000 caractères). Pour les compétences très riches pédagogiquement, Claude produit un JSON plus long que cette limite et la réponse est coupée mid-string → JSON invalide → parsing échoue → retry produit la même coupure → 3 échecs → status `error`.

**Fix** (`backend/services/knowledge_base_service.py`) :
- Nouvelle fonction `_repair_truncated_json()` qui :
  1. Parcourt le JSON char par char en suivant les strings/structures
  2. Trouve la dernière position "sûre" (après `,`, `}` ou `]` hors string)
  3. Tronque à cette position
  4. Ferme les `{` et `[` restés ouverts
- `_parse_json_response()` appelle la réparation en fallback si parsing normal échoue
- Résultat : une compétence tronquée devient **partiellement sauvée** (ex: 4 études de cas au lieu de 6 si la 5ème coupe au milieu) plutôt que complètement perdue

**Impact** : les 2 compétences en erreur peuvent être relancées via "Relancer" (logique résumable) et sortiront désormais avec du contenu valide même si tronqué.

### Fix : Couche 1 respecte les règles éditoriales TTS

Après identification d'un oubli : les règles éditoriales (religion, alcool, fêtes, paris, manipulation, hallucination, règles anti-inventions — 20 règles non négociables) qui encadrent la génération TTS doivent aussi s'appliquer à la Couche 1 d'enrichissement puisque son contenu devient la source primaire du cours audio.

- `backend/services/knowledge_base_service.py` : nouvelle fonction `_load_editorial_rules()` qui charge dynamiquement la section "CONTENU — RÈGLES ABSOLUES" + "HALLUCINATION" du fichier `prompt-generation-tts-direct.md` (cache invalidé par mtime).
- Les 2 prompts d'enrichissement (`_EXTRACT_COMPETENCES_PROMPT`, `_ENRICH_COMPETENCE_PROMPT`) incluent désormais un placeholder `{EDITORIAL_RULES}` injecté à chaque appel.
- Points d'attention ajoutés explicitement : études de cas fictives doivent être annoncées comme telles, vocabulaire métier strictement factuel, pièges décrits pour être évités (pas maîtrisés), contexte terrain 100% professionnel.

**Une seule source de vérité** : éditer les règles dans `/schedule-config` (via `POST /api/hr/tts-prompt`) propage automatiquement à la Couche 1.

### Feature : Couche 1 — Enrichissement REAC → Knowledge Base

Implémentation de la première couche de l'architecture qualité programme (cf. `memoire/01-architecture/architecture-4-couches-qualite-programme.md`).

**Objectif** : faire passer la matière source exploitable par Claude de ~15k mots (REAC brut) à ~120-150k mots enrichis, pour réduire drastiquement le ratio de dilution sur les formations longues (14 jours → ratio 43:1 → 4.3:1).

**Backend** :
- `backend/database/db.py` : nouvelle table `formation_knowledge_base` (migration idempotente) — 1 ligne par compétence avec définition pédagogique, études de cas, pièges, vocabulaire métier, contexte terrain, liens connexes. Flag `dirty` + `UNIQUE(job_id, competence_index)` pour checkpointing.
- `backend/services/knowledge_base_service.py` (nouveau) : orchestration complète. 2 étapes Claude — `extract_competences` (1 appel, extraction structurée depuis REAC) puis `enrich_competence` (1 appel par compétence, enrichissement dense). Séquentiel pour éviter rate-limit Anthropic. Retries 3× par appel. Fonction `build_kb_context` assemble un contexte structuré pour injection dans le prompt programme global.
- `backend/routes/formation_routes.py` : 2 nouvelles routes admin — `POST /api/formation/<id>/enrich-reac` (lance l'enrichissement, accepte `model` body pour Sonnet/Haiku) et `GET /api/formation/<id>/kb` (retourne entrées + stats).
- `backend/services/formation_pipeline_service.py` : `_generate_global_program_thread` injecte désormais la KB enrichie **en source primaire** quand elle existe (REAC brut en secondaire). Fallback REAC brut si KB absente (rétro-compatibilité).

**Frontend** :
- `frontend/src/pages/FormationPipeline.jsx` : nouveau `StepBlock` "Enrichissement Knowledge Base" inséré à stepIndex=2 (décalage des suivants : Programme global 2→3, Journées 3→4, TTS 4→5). Barre de progression live pendant `kb_building`, stats détaillées en `kb_ready`, expandable listant chaque compétence avec statut individuel. Boutons Relancer Sonnet/Haiku. `statusToStep` mis à jour pour `kb_building` / `kb_ready`. Polling étendu aux statuts KB.

**Nouveaux statuts job** : `kb_building`, `kb_ready`.

**Coût estimé** : ~$0.50-1 supplémentaire par formation (Claude Sonnet 4), négligeable vs coût TTS Fish Audio (~$5-15).

**Documentation** : `memoire/04-solutions/couche-1-enrichissement-reac.md` (structure type avec impact attendu sur ratio dilution).

### Feature : dossier `memoire/` pour consolidation des réflexions (mémoire académique)

Création du dossier `memoire/` à la racine du projet, destiné à consolider les réflexions, décisions techniques et diagnostics pour la rédaction du mémoire académique de fin d'année.

**Structure** :
- `memoire/README.md` — méga-menu navigable
- `memoire/01-architecture/` — décisions structurantes
- `memoire/02-problemes/` — problèmes rencontrés et diagnostics
- `memoire/03-decisions/` — arbitrages techniques
- `memoire/04-solutions/` — solutions techniques documentées (à venir)

**Fichiers initiaux créés** (consolidation des réflexions des sessions précédentes) :
- `01-architecture/pipeline-formation-vue-ensemble.md`
- `01-architecture/multi-tenant-plateforme-par-pipeline.md`
- `01-architecture/architecture-4-couches-qualite-programme.md`
- `02-problemes/rc-rome-indisponibles.md`
- `02-problemes/ratio-dilution-reac.md`
- `03-decisions/audit-rag-sur-reac.md`

**Instruction permanente ajoutée** dans `.claude/CLAUDE.md` : à chaque réflexion/décision/audit non-trivial, un fichier est ajouté à `memoire/` en suivant la structure type (Contexte → Problème → Options → Décision → Rationale → Références code → Leçons).

**Distinction CHANGELOG vs memoire/** : le CHANGELOG est chronologique et factuel ("quoi a changé"), le dossier `memoire/` est thématique et analytique ("pourquoi, comment, qu'a-t-on appris").

### Décision : Couche 1 (enrichissement REAC → knowledge base) prochaine étape

Architecture qualité programme formation définie en 4 couches (cf. `memoire/01-architecture/architecture-4-couches-qualite-programme.md`) :
- Couche 1 — Enrichissement structuré du REAC (priorité, à implémenter)
- Couche 2 — Alerte densité UI
- Couche 3 — Squelette pédagogique imposé (Bloom)
- Couche 4 — RAG externe Obsidian (optionnel, si insuffisant)

Justification : le ratio de dilution atteint 43:1 sur une formation 14 jours (15k mots REAC → 644k mots générés). Enrichir la source à 120-150k mots avant génération fait chuter le ratio effectif dans la zone sûre.

### Fix : bouton "Re-télécharger" REAC débloqué depuis le statut `reac_ready`

- `backend/routes/formation_routes.py` : route `POST /api/formation/<id>/fetch-reac` accepte maintenant les statuts `init`, `error` **et `reac_ready`** (avant : 400 BAD REQUEST quand on cliquait re-télécharger).
- Raison : le bouton "Re-télécharger" n'avait aucun effet utile — seul `init`/`error` étaient autorisés, alors que le cas courant (tenter à nouveau après succès partiel REAC-only, RC/ROME vides) est `reac_ready`.

### Clarification : RC et ROME sont optionnels par design

Le pipeline télécharge REAC + RC + ROME en parallèle via 3 threads. Seul REAC est obligatoire :
- RC (`download_rc_text`) : regex sur page France Compétences, retourne `""` silencieusement si aucun pattern URL ne matche (RC public inconsistant selon RNCP)
- ROME (`fetch_rome_data`) : nécessite `FRANCE_TRAVAIL_CLIENT_ID` + `FRANCE_TRAVAIL_CLIENT_SECRET` pour API officielle, fallback scraping candidat.francetravail.fr souvent bloqué
- Job passe quand même en `reac_ready` si seul REAC réussit → RC/ROME restent gris dans l'UI

### Décision : RC et ROME retirés de l'UI Pipeline Formation

Après investigation sur RNCP 35304 (TP CRCD) :
- RC inexistant publiquement sur France Compétences pour ce titre
- ROME D1408 / M1401 : ancienne URL `/metierform/accueil?codeRome=...` retourne 404, nouvelle URL `metierscope/fiche-metier/{code}` est une SPA JS non scrapable en HTTP brut

**Décision** : le REAC (95k caractères, toutes compétences + savoirs associés détaillés) est suffisant pour que Claude génère le programme de formation. RC/ROME n'apporteraient qu'un gain marginal (critères d'évaluation / contexte métier) insuffisant pour justifier le coût maintenance.

**Changements UI** (`frontend/src/pages/FormationPipeline.jsx`) :
- Badges RC et ROME supprimés de l'étape "Téléchargement REAC"
- Seul le badge REAC reste affiché
- Texte descriptif mis à jour ("Télécharge le REAC depuis France Compétences" au lieu de "REAC + RC + ROME")
- Backend inchangé : `fetch_rome_data` et `download_rc_text` continuent de s'exécuter en silence au cas où certains RNCP futurs les exposeraient proprement (no-op si vides)

**Objectif long terme** : automatisation complète du pipeline (aucune intervention humaine). L'upload manuel RC/ROME a été envisagé puis rejeté car incompatible avec cet objectif.

## 2026-04-16

### Feature : Pipeline formation automatisé (RNCP → TTS)

Pipeline end-to-end permettant de créer une formation complète depuis un code RNCP.

**Backend :**
- `backend/services/formation_pipeline_service.py` (nouveau) :
  - `search_rncp(query)` : recherche des titres RNCP sur France Compétences par scraping HTML
  - `download_reac_text(rncp_code)` : télécharge le PDF REAC depuis France Compétences et en extrait le texte (PyPDF2)
  - `launch_global_program_generation(job_id)` : génère un programme de formation structuré (blocs, modules, contenu théorique) depuis le REAC via Claude Sonnet 4
  - `launch_daily_split(job_id)` : découpe le programme global en N journées (÷7h/jour) avec exactement 6 sous-parties chacune, JSON avec `module_content` par sous-partie
  - `launch_tts_for_all_days(job_id, platform_id)` : crée les dossiers cours et lance la génération TTS from-scratch pour chaque journée
  - CRUD DB : `create_job`, `update_job`, `get_job`, `list_jobs` pour la table `formation_pipeline_jobs`
- `backend/routes/formation_routes.py` (nouveau) : 10 routes admin-protégées (`search-rncp`, `init`, `fetch-reac`, `generate-global`, `validate-global`, `split-daily`, `validate-daily`, `launch-tts`, statut, liste)
- `backend/database/db.py` : table `formation_pipeline_jobs` + migration colonnes `from_scratch` et `module_contents` dans `content_generation_jobs`
- `backend/main_app.py` : enregistrement du blueprint `formation_bp`
- `backend/services/content_generation_service.py` : support mode `from_scratch` avec `sub_parts_override` et `module_contents` — 3 passes indépendantes (Fondation / Pratique / Maîtrise) sur le même `{CONTENU_DU_MODULE}`
- `prompt-generation-tts-scratch.md` (nouveau à la racine) : prompts des 3 passes from-scratch avec règles Fish Audio S2-Pro intégrées

**Frontend :**
- `frontend/src/pages/FormationPipeline.jsx` (nouveau) : page stepper 5 étapes
  - Étape 1 : recherche RNCP + sélection dans les résultats + saisie durée (affiche le nb de journées calculé)
  - Étape 2 : téléchargement REAC avec polling statut
  - Étape 3 : programme global éditable (textarea toggle preview/édition)
  - Étape 4 : programmes journée éditables par jour (JSON editor per-day)
  - Étape 5 : lancement TTS avec confirmation du nombre de dossiers à créer
  - Polling 3s sur les statuts en cours (`reac_fetching`, `global_generating`, `daily_splitting`)
- `frontend/src/App.jsx` : route `/formation-pipeline` protégée par `ProtectedAdminRoute`

**Statuts pipeline :** `init → reac_fetching → reac_ready → global_generating → global_ready → global_validated → daily_splitting → daily_ready → daily_validated → tts_launched`

## 2026-04-14

### Fix : Chargement instantané de la forme d'onde dans l'éditeur audio

- **Backend** `hr_routes.py` — nouveau endpoint `GET /audio-url/<filename>` qui génère une SAS URL Azure valide 1h pour le blob MP3, au lieu de le proxifier intégralement
- **Frontend** `AudioEditor.jsx` — WaveSurfer reçoit directement la SAS URL : stream depuis le CDN Azure avec range requests natifs → chargement quasi-instantané au lieu de 15 secondes
- L'ancien endpoint `/audio-stream/<filename>` est conservé en fallback
- Après cut/replace-confirm, une nouvelle SAS URL est demandée avant le rechargement de la forme d'onde (le blob Azure ayant changé, la SAS précédente pointerait vers un cache potentiellement périmé)

### Feature : Éditeur audio (couper / remplacer une région)

- **Backend** `hr_routes.py` — 4 nouveaux endpoints :
  - `GET /audio-stream/<filename>` : proxy Azure → frontend pour WaveSurfer
  - `POST /audio/<filename>/cut` : coupe une région `[start_ms, end_ms]` via pydub, upload Azure (irréversible)
  - `POST /audio/<filename>/replace-preview` : génère TTS fish.audio pour un texte, stocke en mémoire, retourne base64 + preview_id
  - `POST /audio/<filename>/replace-confirm` : splice le preview TTS dans l'audio original via pydub, upload Azure (irréversible)
- **Frontend** `AudioEditor.jsx` (nouveau composant) :
  - WaveSurfer.js v7 avec plugin Regions — sélection par drag sur la forme d'onde
  - Mode **Couper** : sélectionner → confirmer → les morceaux se rejoignent
  - Mode **Remplacer** : sélectionner → écrire le nouveau texte → prévisualiser la voix TTS → confirmer l'intégration
  - Prévisualisation du TTS jouée directement dans le browser avant confirmation
  - Rechargement automatique de la forme d'onde après modification
- **CoursFolders.jsx** : bouton ✂️ sur chaque fichier audio généré dans la liste "Audios générés"
- `wavesurfer.js` v7.12.6 installé dans les dépendances frontend

### Feature : Régénération audio sélective depuis le script TTS modifié

- **DB** : colonne `dirty INTEGER DEFAULT 0` ajoutée à `content_generation_segments` (migration automatique)
- **PATCH segment** : marque maintenant `dirty = 1` à chaque modification de texte
- **Service** `content_generation_service.py` :
  - `generate_audio_from_script(folder_id, on_progress, force_all)` : assemble les 18 segments → découpe en 7 blocs proportionnels → régénère TTS uniquement pour les blocs dont au moins un segment est `dirty` → marque `dirty = 0` après génération réussie
  - `get_script_dirty_blocs(folder_id)` : calcule combien de blocs seraient régénérés (pour affichage dans le bouton)
- **Route** `POST generate-playlist` : si un script TTS complété existe, utilise `generate_audio_from_script` au lieu de la reformulation Claude. Sinon pipeline classique.
- **Route** `GET /content-job/dirty-blocs` : expose le comptage dirty au frontend
- **Frontend** : bouton "Générer les 7 cours MP3" affiche dynamiquement "Régénérer X/7 blocs modifiés" quand des segments ont été édités, ou "Générer les 7 cours MP3 (script)" si le script existe sans modification

### Feature : Modes de test pour la génération de contenu (mock / mini / seed)

- **`seed_test_content.py`** (nouveau script à la racine) : insère 18 segments factices directement en DB pour un `folder_id` donné — 0€, instantané, idéal pour tester la modale/édition
- **Mode `mock`** dans `run_content_generation` : génère du texte factice structuré (~220 mots/segment) avec `time.sleep(0.8)` pour simuler le délai, sans aucun appel Claude — teste le polling, le checkpointing, l'assemblage, l'upload Azure
- **Mode `mini`** : génère 1 seule sous-partie × 1 seule passe avec max_tokens 300 via le vrai Claude (~0.02€) — valide l'intégration Claude sans coût significatif, pas d'upload Azure
- **Frontend** : boutons "Mock (0€)" et "Mini (~0.02€)" visibles uniquement en `import.meta.env.DEV` sous les boutons de génération normale
- **Route** `POST /start` accepte maintenant `{"mode": "normal"|"mock"|"mini"}` dans le body

### Feature : Visionneuse de script TTS avec sommaire latéral et édition par passe

- **Frontend** `CoursFolders.jsx` : redesign complet de la modale "Script TTS généré"
  - Layout 2 colonnes : sidebar sommaire (260px) + panneau contenu (flex-1)
  - Sidebar : liste cliquable des 6 sous-parties avec badge numéroté, nom et nombre de mots — navigation instantanée entre sous-parties
  - Panneau droit : affiche les 3 passes de la sous-partie sélectionnée, chacune avec bouton "Modifier" → textarea inline → "Sauvegarder" / "Annuler"
  - Réinitialisation de l'état d'édition à chaque changement de sous-partie ou fermeture de la modale
- **Backend** `hr_routes.py` : nouvelle route `PATCH /api/hr/cours-folders/<id>/content-job/segment`
  - Sauvegarde le texte modifié dans `content_generation_segments`
  - Recalcule `word_count` du segment et `total_words` du job depuis les segments complétés
  - Retourne `new_word_count` et `new_total_words` pour mise à jour optimiste du frontend

## 2026-04-13

### Feature : Pipeline génération de contenu TTS-direct depuis un programme

- **DB** : 2 nouvelles tables `content_generation_jobs` et `content_generation_segments` avec checkpointing
- **Service** `content_generation_service.py` :
  - `extract_sub_parts(program_text)` : Claude extrait automatiquement 6 sous-parties depuis le programme
  - `run_content_generation(folder_id)` : boucle 6 sous-parties × 3 passes (Passe 1/2/3 ~5 100 mots chacune) = ~92 000 mots
  - Checkpoint après chaque passe : reprise automatique sans repasser les segments déjà générés
  - Assemblage final + upload Azure comme document `.txt` dans le dossier
- **Routes** :
  - `POST /api/hr/cours-folders/<id>/content-job` — crée le job + extraction synchrone des sous-parties
  - `POST /api/hr/cours-folders/<id>/content-job/start` — lance/reprend la génération (eventlet)
  - `GET /api/hr/cours-folders/<id>/content-job` — statut en temps réel (polling 3s)
  - `POST /api/hr/cours-folders/<id>/content-job/cancel` — annule le job
  - `GET /api/hr/cours-folders/<id>/content-job/preview` — prévisualise le prompt Passe 1 pré-rempli
- **Frontend** : nouvelle section "Générer le contenu depuis un programme" dans la vue dossier
  - Textarea programme → bouton "Extraire les sous-parties" (Claude ~5s)
  - Liste des 6 sous-parties + bouton "Lancer la génération" + "Prévisualiser le prompt"
  - Barre de progression (passes X/18, mots générés en temps réel)
  - Bouton "Reprendre depuis le checkpoint" en cas d'erreur
  - Note utilisateur : "Chaque dossier représente une journée de formation"

### Feature : Réordonnancement drag & drop des dossiers de cours (ordre chronologique)

- **DB** : ajout colonne `position INTEGER` sur `cours_folders` + migration auto des dossiers existants par ordre de création
- **Backend** : `get_cours_folders` ordonne désormais par `position ASC` et retourne le champ `position`
- **Backend** : `create_cours_folder` assigne `position = max + 1` automatiquement
- **Route** : `PUT /api/hr/platforms/<id>/cours-folders/reorder` — reçoit `[{id, position}]` et met à jour en bulk
- **Frontend** : les cartes dossiers sont maintenant draggables (HTML5 drag & drop), réordonnement optimiste côté client avec rollback en cas d'erreur
- **Frontend** : badge "Jour X" affiché sur chaque carte selon sa position dans la liste
- **Frontend** : hint "Glissez les cours pour changer leur ordre chronologique" + icône drag visible au hover
- **Design** : carte source semi-transparente en cours de drag, carte cible surlignée en violet avec scale(1.02)

### Feature : Intégration pipeline TTS dans la plateforme (analyse + génération + remplissage)

- **Analyse des mots** : nouveau bouton "Analyser le contenu" dans CoursFolders → compte les mots de tous les PDFs du dossier, indique si suffisant pour une journée (seuil 69 120 mots = 192 mots/min × 360 min), affiche le surplus ou le manque
- **Recyclage Q&A/Pauses** : la pipeline `playlist_tts_service.py` récupère désormais les fichiers Q&A et Pauses depuis le container Azure `audioqapause` (permanent) au lieu de les générer via fish.audio à chaque fois → économie de 12 appels TTS par journée
- **Route `/analyse`** : `GET /api/hr/cours-folders/<id>/analyse` — analyse mot par mot tous les PDFs du dossier
- **Route `/fill-from-folder`** : `POST /api/hr/platforms/<id>/fill-from-folder` — copie les 7 cours depuis `audiostts` + les 12 Q&A/Pauses depuis `audioqapause` vers le container audio de la plateforme
- **Bouton "Remplir avec les audios"** dans AUDIOS FORMATION (HRDashboard) → sélecteur de dossier → copie automatique des 19 fichiers dans la plateforme

## 2026-04-10

### Pipeline TTS — Résumabilité + persistance Azure Blob

- **Nouveau module** : `tts_pipeline_state.py` (SQLite local + Azure Blob Storage)
  - Table `tts_jobs` : journal des jobs (status, total_paragraphs, etc.)
  - Table `tts_segments` : état de chaque paragraphe (done/failed, azure_path, duration_ms)
  - Helpers Azure : `azure_upload_segment`, `azure_download_segment`, `azure_upload_final`
- **Refactor `pipeline_tts_v2.py`** :
  - Nouveau flag `--job-id` (défaut : nom du output-dir) pour identifier un job
  - `generate_all_tts_parallel` : skip les paragraphes déjà en BDD, upload Azure immédiat après chaque génération
  - `assemble_slots` : télécharge depuis Azure à la demande au lieu de tout garder en RAM (~4 GB → ~100 MB)
  - Les 7 MP3 finaux sont uploadés vers Azure dans `{job_id}/final/`
- **Résultat** : si la pipeline crash ou que le crédit API s'épuise, on relance la même commande et elle reprend pile où elle s'est arrêtée. Aucun appel TTS gaspillé. Tout est dans le container Azure `pipelinebackup`.
- **Variables .env requises** : `AZURE_AUDIO_STORAGE_CONNECTION_STRING`, `AZURE_BACKUP_CONTAINER` (défaut `pipelinebackup`).

## 2026-04-09

### Prompt : Génération directe cours oral TTS-ready

- **Nouveau prompt** : `prompt-generation-tts-direct.md` — fusionne la génération de contenu ET la reformulation TTS en un seul prompt.
- **Objectif** : utiliser Claude web (gratuit/Pro) au lieu de l'API pour générer directement du texte oral prêt pour Fish Audio S2-Pro, sans étape de reformulation intermédiaire.
- **Économie** : ~$13.50 par formation (suppression génération API + reformulation API). Seul le coût Fish Audio TTS reste (~$20).
- **Process** : 3 passes par sous-partie (fondation, expansion, enrichissement), chaque passe génère directement du texte oral avec tags S2-Pro → envoi direct à `pipeline_tts_v2.py`.

## 2026-04-07

### Fix : config-cours distant passe maintenant `platform_id`

- L'endpoint `/api/internal/config-cours` (appelé par P1 vers P2/P3) utilisait `set_heure_debut_cours()` sans `platform_id` → mettait à jour `platform_id=1` dans la BDD distante au lieu de la bonne plateforme.
- Corrigé : le payload inclut maintenant `platform_id` et l'endpoint le lit pour mettre à jour la bonne ligne.

### UI : HR Dashboard — pagination des cartes plateformes

- Grille repassée à 3 colonnes max (`lg:grid-cols-3`) pour des cartes plus grandes et lisibles.
- Ajout d'une pagination (Précédent / numéros / Suivant) quand il y a plus de 3 plateformes.

### Fix : Page Attente — compteur à 00 en multi-tenant

- `Attente.jsx` utilisait `fetch(apiUrl(...))` au lieu de `apiFetch(...)`, donc le header `X-Platform-Id` n'était pas envoyé → le backend retournait le statut de P1 (cours terminé) au lieu de la bonne plateforme.

### Fix : HR Dashboard — liens "Accéder au cours" avec `?p={id}` pour multi-tenant

- Les liens "Accéder au cours" et recorder dans le HR Dashboard pointaient vers `/video` sans `?p={id}`, donc le frontend ne savait pas quelle plateforme charger (défaut P1 → "cours terminé").
- Corrigé : le lien pointe maintenant vers `/?p={id}` pour que le `platform_id` soit stocké en localStorage dès le login.

### Fix : HR Dashboard — actions locales pour plateformes multi-tenant

- **Problème** : Les actions "Heure du cours", "Verrouiller uploads" et "Auto-schedule" faisaient `if platform_id == 1: local` / `else: HTTP distant`. Les plateformes multi-tenant (P4, P5+) n'ont pas de backend séparé → timeout HTTP vers un backend inexistant.
- **Solution** : Ajout de `_is_local_platform(pid)` qui vérifie si la plateforme a un `backend_url` configuré. Si non → appel local direct au `time_service`. Corrigé dans 5 endroits de `hr_routes.py` : `get_platform_course_time`, `proxy_config_cours`, `toggle_upload_lock`, `_unlock_platform`, `auto_schedule`.

## 2026-04-03

### Feature : Pipeline TTS automatisée - Génération des 19 audios de formation

- **Concept** : Prendre plusieurs PDFs d'un cours → générer automatiquement les 19 fichiers MP3 conformes à la playlist (7 blocs cours + 7 Q&A + 5 pauses)
- **Approche** : Concaténation des PDFs → découpage proportionnel en 7 blocs de cours (calibration 192 mots/min via fish.audio speed=0.95) → transitions naturelles (pas de mention temporelle pour bloc 4 été/hiver) → TTS via fish.audio → upload Azure avec nommage strict
- **Technologie** : Claude API pour reformulation/structuration + fish.audio pour TTS + pydub pour mesure durée
- **Interface** : Intégration dans CoursFolders + pipeline orchestrée en backend

### Implémentation : Pipeline TTS playlist

- **`backend/services/playlist_tts_service.py`** — Nouveau service d'orchestration
  - `PLAYLIST_SPEC` : définition des 19 fichiers (nom, durée, type, bloc)
  - `_call_claude_reformulate()` : reformulation **bloc par bloc** (7 appels Claude Sonnet)
    - Découpage proportionnel du texte source selon les durées des blocs
    - Contexte du bloc précédent transmis pour continuité narrative
    - Retry automatique (3 tentatives) si le word count est hors tolérance ±15%
    - `_count_words_excluding_tags()` : décompte excluant les tags [crochets] fish.audio
  - Tags fish.audio S2-Pro intégrés **directement par Claude** (pas d'heuristique)
    - Langage naturel libre en [crochets] : `[pause]`, `[excited]`, `[speak with conviction]`, etc.
    - Jamais de parenthèses (syntaxe S1 uniquement)
    - 15-25 tags d'émotion + 15-20 [pause] + 4-6 [long pause] par bloc
  - `_pad_audio_to_duration()` : 17s silence début + padding/truncate fin
  - `_build_pause_audio()` : intro TTS + silence + outro TTS
  - Q&A et pauses : **7 variantes** de textes pour éviter la répétition
  - Transitions bloc 4 neutres : "Très bien, on reprend." (fonctionne été comme hiver)
  - `generate_playlist_for_folder()` : pipeline complète avec callback de progression
  - Résultat enrichi : durée totale (h), taille totale (Mo), word counts par bloc
- **`backend/routes/hr_routes.py`** — Nouvelles routes
  - `POST /api/hr/cours-folders/<id>/generate-playlist` — lance la pipeline en background (eventlet)
  - `GET /api/hr/cours-folders/<id>/playlist-status` — retourne la progression en temps réel
  - État des jobs en mémoire (`_playlist_jobs`) avec step/total/message
- **`frontend/src/components/CoursFolders.jsx`** — Bouton "Générer la playlist (19 MP3)"
  - Barre de progression avec polling toutes les 2s
  - Affichage statut terminé : X/19 fichiers + durée totale + taille Mo
  - Affichage erreur avec message
- **`backend/requirements.txt`** — Ajout `anthropic>=0.30.0`

## 2026-04-02

### Feature : Planning saisonnier été/hiver (swap bloc 4)

- **Concept** : Pour les formations du vendredi (ou toute formation choisie), l'ordre du bloc 4 (pause midi / cours / Q&R) s'inverse selon la saison
  - **Hiver** : Pause (12h20-13h50) → Cours (13h50-14h35) → Q&R (14h35-14h45)
  - **Été** : Cours (12h20-13h05) → Q&R (13h05-13h15) → Pause (13h15-14h45)
  - Durée totale identique (145 min) → zéro décalage sur le reste de la playlist
- **`backend/database/db.py`** — Ajout colonne `playlist_mode` (NULL/ete/hiver) sur `platform_config`
- **`backend/services/audio_service.py`** — `get_playlist(platform_id)` retourne la playlist dynamique selon le mode
- **`backend/routes/video_routes.py`** — Passe `platform_id` à `get_current_audio_info()` via query param optionnel
- **`backend/routes/hr_routes.py`** — Routes `GET/POST /api/hr/schedule-config` pour lire/écrire la config saison
- **`frontend/src/pages/ScheduleConfig.jsx`** — Page admin `/schedule-config` : toggle été/hiver + sélection des formations concernées
- **`frontend/src/App.jsx`** — Route `/schedule-config` protégée par `ProtectedAdminRoute`

### Feature : Migration stockage cours vers Azure Blob Storage

- **`backend/services/azure_blob_service.py`** — Nouveau service Azure Blob Storage
  - Fonctions `upload_blob`, `download_blob`, `delete_blob`, `delete_blobs_by_prefix`
  - Deux conteneurs : `documenttts` (PDFs) et `audiostts` (MP3 générés)
  - Organisation des blobs : `platform-{id}/folder-{id}/{uuid}.pdf|.mp3`
  - Variable d'environnement : `AZURE_TTS_STORAGE_CONNECTION_STRING`
- **`backend/services/tts_service.py`** — Adapté pour travailler avec des bytes en mémoire
  - `extract_text_from_pdf()` accepte des bytes (BytesIO) au lieu d'un chemin fichier
  - `convert_to_speech()` retourne des bytes MP3 au lieu d'écrire sur disque
  - `process_document_to_audio()` pipeline complète bytes-in / bytes-out
- **`backend/routes/hr_routes.py`** — Routes cours migrées de filesystem local vers Azure
  - Upload PDF → Azure `documenttts` (plus de `file.save()` local)
  - Download PDF/audio → proxy depuis Azure via `send_file(BytesIO(...))`
  - Suppression → `delete_blob()` Azure au lieu de `os.remove()`
  - Pipeline TTS background : télécharge PDF depuis Azure, traite en mémoire, upload MP3 sur Azure
  - Zéro stockage local, tout passe par Azure Blob Storage

## 2026-02-20

### Feature : Déploiement Azure Function via GitHub Actions

- **`.github/workflows/deploy-azure-function.yml`** — Workflow de déploiement de la Function App d'auto-scheduling
  - Se déclenche sur push `staging` quand des fichiers `azure-function/**` changent
  - Utilise `Azure/functions-action@v1` avec `scm-do-build-during-deployment: true`
  - Le secret `AZURE_FUNCTIONAPP_PUBLISH_PROFILE` doit être ajouté dans GitHub → Settings → Secrets
  - Le nom de la Function App est à renseigner dans la variable `AZURE_FUNCTIONAPP_NAME` du workflow

### Feature : Azure Function App - Auto-scheduling des cours

- **`azure-function/`** — Nouvelle Azure Function Timer Trigger (modèle Python v1)
  - `auto_schedule/__init__.py` — S'exécute chaque samedi à 8h UTC (9h Paris)
  - `auto_schedule/function.json` — CRON `0 0 7 * * 6` (samedi 7h UTC = 8h Paris hiver / 9h été)
  - Appelle `POST /api/internal/auto-schedule` sur le backend P1 avec la clé `PLATFORM_API_KEY`
  - P1 programme P1 localement + propage vers P2/P3 via `_call_platform()`
  - Plan : Consommation Azure (paiement à l'usage, idéal pour 1 exécution/semaine)
- **`backend/routes/hr_routes.py`** — Route `POST /api/internal/auto-schedule`
  - Protégée par header `X-Platform-Key` (comparé à `PLATFORM_API_KEY` env var)
  - Schedule par défaut : P1=vendredi 9h, P2=lundi 9h, P3=mercredi 9h
- **`.gitignore`** — Ajout de `azure-function/local.settings.json` (contient les clés sensibles)

### Feature : Recorder accessible sans mot de passe

- **`App.jsx`** — `/recorder` n'est plus protégé par `ProtectedAdminRoute`
- **`admin_routes.py`** — Suppression des vérifications `is_admin` sur les routes utilisées par le Recorder :
  - `POST /api/admin/upload-audios`
  - `GET /api/admin/audio-upload-status`
  - `DELETE /api/admin/audios/<filename>`
- Les intervenants peuvent désormais accéder au Recorder et uploader des audios sans compte admin

### Fix : Route publique pour la liste d'audios du Recorder

- **`hr_routes.py`** — Nouvelle route `GET /api/recorder/audio-list` accessible sans session admin
  - Lit le container Azure configuré sur ce backend (`AZURE_AUDIO_CONTAINER`)
  - Génère des URLs SAS valides 1h pour chaque fichier
  - Ajoutée dans `always_allowed` du `before_request` (bypass du feature flag HR)
- **`Recorder.jsx`** — Utilise `/api/recorder/audio-list` au lieu de `/api/admin/audio-list`
  - Permet aux intervenants non-admin de voir et uploader leurs fichiers

### Analyse : Les Recorders P2/P3 affichaient les mêmes fichiers

- Cause identifiée : les containers `formationaudio-p2` et `formationaudio-p3` contenaient les mêmes fichiers
- Chaque container est indépendant mais partage le même compte de stockage Azure (`formationaudios`)

## 2026-02-19

### Feature : Intégration complète Plateforme 2 dans le Dashboard RH

- **`hr_routes.py`** — Fonctionnalités P2 opérationnelles :
  - `get_platforms()` : expose `frontend_url` dans la réponse pour chaque plateforme
  - `toggle_lock()` : propage le changement de lock vers P2 via `_call_platform()` → `/api/internal/set-lock`
  - `get_platform_audios()` : utilise le container Azure de chaque plateforme (`PLATFORM_2_AUDIO_CONTAINER`)
  - `delete_audio()` : supporte tous les containers (P1 et P2+)
  - Nouvelle route `POST /api/hr/platforms/<id>/config-cours` : pour P1 appelle `set_heure_debut_cours` localement, pour P2+ proxy vers `/api/internal/config-cours`

- **`HRDashboard.jsx`** — Adaptations multi-plateformes :
  - Lien "Accéder au cours" utilise `p.frontend_url` (ou `window.location.origin` en fallback)
  - Bouton "Heure du cours" mémorise la plateforme sélectionnée (`courseTimePlatformId`)
  - `handleSetCourseTime` appelle `/api/hr/platforms/<id>/config-cours` (route unifiée)

- **`.env`** — Nouvelles variables multi-plateformes :
  - `PLATFORM_2_BACKEND_URL`, `PLATFORM_2_FRONTEND_URL`
  - `PLATFORM_2_AUDIO_CONTAINER`, `PLATFORM_2_PDF_CONTAINER`
  - `PLATFORM_API_KEY` (clé partagée pour les appels service-to-service)

### Fix : Port backend 5000 → 5001

- Conflit avec un autre projet local
- Modifié dans `run.py`, `main_app.py`, `vite.config.js` (2 occurrences)

### Fix : Déploiement GitHub Actions Plateforme 2

- Réécriture de `staging_socrate-backend-p2.yml` pour utiliser `working-directory: ./backend`
- Correction de l'erreur "requirements.txt not found" due à la configuration auto-générée par Azure

### Feature : Feature flag `HR_DASHBOARD_ENABLED`

- Variable d'env `HR_DASHBOARD_ENABLED` (défaut `false`, `true` uniquement sur P1)
- `hr_routes.py` : `before_request` guard bloque toutes les routes HR si désactivé (sauf `get_hr_enabled` et `check_upload_permission`)
- `App.jsx` : `ProtectedHRRoute` vérifie `/api/hr/enabled` côté serveur avant d'afficher `/hr-dashboard`

### UX : Indicateurs de chargement gris + blocage scroll

- Recorder.jsx : cercles de chargement gris (`#9ca3af`) avec `animate-spin` (place des couleurs statiques)
- Index.jsx / Video.jsx : `overflow: hidden` sur `body` pour empêcher le scroll hors page
- Recorder.jsx / HRDashboard.jsx : `useEffect` pour corriger la couleur de l'overscroll

## 2026-02-18

### Feature : Upload audio asynchrone / parallèle

- Refactoring complet du pipeline d'upload audio : passage d'un traitement séquentiel (convert all → upload all) à un traitement **parallèle par fichier** via `eventlet.GreenPool(size=4)`
- Chaque fichier suit son propre cycle de vie indépendant : `pending → converting → uploading → done`
- **Backend** (`state.py`, `admin_routes.py`) :
  - Ajout de `files_status` dans `audio_upload_job` pour tracker l'état individuel de chaque fichier
  - Nouveau statut global `processing` (remplace l'ancien flow `converting → uploading`)
  - `_process_audio_upload` réécrit avec `process_single_file` + `GreenPool`
- **Frontend** (`Recorder.jsx`) :
  - Suivi de `filesStatus` (dict backend) au lieu de `currentFile`
  - Chaque audio dans les cartes (Cours/Pauses/Q&A) affiche son état en temps réel : cercle coloré pendant le traitement, bouton play dès qu'il est terminé
  - Polling Azure audios déclenché pendant la phase `processing`

### UX : Indicateurs visuels d'upload par fichier

- Chaque fichier audio dans les 3 cartes (Cours, Pauses, Q&A) affiche un indicateur visuel individuel pendant l'upload
- 4 états visuels par fichier : uploadé (bouton play coloré), en cours actif (cercle plein), en attente (cercle avec point), non uploadé (icône grise)
- Couleurs par catégorie : Cours=#3b82f6, Pauses=#f59e0b, Q&A=#16a34a
- Indicateurs statiques (pas d'animations) selon la préférence utilisateur

## 2026-02-17

### UX : HR Dashboard — Modale de confirmation pour suppression audio

- Remplacement du `confirm()` natif du navigateur par une modale custom
- Icône poubelle rouge, titre, nom du fichier en gras, message "Cette action est irréversible"
- Boutons Annuler / Supprimer (rouge)
- Clic en dehors de la modale → fermeture

### UI : Page Video — fond spatial + "TP CRCD" en grand

- Zone vidéo : fond remplacé par `rocket.jpg` (même image que la homepage), cadré sur le haut (ciel étoilé / espace)
- Overlay sombre semi-transparent pour lisibilité
- Avatar "Professeur" remplacé par "TP CRCD" en très grand blanc gras (Poppins, tracking large), style header à la TurboScribe

### Fix : Export Excel — durée calculée pour les sessions "en cours"

- Les utilisateurs encore connectés au moment de l'export ont désormais leur durée calculée (heure d'arrivée → heure actuelle) au lieu de "En cours..."
- La durée affichée est suffixée `(en cours)` pour signaler que c'est une estimation
- Ces sessions sont désormais incluses dans le récapitulatif "Temps total de connexion" par utilisateur

### Feature : HR Dashboard — Bouton "Heure du cours" sur Plateforme active

- Ajout d'un bouton **"Heure du cours"** dans la carte de la plateforme active (entre "Accéder au cours" et "Voir les audios")
- Clic → ouvre une modale légère `CourseTimeModal`
- **Modal Heure du cours** :
  - Header bleu cohérent avec le reste du dashboard
  - Champ **date** (pré-rempli avec la date du jour)
  - Champ **heure** (time picker natif)
  - Appel `POST /api/admin/config_cours` avec `{ date_cours, heure_cours }` (même API que la page Admin)
  - Feedback succès : icône verte + message de confirmation renvoyé par l'API
  - Feedback erreur : bandeau rouge avec le message d'erreur
  - Boutons Annuler / Enregistrer (désactivé si champs vides ou en chargement)

### Feature : HR Dashboard — Modal PDF avec visualiseur et upload

- **Transformation de la section PDF** :
  - Au lieu d'afficher "Aucun PDF" avec boutons upload/delete, bouton cliquable "Gérer le PDF" avec flèche à droite
  - Clic sur le bouton → ouverture d'une modal overlay
- **Modal PDF** :
  - Header bleu avec titre "GESTION DU PDF" + icône + bouton fermer
  - Layout en 2 colonnes :
    1. **PDF ACTUEL** (gauche) : Visualiseur de PDF avec iframe + bouton supprimer
    2. **UPLOADER UN NOUVEAU PDF** (droite) : Zone de drag & drop avec icône cloud_upload
  - Si aucun PDF : message "Aucun PDF uploadé" avec grande icône
  - Drag & drop fonctionnel avec feedback visuel (bordure bleue + fond bleu clair)
  - Spinner pendant l'upload
  - Format : PDF uniquement
- **UX** :
  - Clic en dehors de la modal → fermeture
  - Clic sur la croix → fermeture
  - Visualisation directe du PDF dans un iframe
  - Upload par drag & drop ou clic pour parcourir
- **Objectif** : Interface unifiée pour visualiser et gérer le PDF du RAG pour chaque plateforme

### Feature : HR Dashboard — Modal d'audios avec 3 cartes

- **Transformation du bouton "Voir les audios"** :
  - Au lieu d'ouvrir une liste en dessous, ouvre maintenant une modal overlay
- **Modal d'audios** :
  - Header bleu avec titre "AUDIOS FORMATION" + icône + bouton fermer
  - 3 cartes côte à côte (Cours, Pauses, Q&A) comme dans la page Recorder
  - Chaque carte affiche :
    - Image personnalisée avec bordure noire
    - Titre de la catégorie
    - Compteur X/Y fichiers
    - Liste des audios attendus avec état (uploadé = check vert, non uploadé = play gris)
  - Design en lecture seule (pas de boutons play/delete)
  - Modal responsive avec scroll vertical
- **UX** :
  - Clic en dehors de la modal → fermeture
  - Clic sur la croix → fermeture
  - Loading spinner pendant le chargement des audios
- **Objectif** : Vue d'ensemble rapide et visuelle des audios uploadés pour chaque plateforme

## 2026-02-17

### Design : Recorder — Organisation des audios en 3 cartes par catégorie

- **Séparation en 3 cartes** au lieu d'une seule liste :
  1. **Carte COURS** (bleue, image carnet/crayon avec bordure noire) : tous les fichiers `cours_*`
  2. **Carte PAUSES** (jaune/orange, image réveil "BREAK TIME" avec bordure noire) : tous les fichiers `pause_*`
  3. **Carte Q&A** (verte, image bulles de dialogue avec bordure noire) : tous les fichiers `qa_*`
- **Layout** : Grid responsive (1 colonne mobile, 3 colonnes desktop)
- **Chaque carte affiche** :
  - Icône colorée dans un badge arrondi
  - Titre de la catégorie
  - Compteur : X/Y fichiers uploadés
  - Liste des audios de cette catégorie (ordre chronologique)
  - Boutons play, durée, suppression pour chaque audio
- **Design compact** : cartes arrondies (rounded-2xl), items plus petits, player audio inline
- **Icônes audios** : petits logos "audiotrack" grisés pour les fichiers non uploadés (au lieu de cadenas)
- **Objectif** : Meilleure vue d'ensemble et organisation visuelle par type de contenu

### Design : Recorder — Refonte de la zone d'upload avec modal + flèche décorative

- **Transformation de la zone d'upload** :
  - Remplacement de la grande zone de drag & drop par un simple bouton "DÉPOSEZ VOS FICHIERS"
  - Bouton avec icône upload, fond bleu (#137fec), centré
  - Au clic, ouverture d'une modal overlay avec fond semi-transparent
- **Nouvelle disposition centrée** :
  1. Texte descriptif centré en haut : "Gérez et uploadez vos 19 pistes audio séquentielles..."
  2. **Flèche décorative** style "hand-drawn" (image PNG bleue courbe) qui pointe vers le bouton
  3. Bouton "DÉPOSEZ VOS FICHIERS" centré
  4. Barre de progression minimaliste et discrète (h-1, sans carte, juste X/Y fichiers + pourcentage + barre fine avec glow)
- **Modal d'upload** :
  - Header bleu avec titre "TRANSCRIRE DES FICHIERS" + icône upload + bouton fermer
  - Zone de drag & drop dans le corps de la modal
  - Texte : "Glissez vos fichiers ici ou cliquez pour parcourir"
  - Formats supportés affichés en petits caractères
  - Bouton "Uploader les fichiers" après sélection
  - Barre de progression pendant upload (saving/converting/uploading)
- **UX** :
  - Clic en dehors de la modal → fermeture
  - Clic sur la croix → fermeture
  - Après upload → fermeture automatique de la modal
- **Objectif** : Interface plus épurée et visuelle avec interaction guidée par la flèche décorative

### Design : Recorder — Simplification du header (suite)

- **Suppression de 3 éléments** dans la section Context & Progress :
  - Icône folder_open retirée
  - Texte "FORMATION TP CRCD" retiré
  - Titre "Upload Sequence" retiré
- **Résultat** : La section ne contient plus que la description fonctionnelle et la carte de progression
- **Objectif** : Épurer encore plus l'interface, focus sur l'essentiel

### Design : Recorder — Redesign complet inspiré du template "Audio Manager Pro"

- **Objectif** : Moderniser l'interface Recorder avec un design propre, épuré et professionnel
- **Inspiration** : Template HTML "Audio Upload Progress Dashboard v2" avec Material Icons et palette bleue
- **Changements visuels** :
  - Header sticky avec icône graphic_eq + titre "Audio Manager Pro" + sous-titre "Formation TP CRCD"
  - Section progress : tag bleu "FORMATION TP CRCD", titre "Upload Sequence", description
  - Card de progression : X% completion, Y of Z tracks uploaded, barre de progression bleue
  - Grille responsive (1-5 colonnes selon taille écran) de 19 cards représentant chaque audio attendu
  - **Cards complétées** : check vert, boutons play/delete avec hover, durée (parsée depuis nom fichier), taille, barre verte en bas, audio player inline
  - **Card upload active** : bordure pointillée bleue, icône cloud_upload, zone drop/browse, bouton "Uploader", barre de progression pendant upload
  - **Cards verrouillées** : icône lock, grises, opacity 0.6
  - Messages success/error/info en bas avec couleurs adaptées (vert/rouge/bleu)
  - Rapport d'upload détaillé avec symboles ✓/✗
  - Footer : "Audio Upload Dashboard v2.0 • Designed for high-efficiency workflows."
- **Fonctionnalités conservées** :
  - Check permission upload RH (bannière rose si verrouillé)
  - Upload drag & drop + multi-fichiers avec preview
  - Lecture audio inline dans les cards
  - Suppression d'audios (si non verrouillé)
  - Polling avec barre de progression (saving/converting/uploading)
  - Rapport d'upload détaillé (fichiers convertis, skippés)
  - Upload séquentiel : seul le prochain audio manquant a la zone d'upload active
  - Parse durée depuis nom fichier (ex: cours_9h00_9h45.mp3 → 45min)
- **Palette** :
  - Primary : #137fec (bleu)
  - Fond : #f8fafc (gris très clair)
  - Cards : blanc #ffffff avec bordure #e2e8f0
  - Success : vert #16a34a
  - Error : rouge #ef4444
  - Police : Inter
  - Icons : Material Icons
- **Backend** : Aucun changement (toutes les fonctionnalités préservées)

### Design : HR Dashboard — Redesign complet avec Material Icons et palette purple

- **Objectif** : Moderniser l'interface du Dashboard RH avec un design plus épuré et professionnel
- **Changements visuels** :
  - Police Inter appliquée sur toute la page (au lieu de Fredoka)
  - Material Icons de Google remplacent tous les SVG custom (lock, audiotrack, picture_as_pdf, delete, etc.)
  - Palette de couleurs : Purple #8B5CF6 au lieu de fuchsia (#d946ef)
  - Fond : #0f172a (slate-900) avec grid pattern subtil (rgba white 0.03)
  - Cards : #1e293b (slate-800) avec bordure purple pour plateformes actives, gray pour inactives
  - Overlay "BIENTÔT DISPONIBLE" avec icône Material "schedule" sur fond blur
  - Toggle switch avec glow purple (box-shadow rgba(139, 92, 246, 0.5)) quand verrouillé
  - PDF upload : bordure dashed #334155 sur fond #0f172a
  - Alertes : fond #450a0a (rose) ou #713f12 (amber) avec icônes Material "error" ou "warning"
- **Nouvelle feature** : Dark mode toggle dans le header (bouton avec icône "light_mode"/"dark_mode")
  - Par défaut en mode sombre
  - Changement d'icône dynamique selon l'état
- **Footer** ajouté :
  - Copyright "© 2026 Le Socrate. Tous droits réservés."
  - Liens : Documentation, Support, Confidentialité
  - Bordure top #1e293b, texte #64748b
- **Boutons interactifs** avec hover states inline (onMouseEnter/onMouseLeave) :
  - PDF delete : hover #450a0a avec texte #f87171
  - PDF upload : hover #581c87 avec texte #c084fc
  - Expand audios : hover background #1e293b
  - Play audio : hover #7c3aed
- **Pipeline de backup** : icônes Material "check", spinner custom, "close" pour les états
- **Backend** : Aucun changement (toutes les fonctionnalités préservées)
- **Frontend** : index.html — ajout des imports Google Fonts (Material Icons + Inter)

### Design : Zone vidéo avec bordure violette fine (sans glow)

- Bordure violette fine (`border-[2.5px] border-purple-500`) - 2.5px, ton vif et élégant
- Pas d'effet glow violet, juste une ombre classique (shadow-2xl)
- Aspect épuré avec une bordure colorée subtile mais visible

### Design : Fond lavande clair sur la page Video (sauf header et boutons)

- Couleur appliquée : `#F8F7FF` (lavande très doux) sur le fond principal uniquement
- Header "Formation TP CRCD" : blanc avec bordure grise de séparation
- Boutons micro et chat : blanc de base, blanc surbrillant (avec ombre) au hover
- Rings des boutons : purple-100 au lieu de gray-100
- Effet visuel plus doux et chaleureux avec contraste blanc/lavande

## 2026-02-16

### Design : Icône professeur dans le chat

- **Modification** : Remplacement de l'icône lampe (ampoule) par une icône de professeur avec tableau dans le ChatPanel
- Nouvelle image : `professor-icon.png` (icône noir et blanc représentant un enseignant avec pointeur et tableau)
- Contour circulaire noir fin (1px) ajouté autour du cercle jaune pour plus de définition visuelle
- Animation de chargement remplacée par message texte : "Un instant, le professeur va vous répondre..."
- Délai de 5 secondes ajouté avant l'affichage de la réponse pour un effet plus naturel
- Impacte les messages de l'assistant et l'état de chargement
- Contexte visuel plus cohérent avec le thème pédagogique de l'application

### Feature : Backup vérifié avant ouverture aux intervenants (HR Dashboard)

- **Comportement** : le toggle "Ouvrir" déclenche une pipeline en 3 étapes au lieu d'un simple deverrouillage instantané
- **Pipeline backend** (tâche de fond avec polling) :
  1. Copie server-side de chaque blob vers `formationaudio-archives/{date_heure}/plateforme-{id}/`
  2. **Vérification stricte** : compare noms source vs archive — si un seul manque, arrêt immédiat sans suppression
  3. Suppression des blobs source (seulement si vérification 100% OK)
  4. Déverrouillage (`upload_locked = 0` en DB)
- **Backend** : `backup_jobs` dans `state.py` + 2 nouveaux endpoints dans `hr_routes.py` + `AZURE_AUDIO_ARCHIVE_CONTAINER` en `.env`
- **Frontend** : composant `BackupPipeline` avec 3 étapes horizontales animées (fuchsia = done, spinner = running, croix = error) + polling 1.5s

### Feature : Dashboard RH — Centre de controle des 3 plateformes

- **Objectif** : permettre aux RH de piloter les 3 plateformes de formation depuis une seule page sans echanger par mail
- **Backend** :
  - 2 nouvelles tables SQLite : `platform_config` (config par plateforme, verrouillage upload, PDF) et `deletion_requests` (demandes de suppression par les contributeurs)
  - Seed automatique de 3 lignes dans `platform_config` a l'init de la base
  - Nouveau blueprint `hr_routes.py` (factory pattern) avec 11 endpoints :
    - `GET /api/hr/platforms` — vue d'ensemble des 3 plateformes (stats Azure, alertes, PDF)
    - `POST /api/hr/platforms/<id>/toggle-lock` — verrouiller/deverrouiller l'upload
    - `GET /api/hr/platforms/<id>/audios` — lister les audios (P1=Azure, P2/P3=vide)
    - `DELETE /api/hr/platforms/<id>/audios/<filename>` — supprimer un audio Azure
    - `POST /api/hr/platforms/<id>/upload-pdf` — uploader un PDF par plateforme
    - `DELETE /api/hr/platforms/<id>/pdf` — supprimer le PDF
    - `GET /api/hr/upload-permission/<id>` — check permission (sans auth admin, pour Recorder)
    - `POST /api/hr/deletion-requests` — creer une demande de suppression (sans auth admin)
    - `GET /api/hr/deletion-requests` — lister les demandes en attente
    - `POST /api/hr/deletion-requests/<id>/approve` — approuver (supprime le blob Azure)
    - `POST /api/hr/deletion-requests/<id>/reject` — rejeter
  - Blueprint enregistre dans `main_app.py`
- **Frontend** :
  - Nouvelle page `HRDashboard.jsx` accessible sur `/hr-dashboard` (protegee admin)
  - Design "mission control" : fond sombre avec grille subtle, gradient radial, cards avec bordure fuchsia/gris
  - 3 cartes plateforme : P1 active (Azure connecte), P2/P3 avec overlay "Bientot disponible"
  - Toggle lock custom avec glow fuchsia, pastille pulsante verte/grise
  - Gestion des audios inline : lecture, suppression, accordeon
  - Upload PDF par plateforme avec preview
  - Panneau des demandes de suppression avec boutons approuver/rejeter
  - Alertes dynamiques (PDF manquant, aucun audio, demandes en attente)
  - Lien "Dashboard RH" (bouton fuchsia) ajoute dans le header de `Admin.jsx`
- **Recorder.jsx** :
  - Check permission upload au montage (`GET /api/hr/upload-permission/1`)
  - Banniere rose "Uploads verrouilles par les RH" + zone de drop desactivee quand verrouille
  - Bouton "Demander la suppression" sur chaque audio de la playlist Azure
  - Modal avec nom du demandeur + raison + envoi vers `POST /api/hr/deletion-requests`

### Feature : Export Excel — colonne "Temps total de connexion" par utilisateur (export_service.py)

- Ajout d'un tableau récapitulatif en colonnes H-J du fichier Excel
- Pour chaque utilisateur unique (nom + prénom), affiche le cumul de toutes ses sessions
- Format : `Xh Ymin Zsec` ou `Ymin Zsec` selon la durée
- Trié alphabétiquement par nom
- En-têtes colorés (bleu foncé pour le détail, bleu moyen pour le récap)
- Largeurs de colonnes automatiques pour la lisibilité

### Fix : Tests Playwright — gestion de l'état inconnu sur /video

- **Probleme** : le test `la page /video affiche un contenu valide` echouait avec `État inattendu: unknown` car la page restait bloquee sur "Chargement du cours..." (API Azure lente ou inaccessible depuis Chromium headless)
- **Solution** : refactoring de `loginAndGetState()` pour attendre explicitement la disparition du spinner de chargement avant de detecter l'etat, avec timeout 15s
- Ajout des etats `loading` et `error` pour couvrir tous les cas possibles
- Le test skippe proprement au lieu de planter quand l'etat ne peut pas etre determine
- Resultat : 11 passed, 0 failed, 7 skipped (exit 0)

### Fix : Routing SPA sur Azure Static Web Apps (staticwebapp.config.json)

- **Probleme** : les routes React (`/admin`, `/login-admin`, `/attente`, etc.) renvoyaient une 404 quand accedees directement dans la barre d'adresse, car Azure Static Web Apps cherchait un fichier physique
- **Solution** : ajout de `staticwebapp.config.json` dans `frontend/public/` avec `navigationFallback` vers `index.html`
- Toutes les routes non-statiques sont maintenant redirigees vers React Router

### Fix : Session cross-origin pour deploiement Azure (backend + frontend)

- **Probleme** : apres login, la session Flask n'etait pas transmise aux requetes suivantes. Deux causes :
  1. **Backend** : les cookies de session n'avaient pas `SameSite=None; Secure`, requis pour le cross-origin
  2. **Frontend** : les fetch critiques (`/api/auth/login` dans Index.jsx, `/api/video/status` dans Video.jsx) n'avaient pas `credentials: 'include'`, donc le navigateur ignorait le `Set-Cookie` et n'envoyait pas le cookie
- **Solution backend** : ajout de `SESSION_COOKIE_SAMESITE = "None"` et `SESSION_COOKIE_SECURE = True` en mode Azure (`main_app.py`)
- **Solution frontend** : ajout de `credentials: 'include'` aux fetch manquants (`Index.jsx`, `Video.jsx`)
- Ajout d'un helper `apiFetch()` dans `api.js` qui inclut automatiquement `credentials: 'include'`

### Refactor : Migration de tous les fetch('/api/...') vers apiUrl('/api/...') dans le frontend

- **Objectif** : centraliser la construction des URLs API via le helper `apiUrl()` (defini dans `frontend/src/api.js`) pour faciliter le deploiement multi-environnement (dev, staging, production)
- **Fichiers modifies** (10 fichiers, 26 appels fetch au total) :
  - `pages/LoginAdmin.jsx` (1 fetch)
  - `pages/Recorder.jsx` (4 fetches)
  - `pages/Video.jsx` (2 fetches)
  - `pages/Attente.jsx` (1 fetch)
  - `pages/Admin.jsx` (7 fetches)
  - `pages/Index.jsx` (1 fetch)
  - `pages/DebugCours.jsx` (5 fetches)
  - `components/ChatPanel.jsx` (1 fetch)
  - `components/ProtectedAdminRoute.jsx` (1 fetch)
  - `pages/GeneratedSlides.jsx` (3 fetches)
- Chaque fichier importe desormais `{ apiUrl } from '../api'`
- Aucun changement de comportement : refactor pur

## 2026-02-13

### Fix : Page d'attente affiche maintenant la vraie heure de debut (Attente.jsx)

- **Probleme** : le countdown etait hardcode a 3600 secondes, sans lien avec l'heure reelle du cours
- **Solution** : le frontend appelle `/api/cours-status` pour recuperer `temps_restant` et `heure_debut`
- Le countdown se re-synchronise avec le backend toutes les 30 secondes
- L'heure de debut reelle est affichee (ex: "Debut prevu a 09:00")
- Si le cours demarre pendant l'attente, redirection automatique vers `/video`
- Ajout de `heure_debut` dans la reponse de `/api/cours-status` (backend)

### Fix : Upload PDF purge l'ancien index avant reindexation (admin_routes.py)

- **Probleme** : quand un nouveau PDF etait uploade, l'ancien contenu restait dans l'index Azure AI Search (l'indexer ne supprime pas automatiquement les documents dont le fichier source a disparu)
- **Solution** : avant de relancer l'indexer, le code supprime maintenant tous les documents de l'index puis reset l'indexer
- Pipeline complet : suppression anciens blobs → upload nouveau PDF → purge index → reset indexer → run indexer

### Amelioration : Audio demarre en muet si autoplay bloque (Video.jsx)

- Au refresh, l'audio demarre maintenant **en muet** au lieu de rester bloque en pause
- L'audio est synchronise a la bonne position immediatement
- Le bouton "Activer le son" ne fait que de-muter (un seul clic, pas de rechargement)
- Meilleure UX : l'utilisateur n'a plus l'impression que le cours est "casse" apres un refresh

## 2026-02-12

### Ajout : Upload audio en arriere-plan avec reprise apres refresh

- **Backend** (`state.py`) : Ajout de `audio_upload_job` — dictionnaire global pour tracker le statut du job (idle/saving/converting/uploading/completed/error), la progression, et le rapport final
- **Backend** (`admin_routes.py`) : Refactoring de `POST /api/admin/upload-audios` :
  - Phase 1 (synchrone) : reception et sauvegarde des fichiers dans `/tmp`, retour immediat (HTTP 202)
  - Phase 2 (arriere-plan) : conversion MP3 + upload Azure via `socketio.start_background_task()` (compatible eventlet)
  - Garde-fou : refuse un nouvel upload si un job est deja en cours (HTTP 409)
  - Nouveau endpoint `GET /api/admin/audio-upload-status` : retourne le statut complet du job
- **Frontend** (`Recorder.jsx`) : Resilience au refresh :
  - Au chargement, verifie `audio-upload-status` et reprend le polling si un job est en cours
  - Barre de progression animee avec indication de phase (sauvegarde/conversion/upload)
  - Zone de drop desactivee pendant le traitement
  - Rapport final affiche des que le job termine (meme apres un refresh)

### Ajout : Upload PDF + Ré-indexation RAG Azure

- **Backend** (`admin_routes.py`) : Ajout de 2 routes admin :
  - `POST /api/admin/upload-pdf` — Upload d'un PDF dans Azure Blob Storage (conteneur `formationpdf`), suppression des anciens blobs, puis déclenchement de l'indexer Azure AI Search
  - `GET /api/admin/indexer-status` — Polling du statut de l'indexer (inProgress / success / failure)
- **Frontend** (`Admin.jsx`) : Nouvelle section drag & drop PDF dans le panneau admin avec :
  - Zone de glisser-déposer acceptant uniquement les `.pdf`
  - Bouton "Mettre à jour le cours" avec spinner pendant l'upload
  - Polling automatique du statut de l'indexer toutes les 3s après upload
  - Affichage dynamique du statut : en cours / terminé / erreur
  - Persistance du statut : vérification de l'indexer au chargement de la page, reprise automatique du polling si indexation en cours

### Ajout : Upload multi-audios vers Azure Blob Storage

- **Backend** (`admin_routes.py`) : Ajout de la route `POST /api/admin/upload-audios` :
  - Réception multi-fichiers audio (mp3, wav, ogg, m4a, flac, aac, wma, webm)
  - Nettoyage automatique des noms de fichiers (espaces → `_`, points en trop, caractères spéciaux)
  - Conversion automatique en MP3 via pydub si le format source n'est pas MP3
  - Suppression des anciens blobs puis upload dans le conteneur Azure `formationaudio-dev`
  - Rapport détaillé par fichier (original → nettoyé, converti ou non, erreurs éventuelles)
- **Frontend** (`Admin.jsx`) : Nouvelle section drag & drop audio dans le panneau admin :
  - Zone de glisser-déposer multi-fichiers avec aperçu des noms nettoyés avant upload
  - Bouton "Uploader les audios" avec spinner pendant le traitement
  - Rapport visuel post-upload (fichiers uploadés, conversions effectuées, erreurs)
- **Config** (`.env`) : Ajout de `AZURE_AUDIO_CONTAINER=formationaudio-dev` (conteneur de test)
