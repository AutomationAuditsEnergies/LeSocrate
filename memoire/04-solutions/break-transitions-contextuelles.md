# Solution : transitions Q&A et pauses contextuelles

**Date** : 2026-05-04  
**Statut** : implémenté  
**Fichiers** :
- `backend/services/break_transition_service.py`
- `backend/services/closing_transition_service.py`
- `backend/services/content_generation_service.py`
- `backend/services/playlist_tts_service.py`
- `backend/routes/hr_routes.py`

---

## Contexte

Une journée de cours est découpée en fichiers MP3 horodatés : blocs cours, Q&A,
pauses courtes et pause déjeuner. Avant cette solution, les fichiers Q&A/pauses
pouvaient être recyclés depuis le container `audioqapause`, avec des phrases
génériques.

Le résultat était fonctionnel, mais la continuité audio restait mécanique : un
bloc cours pouvait être bien reformulé, puis le fichier suivant repartait sur une
phrase neutre sans lien clair avec ce qui venait d'être vu.

## Problème

Le closing contextuel du bloc cours ne doit pas annoncer toute la logistique du
fichier suivant. Il doit seulement clôturer proprement la partie pédagogique :
"on s'arrête ici pour cette partie", avec une petite ouverture.

Ensuite, le fichier Q&A ou pause porte sa propre fonction :
- intro Q&A : annonce du temps de questions, mention du chat, rappel bref du thème
  précédent ;
- outro Q&A : clôture des questions et transition vers la suite ;
- intro pause : annonce courte de la pause ;
- outro pause : "la pause est terminée" puis raccord vers le prochain cours ;
- pause déjeuner : intro sobre, sans résumé du matin.

## Solution

Un service dédié `break_transition_service.py` génère pour chaque break une paire
`(intro, outro)` à partir des extraits adjacents :
- fin du cours précédent ;
- début du prochain cours ;
- type de fichier (`qa`, `pause`, `pause_midi`) ;
- durée du slot ;
- type d'élément qui suit ;
- indicateur dernier break de la journée.

Le service appelle le LLM avec une réponse attendue en JSON :

```json
{
  "intro": "texte d'intro",
  "outro": "texte d'outro"
}
```

Si l'appel LLM échoue ou retourne un contenu inexploitable, le service retombe sur
des fallbacks statiques distincts par type de break.

## Règles audio

Le cours ne dit plus explicitement "questions", "pause" ou "chat" dans son
closing. Ces mots sont interdits dans les prompts de `closing_transition_service.py`
pour éviter la redondance avec le fichier suivant.

Le fichier Q&A annonce le temps de questions et le chat dans son intro. Il ne fait
pas semblant de répondre aux apprenants : le silence central reste le vrai temps
laissé aux questions.

Le fichier pause annonce seulement la pause en intro. Son outro porte la reprise :
"La pause est terminée. On reprend..." avec une transition contextualisée.

La pause déjeuner est traitée à part. Son intro ne reçoit pas le contexte du matin,
pour éviter une phrase du type "après avoir vu X..." avant une coupure longue. Son
outro reste également neutre, car le fichier doit fonctionner en mode été comme en
mode hiver.

## Neutralité été/hiver

Une partie de la playlist change d'ordre selon le mode de la plateforme :

- `hiver` : pause déjeuner → cours bloc 4 → Q&A bloc 4
- `ete` : cours bloc 4 → Q&A bloc 4 → pause déjeuner

Comme les MP3 sont persistants au niveau du module, ils doivent rester valables
après un changement de mode. On ne peut donc pas laisser ces fichiers annoncer
explicitement l'élément suivant.

Fichiers traités comme sensibles :
- `pause_12h10_12h20.mp3` : son outro ne doit pas annoncer le prochain cours,
  car en hiver la pause déjeuner peut arriver juste après.
- `qa_13h05_13h15.mp3` : son outro ne doit pas annoncer ni pause déjeuner ni
  cours suivant, car son voisin suivant change selon le mode.
- `pause_midi_13h15_14h45.mp3` : intro et outro restent neutres, sans référence
  au bloc précédent ni au thème suivant.

Le service expose `is_schedule_neutral_break(filename)` pour centraliser cette
liste. Elle est appliquée dans `build_break_transition_texts()` avant l'appel à
`generate_break_transition()`.

La construction des transitions est factorisée dans
`build_break_transition_texts()`. Cette fonction :
- trouve le cours précédent et le cours suivant dans la playlist effective ;
- extrait la fin du cours précédent et le début du cours suivant ;
- applique la neutralité été/hiver si nécessaire ;
- appelle `generate_break_transition()`.

Les callers injectent seulement `get_bloc_text(bloc_num) -> str`, car les deux
pipelines ne stockent pas les blocs dans la même structure (`dict["text"]` dans le
chemin actif, string directe dans le chemin legacy).

Le cours `cours_12h20_13h05.mp3` est aussi dans la zone mobile, mais son closing
est protégé côté `closing_transition_service.py` : il ne doit pas annoncer la
logistique de playlist ni présenter la notion suivante comme l'audio immédiatement
lu.

## Durées

La durée du fichier est connue au moment de générer le MP3, car les breaks sont
créés pendant la génération audio, après construction de la playlist effective.

`duration_label()` ne mentionne une durée que si elle est fiable :
- `300` -> `cinq minutes`
- `420` -> `sept minutes`
- `600` -> `dix minutes`
- `720` -> `douze minutes`
- `900` -> `quinze minutes`
- `>= 3600` ou `pause_midi` -> `pause déjeuner`

Si la durée n'est pas exprimable proprement, le prompt demande explicitement de ne
pas mentionner de durée précise.

## Câblage

Chemin actif `/formation-pipeline` :
- `content_generation_service.generate_audio_from_script()` génère les cours et les
  breaks dans le préfixe playlist du dossier.
- La playlist utilisée vient de la plateforme, donc elle respecte le mode `hiver`
  ou `ete`.
- Le mode mock reste inchangé : les breaks ne sont pas générés.

Chemin legacy :
- `playlist_tts_service.generate_playlist_for_folder()` utilise aussi le service
  contextuel.
- Il lit maintenant la playlist effective de la plateforme au lieu de toujours
  utiliser `PLAYLIST_SPEC`.
- En cas d'échec de génération contextuelle ou TTS, il retombe sur `audioqapause`.

Remplissage vers le planning :
- `hr_routes.fill_from_folder()` copie d'abord les MP3 générés dans le dossier.
- Le fallback `audioqapause` ne sert plus que pour les fichiers Q&A/pause absents.

## Décisions

Le container `audioqapause` est conservé comme fallback, pas comme source principale
quand une playlist contextuelle existe.

Le wiki Obsidian n'a pas été modifié depuis ce repo : `CLAUDE.md` indique que
`wiki/` vit dans le vault externe et ne doit pas être résolu relativement au projet.
