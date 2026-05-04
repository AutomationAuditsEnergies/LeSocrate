# Cas pathologiques de la pipeline audio cours — checklist de monitoring

**Date** : 2026-04-30
**Thématique** : problème (catalogue)
**Statut** : actif (à surveiller en prod)

---

## Contexte

Après avoir construit l'édifice complet — cap budget cascade, backward
redistribution, carryover bloc 7, rebalancing LLM, closing contextuel — le
système a beaucoup de couches qui interagissent. Ce mémo liste les **cas
pathologiques** identifiés en cours de design qu'il faut surveiller en prod,
même si chacun a une voie de récupération prévue.

C'est une **checklist de monitoring**, pas un mémo de diagnostic après-coup.

## Cas listés

### 1. Bloc 7 surchargé sans next_folder

**Quand** : dernier jour de la formation, bloc 7 dépasse son budget après cap +
backward redistribution.

**Cause possible** :
- Volume excessif sur le dernier jour (LLM a sur-généré)
- Effet domino du carryover (chaque jour précédent a déchargé un peu, accumulé
  jusqu'au dernier)

**Détection** : log warning de `_reduce_last_bloc_to_budget` ; si même la
réduction LLM échoue, ValueError remonte → `auto_pilot_error`.

**Récup** : intervention manuelle — ajuster les segments en amont (réduire le
volume_safety target, ou demander un re-shorten via LLM sur des segments
spécifiques).

### 2. Paragraphe trop gros pour rentrer dans un budget

**Quand** : le LLM produit un paragraphe de 800-1200 mots d'un coup, et le bloc
suivant n'a pas la place de l'absorber lors d'une backward redistribution.

**Symptôme** : un bloc finit avec un gros gap (ex. 4 min) parce que le seul
paragraphe disponible dans le bloc N+1 est trop volumineux pour être tiré.

**Détection** : log warning du closing ("gap > 240s", registre "long" déclenché
en cascade). Combiné avec la passe 2 qui ne fait rien, ça signale ce cas.

**Récup** : pas critique — le closing comble pédagogiquement le gap. Mais à
terme, on peut ajouter dans les prompts une consigne "génère des paragraphes de
150-300 mots max" pour limiter ces cas.

### 3. Calibration Fish Audio fausse en prod

**Quand** : la valeur empirique `_TTS_REFERENCE_WPM_AT_095 = 192` est différente
de la valeur réelle à `speed=0.90`.

**Symptôme** : si la voix Fish Audio est plus lente que prévu, les blocs
"corrects en estimation" durent plus longtemps que la cible → pré-check
rejette plus souvent que prévu.

**Détection** : taux d'échec du pré-check anormalement élevé sur les premières
journées de prod.

**Récup** : recalibrer **`_TTS_REFERENCE_WPM_AT_095`** (jamais la `speed`).
Mesurer empiriquement : durée audio réelle / nombre de mots sur une journée
test. Ajuster jusqu'à ce que la formule colle.

Cf. `02-problemes/pipeline-52-jours-risques-residuels.md` (R1).

### 4. Closing trop générique ou hors-ton

**Quand** : le LLM reçoit `prev_excerpt` de 200 mots et `next_excerpt` de 200
mots, mais c'est insuffisant pour produire un récap précis.

**Symptôme** : closings du genre *"On a vu beaucoup de choses, prenez un
moment pour intégrer"* — vrai mais générique. L'apprenant comprend que c'est
une transition automatique.

**Détection** : à l'écoute. Pas de signal automatique.

**Récup** : élargir `prev_excerpt` à 300-400 mots (au coût de prompts plus
longs). Renforcer le prompt avec des contre-exemples ("ne dis pas X, dis Y").

### 5. Closing qui ajoute une idée nouvelle

**Quand** : le LLM, en générant un closing, "invente" une notion ou annonce
quelque chose qui n'est pas dans le cours suivant.

**Symptôme** : *"Demain, on verra comment l'IA peut automatiser tout ça"* —
phrase ajoutée par le LLM sans qu'on ait demandé d'inventer le futur.

**Détection** : à l'écoute, ou via un grep sur les closings stockés (si un
audit est fait).

**Récup** : renforcer le prompt avec *"NE PAS annoncer de notion qui n'est pas
dans le `next_excerpt` fourni"*. Logger les closings pour audit.

### 6. Régénération partielle qui rate des dépendances

**Quand** : un seul segment change → il devient `dirty` → mais le découpage en
7 blocs peut faire que d'AUTRES blocs voient leur contenu modifié (cascade du
cap budget).

**Symptôme** : un bloc "propre" qui reste à dirty=0 alors que son texte a
changé → vieil audio servi avec le nouveau texte invisible (incohérence).

**Détection** : audit du contenu vs audio en blob Azure.

**Récup** : la logique actuelle marque `dirty=True` sur tout bloc dont les
contributing_seg_indices changent. À surveiller que cette logique tient sur
des cas de redistribution backward + carryover combinés.

### 7. Bloc suivant affaibli par redistribution

**Quand** : la backward redistribution tire trop de paragraphes du bloc N+1 →
bloc N+1 devient lui-même sous-rempli.

**Symptôme** : effet cascade — bloc N+1 doit alors tirer du bloc N+2, qui à son
tour tire du N+3...

**Détection** : log de redistribution montre plusieurs paragraphes tirés en
chaîne sur des blocs successifs.

**Récup** : pas critique — chaque bloc reste sous son budget. Mais ajoute un
risque cumulatif sur le bloc 7 (si toute la cascade arrive jusqu'à lui). Le
seuil `_BACKWARD_UNDERSHOOT_THRESHOLD_SEC = 30` limite déjà l'agressivité.

### 8. Trop de closings sur une journée

**Quand** : tous les blocs 1-7 finissent avec un gap > 45s → 7 closings
LLM concaténés sur une journée.

**Symptôme** : la journée entière sonne "bavarde", chaque bloc se termine par
"on a vu, on va voir, prenez un moment". Apprenant lassé.

**Détection** : à l'écoute d'une journée complète, pas isolé bloc par bloc.

**Récup** : varier les templates short_closing (déjà en place via cycle). Pour
les closings LLM, varier les prompts par bloc (ne pas demander la même
structure aux 7 blocs).

### 9. Ordre saisonnier autour du bloc 4

**Quand** : la `pause_midi` change de position selon mode hiver/été (cf.
`/schedule-config`). Le closing du bloc 4 ne sait pas si la pause arrive
juste après ou après le Q&A.

**Symptôme** : closing qui dirait *"on se retrouve après le déjeuner pour..."*
en mode hiver, faux en été (le déjeuner vient PLUS TARD en été).

**Détection** : à l'écoute.

**Récup** : éviter les références temporelles précises dans les closings du
bloc 3 et du bloc 4. Le prompt actuel ne pose pas cette contrainte
explicitement — à ajouter si on observe le cas.

### 10. Coût LLM cumulé

**Quand** : 364 blocs × ~50 % de closings LLM × ~2 000 tokens d'entrée + 500
de sortie = ~450 000 tokens d'I/O par RNCP côté closings.

**Estimation** : sur Sonnet 4, ~$2-3 par RNCP rien que pour les closings.
Couplé aux 5 salves de review (4 680 appels × ~3 000 tokens) = ~$50-100 par
RNCP au total côté review + closings.

**Détection** : suivre la facturation Anthropic mensuelle.

**Récup** : si la facture monte, ajouter un cache DB sur les closings (cf.
mémo `04-solutions/closing-bloc-cours-contextuel.md`, section "Pourquoi pas de
cache DB pour V1"). Ou dégrader certains gaps moyens en templates.

### 11. Carryover qui s'accumule en cascade

**Quand** : jour 1 reporte 2 min vers jour 2. Jour 2 reporte 2 min vers jour 3.
... Au jour 52, on a accumulé 50+ minutes de report.

**Détection** : monitoring du `carryover_in_text` — si sa taille croît jour
après jour.

**Récup** : volume_safety doit être recalibré en amont. Le rebalancing LLM du
dernier jour attrape le cas extrême mais c'est un palliatif.

### 12. Heartbeat eventlet bloqué pendant TTS Fish Audio

**Quand** : `convert_to_speech` envoie un POST HTTP qui bloque eventlet sans
yielder pendant > 5 min (TTL du lock auto-pilot).

**Symptôme** : un autre worker considère le job comme abandonné, prend le
lock, double TTS en parallèle.

**Détection** : doublons en blob Azure (peu probable car upload est
idempotent), ou doublons de facturation Fish Audio.

**Récup** : vérifier `eventlet.monkey_patch()` au boot (si activé, `requests`
yield correctement).

Cf. `02-problemes/pipeline-52-jours-risques-residuels.md` (R5).

## Recommandations de monitoring

| Métrique à surveiller | Outil | Seuil d'alerte |
|---|---|---|
| Taux d'échec pré-check Fish Audio | Logs auto-pilot | > 2 % |
| Distribution des gaps closings | Log structuré (à ajouter) | Médiane > 60 s |
| Distribution des carryover (mots/jour) | Query DB | > 1 500 mots récurrent |
| Closings hors-ton (audit qualitatif) | Écoute hebdo | Subjectif |
| Coût Anthropic cumulé par RNCP | Facturation | > $100 |
| Facturation Fish Audio par RNCP | Facturation | Doublons inexpliqués |

## Observabilité actuelle (manquante)

- **Pas de log structuré** des closings générés (texte, gap, registre, bloc).
- **Pas de dashboard** sur les carryover (volume, fréquence, jour le plus
  affecté).
- **Pas de tagging** des MP3 cours pour distinguer "avec closing LLM" vs
  "sans closing".

À ajouter en V2 si le système de monitoring devient pertinent.

## Leçons / Pour le mémoire

- **Un système robuste a des modes d'échec connus.** Lister les cas
  pathologiques avant la prod, c'est plus efficace que les découvrir un par
  un en post-mortem.

- **La probabilité de chaque cas pris isolément est faible, mais la somme
  n'est pas négligeable.** Sur 52 jours et une dizaine de modes d'échec, il
  est probable qu'AU MOINS un se déclenche. Le système doit avoir une voie
  de récupération pour chacun, ou au moins un signal détectable.

- **L'éditorial est un cas pathologique légitime.** Cas 4 (closing générique),
  cas 5 (closing qui invente), cas 9 (closing saisonnier inadéquat) sont des
  défaillances pédagogiques, pas techniques. Elles ne plantent pas la
  pipeline, mais dégradent la qualité finale. À surveiller activement à
  l'écoute, pas via logs.

- **La cascade des fallbacks n'est pas gratuite.** Chaque mécanisme ajouté
  (carryover, closing, redistribution) ouvre un nouveau cas pathologique
  potentiel. La complexité doit être contrebalancée par un effort
  d'observabilité — sinon on a des bugs invisibles.

- **L'observabilité doit être pensée tôt.** Les "à ajouter en V2" risquent de
  ne jamais arriver une fois la pipeline en prod et stable. Mieux :
  instrumenter dès la mise en prod, pour avoir des données immédiatement.
