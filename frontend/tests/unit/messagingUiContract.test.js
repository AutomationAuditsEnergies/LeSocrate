import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const testDir = path.dirname(fileURLToPath(import.meta.url))
const srcDir = path.resolve(testDir, '../../src')
const dashboard = fs.readFileSync(path.join(srcDir, 'pages/HRDashboard.jsx'), 'utf8')
const reviewInbox = fs.readFileSync(path.join(srcDir, 'components/TeacherOrderReviewInbox.jsx'), 'utf8')
const adminValidations = fs.readFileSync(path.join(srcDir, 'pages/AdminValidations.jsx'), 'utf8')
const app = fs.readFileSync(path.join(srcDir, 'App.jsx'), 'utf8')

test('adds a durable center messaging tab backed by authenticated APIs', () => {
  assert.match(dashboard, /id: 'messages', label: 'Messagerie'/)
  assert.match(dashboard, /api\/hr\/messages/)
  assert.match(dashboard, /Suivez ici la validation et la préparation de vos professeurs/)
  assert.doesNotMatch(dashboard, /Demande concernée/)
  assert.doesNotMatch(dashboard, /<Mail size=\{19\}/)
  assert.match(dashboard, /formatScheduleDateTime\(selected\.updated_at\)/)
  assert.match(dashboard, /\{selected\.body\}[\s\S]*\{selected\.title\}/)
  assert.match(dashboard, /selected\.action === 'payment'/)
  assert.match(dashboard, /api\/hr\/billing\/orders\/\$\{message\.order_id\}\/checkout/)
  assert.match(dashboard, /'Ouverture…' : 'Payer'/)
})

test('gives the internal admin a protected validation inbox and API credit links', () => {
  assert.match(app, /path="\/admin\/validations"/)
  assert.match(adminValidations, /api\/admin\/teacher-order-validations/)
  assert.match(adminValidations, /Fish Audio/)
  assert.match(adminValidations, /DeepSeek/)
  assert.match(adminValidations, /Accepter et envoyer le paiement/)
})

test('lets only platform operators validate other centers from their messaging tab', () => {
  assert.doesNotMatch(dashboard, /newpiprod@gmail\.com/)
  assert.match(dashboard, /PLATFORM_OPERATOR_PERMISSIONS = \['platform_operator'\]/)
  assert.match(dashboard, /apiFetch\('\/api\/admin\/session'\)/)
  assert.match(dashboard, /orderReviewCenter \? \(\s*<TeacherOrderReviewInbox/)
  assert.match(reviewInbox, /api\/admin\/teacher-order-validations/)
  assert.match(reviewInbox, /pour les autres centres/)
  assert.match(reviewInbox, /training_weeks/)
  assert.match(reviewInbox, /training_days/)
  assert.match(reviewInbox, /Recharger Fish Audio/)
  assert.match(reviewInbox, /Recharger DeepSeek/)
  assert.match(reviewInbox, /DeepSeek V4 Flash/)
  assert.match(reviewInbox, /DeepSeek V4 Pro/)
  assert.match(reviewInbox, /pipeline_model: pipelineModel/)
  assert.match(reviewInbox, /Valider et envoyer le paiement/)
})
