import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const readSource = relativePath => readFile(
  new URL(`../../src/${relativePath}`, import.meta.url),
  'utf8',
)

test('routes protected course and schedule requests through apiFetch', async () => {
  const [coursesSource, scheduleSource] = await Promise.all([
    readSource('components/CoursFolders.jsx'),
    readSource('pages/ScheduleConfig.jsx'),
  ])

  for (const source of [coursesSource, scheduleSource]) {
    assert.match(source, /apiFetch/)
    assert.doesNotMatch(source, /\bfetch\s*\(/)
    assert.doesNotMatch(source, /\bapiUrl\s*\(/)
  }

  assert.match(coursesSource, /apiDownload/)
  assert.doesNotMatch(coursesSource, /window\.open\s*\(/)
})

test('keeps raw fetch limited to the external audio URL', async () => {
  const audioSource = await readSource('components/AudioEditor.jsx')
  const rawFetchCalls = [...audioSource.matchAll(/\bfetch\s*\(/g)]

  assert.equal(rawFetchCalls.length, 1)
  assert.match(audioSource, /async function fetchAudioBlob\(url,/)
  assert.match(
    audioSource,
    /async function fetchProtectedAudioBlob\(path,[\s\S]*?apiFetch\(path,/,
  )
  assert.doesNotMatch(audioSource, /apiRequestHeaders/)
  assert.doesNotMatch(audioSource, /\bapiUrl\s*\(/)
})

test('awaits Supabase headers before every protected fetch', async () => {
  const apiSource = await readSource('api.js')

  assert.match(
    apiSource,
    /headers:\s*await apiRequestHeaders\(path,\s*fetchOptions\.headers \|\| \{\}\)/,
  )
  assert.match(apiSource, /Authorization:\s*`Bearer \$\{supabaseAccessToken\}`/)
})
