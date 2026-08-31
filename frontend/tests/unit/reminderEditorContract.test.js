import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const dashboardUrl = new URL('../../src/pages/HRDashboard.jsx', import.meta.url)

test('offers the personal and ordinary access paths in the predefined reminder', async () => {
  const source = await readFile(dashboardUrl, 'utf8')

  assert.match(source, /Votre cours commence le \{date\} à \{time\}/)
  assert.match(source, /\{class_url_connexion\}/)
  assert.match(source, /\{session_code\}/)
  assert.match(source, /\{class_url_accueil\}/)
})

test('lets the center restore the default and insert variables at the cursor', async () => {
  const source = await readFile(dashboardUrl, 'utf8')

  assert.match(source, /Rétablir le message par défaut/)
  assert.match(source, /selectionStart/)
  assert.match(source, /setSelectionRange/)
  assert.match(source, /Insérer :/)
  assert.match(source, /Lien personnel/)
  assert.match(source, /Code personnel/)
  assert.match(source, /Lien habituel/)
})

test('selects registered students by identity instead of displaying their email addresses', async () => {
  const source = await readFile(dashboardUrl, 'utf8')
  const reminderPanel = source.slice(
    source.indexOf('function ReminderRulesPanel'),
    source.indexOf('function InvitationsToolContent'),
  )

  assert.match(reminderPanel, /Tous les élèves inscrits/)
  assert.match(reminderPanel, /\[recipient\.prenom, recipient\.nom\]/)
  assert.match(reminderPanel, /Ajoutez d’abord un élève depuis l’onglet Élèves/)
  assert.doesNotMatch(reminderPanel, /recipient\.email/)
})

test('adds a student from a compact icon button beside the identity fields', async () => {
  const source = await readFile(dashboardUrl, 'utf8')
  const studentsPanelStart = source.indexOf('function StudentsToolContent')
  const studentsPanel = source.slice(
    studentsPanelStart,
    source.indexOf('function PlatformCard', studentsPanelStart),
  )

  assert.match(studentsPanel, /sm:grid-cols-\[1fr_1fr_1\.5fr_auto\]/)
  assert.match(studentsPanel, /aria-label="Ajouter l’élève"/)
  assert.match(studentsPanel, /className="inline-flex h-10 w-10/)
  assert.match(studentsPanel, /Prénom de l’élève/)
  assert.match(studentsPanel, /Nom de l’élève/)
  assert.match(studentsPanel, /eleve@exemple\.fr/)
  assert.doesNotMatch(studentsPanel, /Nassim|Issad|nassim@exemple\.com/i)
  assert.doesNotMatch(studentsPanel, />\s*Ajouter l’élève\s*</)
})
