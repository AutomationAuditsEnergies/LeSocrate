import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../../src/pages/LoginCentre.jsx', import.meta.url), 'utf8')
const apiSource = readFileSync(new URL('../../src/api.js', import.meta.url), 'utf8')
const supabaseSource = readFileSync(new URL('../../src/supabaseClient.js', import.meta.url), 'utf8')
const appSource = readFileSync(new URL('../../src/App.jsx', import.meta.url), 'utf8')

test('uses email-first copy throughout center authentication', () => {
  assert.match(source, /'Email' : 'Adresse email'/)
  assert.doesNotMatch(source, /Email ou identifiant/)
  assert.doesNotMatch(source, />Identifiant</)
  assert.doesNotMatch(source, /Accéder au tableau de bord/)
  assert.match(source, /Se connecter/)
})

test('opens a dedicated single-field forgot-password state', () => {
  assert.match(source, /setForgotPasswordMode\(true\)/)
  assert.match(source, /Vous recevrez un email avec un lien pour créer ou réinitialiser votre mot de passe en toute sécurité\./)
  assert.match(source, /Veuillez entrer votre adresse email/)
  assert.match(source, /resetLoading \? 'Envoi en cours…' : 'Valider'/)
  assert.match(source, /Retour à la connexion/)
  assert.doesNotMatch(source, /dans le champ identifiant/)
})

test('resumes a valid center session instead of showing the login form again', () => {
  assert.match(source, /supabaseClient\.auth\.getSession\(\)/)
  assert.match(source, /apiFetch\('\/api\/admin\/session'/)
  assert.match(source, /response\.ok && data\.authenticated/)
  assert.match(source, /navigate\('\/dashboard-centre', \{ replace: true \}\)/)
  assert.match(source, /<AppLoader label="Reprise de votre session" \/>/)
})

test('uses the Supabase session for center login and Flask API calls', () => {
  assert.match(source, /auth\.signInWithPassword\(\{/)
  assert.match(source, /email,\s*password:/)
  assert.match(apiSource, /Authorization: `Bearer \$\{supabaseAccessToken\}`/)
  assert.match(supabaseSource, /autoRefreshToken: true/)
  assert.match(supabaseSource, /persistSession: true/)
})

test('returns protected center pages to login when Supabase ends the session', () => {
  assert.match(apiSource, /socrate:center-session-expired/)
  assert.match(appSource, /onAuthStateChange/)
  assert.match(appSource, /event === 'SIGNED_OUT'/)
  assert.match(appSource, /navigate\('\/connexion-centre', \{ replace: true \}\)/)
})

test('keeps recovery and explicit signup flows accessible', () => {
  assert.match(source, /initialPasswordRecoveryMode \|\| initialAuthMode !== 'login'/)
  assert.match(source, /setCheckingExistingSession\(false\)/)
})

test('offers an explicit passwordless entry point only in local development', () => {
  assert.match(source, /import\.meta\.env\.DEV/)
  assert.match(source, /apiFetch\('\/api\/admin\/dev-login'/)
  assert.match(source, /Accéder sans compte/)
})
