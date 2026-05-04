# Claude Code subprocess tape sur l'API à la carte au lieu du forfait

**Date** : 2026-04-28
**Thématique** : problème
**Statut** : résolu

## Contexte

Le projet permet d'exécuter certaines étapes du pipeline (KB, programme global, programmes journée, génération cours, révision) via la CLI Claude Code locale plutôt que via l'API Anthropic à la carte. Motivation : le forfait Claude Code Pro/Max permet d'épargner les crédits API à l'unité quand le compte API est bas ou vide.

Tout l'orchestrateur subprocess est centralisé dans `claude_code_mission_service.py:_run_subprocess` qui spawne `claude -p ... --model <id> --dangerously-skip-permissions --output-format stream-json` via `subprocess.Popen`.

## Problème

L'utilisateur a déclenché "Exécuter avec Claude Code" sur l'étape KB pour économiser ses crédits API (compte API vide depuis quelques heures). Le subprocess remonte un échec :

- **UI** : `Échec : Claude Code returncode=1`. Log de fin : `"output_tokens":0,"iterations":[],"modelUsage":{}` → la CLI a démarré mais aucun appel modèle n'a été effectué.
- **execution.log** :
  ```json
  "apiKeySource":"ANTHROPIC_API_KEY"
  ...
  "text":"Credit balance is too low"
  "error":"billing_error"
  "api_error_status":400
  ```

Donc la CLI Claude Code a vu la variable `ANTHROPIC_API_KEY` dans l'environnement parent (héritée par défaut par `subprocess.Popen`) et l'a utilisée comme source d'authentification, **bypassant le forfait OAuth stocké localement**. Comme le compte API à la carte est vide → `billing_error` immédiat avant tout appel modèle.

Côté UI, c'est très déroutant : l'utilisateur a explicitement cliqué sur "Exécuter avec Claude Code" (colonne forfait local) et constate qu'il consomme quand même son budget API.

## Cause racine

Comportement standard de la CLI Claude Code : **si `ANTHROPIC_API_KEY` est définie, elle prend la priorité sur le login OAuth du forfait**. C'est documenté chez Anthropic mais n'est pas évident quand on automatise la CLI depuis un service Python.

Le `subprocess.Popen` Python hérite par défaut de l'env du process parent (notre Flask), qui contient `ANTHROPIC_API_KEY` parce que les services API du même projet en ont besoin (`utils/anthropic_client.py:post_message`).

Donc dès qu'on lance un subprocess CLI depuis ce backend, on tape sur l'API à la carte sans le savoir.

## Options envisagées

**A.** Demander à l'utilisateur de retirer `ANTHROPIC_API_KEY` de son `.env` — rejeté : le mode API a besoin de la variable, on ne peut pas l'enlever globalement.

**B.** Lancer le subprocess avec un env nettoyé (sans `ANTHROPIC_API_KEY` ni `ANTHROPIC_AUTH_TOKEN`) → CLI retombe sur le login OAuth du forfait. **Retenue.**

**C.** Utiliser une option CLI explicite type `--no-api-key` — pas dispo dans la version 2.1.121 (ou dans tous les cas, B est plus robuste car indépendant des changements d'option CLI).

## Décision

Modifier `_run_subprocess` :

```python
child_env = os.environ.copy()
for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
    child_env.pop(k, None)
proc = subprocess.Popen(cmd, cwd=cwd, ..., env=child_env)
```

Tous les subprocess CLI passent par cette fonction (KB, global, daily, content chunks, review chunks, volume safety) → un seul fix corrige toutes les étapes en mode local.

## Rationale

Le subprocess doit représenter exactement l'environnement d'un utilisateur qui taperait `claude` dans son terminal **sans avoir exporté `ANTHROPIC_API_KEY`** : c'est le mode "forfait" par défaut, c'est ce que l'utilisateur attend quand il clique "Exécuter avec Claude Code". L'env strip rend cette équivalence explicite.

## Pré-requis

Pour que le fix marche, l'utilisateur doit avoir un token OAuth valide stocké localement (typiquement dans `~/.claude/`). Ça se fait en lançant `claude` dans un terminal une fois et en faisant `/login` au prompt. Sans login, le subprocess échouera avec une erreur "not authenticated" — ce qui est attendu et un signal clair à l'utilisateur.

## Références code

- `backend/services/claude_code_mission_service.py:_run_subprocess` — env strip avant Popen
- `backend/utils/anthropic_client.py:post_message` — utilise toujours `ANTHROPIC_API_KEY` (mode API), inchangé

## Leçons

1. **Subprocess et héritage d'env est un piège classique** quand on automatise une CLI tierce qui a sa propre logique de credentials. Toujours expliciter `env=` avec le strict nécessaire.
2. **Logs structurés stream-json sont précieux** — le diagnostic ici a pris 2 minutes parce que `apiKeySource` était dans le payload `init`. Sans ça, on aurait passé 30 min à deviner.
3. **Distinguer les budgets dans le UI** est une chose ; les distinguer dans le code en est une autre. Le UI promet "forfait local" → le code doit garantir que le subprocess utilise effectivement le forfait, pas seulement par espoir.
4. **Pattern réutilisable** : pour toute intégration de CLI tierce dans un service web, créer un helper `_clean_subprocess_env(strip_keys=...)` qui matérialise quelles vars sont retirées, et le réutiliser pour tous les `subprocess.Popen`.
