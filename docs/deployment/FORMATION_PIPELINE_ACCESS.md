# Accès à la pipeline de formation

`/formation-pipeline` est une capacité explicite d'un compte centre. Une
session `legacy_admin`, un centre désactivé ou un centre sans permission est
refusé côté API, même si son ancien jeton d'authentification est encore valide.

Le premier déploiement de la colonne accorde la permission au compte existant
`newpiprod@gmail.com`. Les déploiements suivants ne réappliquent pas cette
décision et respectent donc toute révocation ultérieure.

Lors d'une migration depuis l'ancienne base SQLite, seules les plateformes
encore sans propriétaire et déjà référencées par un job de pipeline sont
rattachées à ce compte. Une migration rejouée conserve également une révocation
déjà présente dans PostgreSQL ; aucune autre plateforme n'est attribuée par
déduction. Le bootstrap s'interrompt si plusieurs comptes correspondent à cet
e-mail sans tenir compte de la casse.

Depuis l'environnement backend Formation3 :

```bash
python tools/access/set_pipeline_access.py \
  --username newpiprod@gmail.com \
  --grant
```

Pour révoquer immédiatement l'accès :

```bash
python tools/access/set_pipeline_access.py \
  --username newpiprod@gmail.com \
  --revoke
```
