import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('../../src/pages/HRDashboard.jsx', import.meta.url),
  'utf8',
)
test('submits teacher orders for review before opening Stripe Checkout', () => {
  assert.match(source, /data\.next_action === 'pending_review'/)
  assert.match(source, /Demande envoyée/)
  assert.match(source, /Votre demande a bien été envoyée à nos équipes/)
  assert.match(source, /Veuillez consulter votre messagerie/)
})

test('still follows a hosted Stripe Checkout URL returned by the backend', () => {
  assert.match(source, /data\.next_action === 'redirect' && data\.checkout_url/)
  assert.match(source, /window\.location\.assign\(data\.checkout_url\)/)
})

test('reconciles the browser success redirect with Stripe on the server', () => {
  assert.match(source, /checkoutSessionId = params\.get\('session_id'\)/)
  assert.match(source, /teacher-orders\/\$\{orderId\}\/confirm-payment/)
  assert.match(source, /Stripe confirme actuellement votre paiement/)
  assert.match(source, /order\.payment_status === 'paid'/)
})

test('lets the user open the paid teacher from the confirmation notice', () => {
  assert.doesNotMatch(source, /checkout === 'success'[\s\S]{0,240}setWorkspaceSection\('teachers'\)/)
  assert.match(source, /setNewlyCreatedPlatformId\(order\.platform_id\)/)
  assert.match(source, /action: 'view_teacher'/)
  assert.match(source, /Voir le professeur/)
  assert.match(source, /orderNotice\.action === 'view_teacher'[\s\S]*setWorkspaceSection\('teachers'\)/)
  assert.doesNotMatch(source, /TeacherArrivalAnimation/)
})

test('stops tracking cancelled, failed, expired, or refunded payments', () => {
  assert.match(source, /checkout === 'cancelled'[\s\S]*setActiveTeacherOrderId\(null\)/)
  assert.match(source, /\['failed', 'expired'\]\.includes\(order\.payment_status\)/)
  assert.match(source, /order\.payment_status === 'refunded'/)
})

test('sends the Lyon account directly to payment without validation', () => {
  assert.match(source, /billing\?\.review_required === false \? 'Tarif à régler maintenant'/)
  assert.match(source, /billing\.review_required === false \? 'Continuer vers le paiement'/)
  assert.match(source, /data\.next_action === 'redirect' && data\.checkout_url/)
})
