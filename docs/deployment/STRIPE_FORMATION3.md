# Stripe sur Formation3

## Règle de prix

Le backend calcule le montant, jamais le navigateur :

- coût de production provisoire : `15 €` par journée ;
- nouveau professeur IA : `15 € × 2 = 30 €` par journée ;
- réutilisation : `15 € × 1,5 = 22,50 €` par journée ;
- montant Stripe : tarif journalier × nombre de journées.

Le workflow Formation3 configure `AI_TEACHER_COST_PER_DAY_CENTS=1500`. Modifier
cette valeur suffit pour faire évoluer les deux tarifs en conservant les mêmes
multiplicateurs.

## Secrets GitHub

Dans GitHub : **Settings → Secrets and variables → Actions → New repository secret**.

Ajouter :

1. `SAAS_STRIPE_SECRET_KEY` : clé secrète Stripe `sk_live_...` (ou `sk_test_...` pendant les essais).
2. `SAAS_STRIPE_WEBHOOK_SECRET` : secret de signature `whsec_...` du webhook ci-dessous.

Ne jamais mettre ces valeurs dans un fichier du dépôt ou dans le frontend.

## Webhook Stripe

Dans Stripe : **Developers / Workbench → Webhooks → Add destination**.

- URL : `https://formation3-cpdhezh4cdcqecfy.francecentral-01.azurewebsites.net/api/billing/stripe/webhook`
- événements :
  - `checkout.session.completed`
  - `checkout.session.async_payment_succeeded`
  - `checkout.session.async_payment_failed`
  - `checkout.session.expired`
  - `charge.refunded`

Copier ensuite le **Signing secret** `whsec_...` dans le secret GitHub
`SAAS_STRIPE_WEBHOOK_SECRET`, puis relancer le workflow Formation3.

Utiliser le même mode des deux côtés : clés `sk_test_...` avec webhook test, ou
clés `sk_live_...` avec webhook live.

Le retour navigateur `success_url` n’autorise jamais la création. Seul le
webhook signé le fait. Le backend commit dans une même transaction PostgreSQL :

1. l’événement Stripe idempotent (`event.id`) ;
2. l’autorisation de la commande et le montant réellement payé ;
3. le work item de fulfillment dans la file durable.

Un crash avant le commit ne laisse donc ni événement « consommé » ni commande
payée sans travail durable. Les événements dupliqués sont ignorés, les échecs
sont rejouables et un remboursement arrivé avant l’événement Checkout retrouve
la commande grâce aux métadonnées serveur.

### Réconciliation

Pour une commande qui reste en attente, contrôler son Checkout Session et ses
events dans Stripe Workbench, puis utiliser **Resend event** vers l’URL ci-dessus.
La même transaction idempotente réconcilie alors la commande sans créer un second
professeur. Consulter parallèlement `stripe_webhook_events.status`,
`ai_teacher_orders.payment_status` et `pipeline_work_items.status`; un event
`failed` conserve `last_error` et accepte une nouvelle livraison.

## Exemption du centre interne

Le backend exempte systématiquement l’email normalisé `newpiprod@gmail.com`, même
si l’état PostgreSQL est encore `stripe_required`. Cette règle reste côté serveur
et le navigateur ne peut pas la demander.

Pour rendre également l’exemption explicite et auditable dans PostgreSQL après
application du schéma, exécuter une fois :

```bash
DATABASE_URL='postgresql://...' venv/bin/python \
  backend/tools/billing/set_center_exemption.py \
  --username newpiprod@gmail.com \
  --grant \
  --reason "Compte interne Le Socrate" \
  --actor "deployment"
```

L’exemption est alors aussi attachée à l’identifiant PostgreSQL stable du compte.
