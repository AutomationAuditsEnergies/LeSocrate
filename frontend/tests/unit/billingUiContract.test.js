import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('../../src/pages/HRDashboard.jsx', import.meta.url),
  'utf8',
)

test('redirects paid teacher orders to hosted Stripe Checkout', () => {
  assert.match(source, /data\.next_action === 'redirect' && data\.checkout_url/)
  assert.match(source, /window\.location\.assign\(data\.checkout_url\)/)
})

test('never treats the browser success redirect as payment confirmation', () => {
  assert.match(source, /Ce retour ne vaut pas confirmation/)
  assert.match(source, /webhook Stripe signé/)
  assert.match(source, /order\.payment_status === 'paid'/)
})

test('stops tracking cancelled, failed, expired, or refunded payments', () => {
  assert.match(source, /checkout === 'cancelled'[\s\S]*setActiveTeacherOrderId\(null\)/)
  assert.match(source, /\['failed', 'expired'\]\.includes\(order\.payment_status\)/)
  assert.match(source, /order\.payment_status === 'refunded'/)
})
