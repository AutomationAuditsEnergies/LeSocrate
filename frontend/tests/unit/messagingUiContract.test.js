import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const testDir = path.dirname(fileURLToPath(import.meta.url))
const srcDir = path.resolve(testDir, '../../src')
const dashboard = fs.readFileSync(path.join(srcDir, 'pages/HRDashboard.jsx'), 'utf8')
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
})

test('gives the internal admin a protected validation inbox and API credit links', () => {
  assert.match(app, /path="\/admin\/validations"/)
  assert.match(adminValidations, /api\/admin\/teacher-order-validations/)
  assert.match(adminValidations, /Fish Audio/)
  assert.match(adminValidations, /DeepSeek/)
  assert.match(adminValidations, /Accepter et envoyer le paiement/)
})
