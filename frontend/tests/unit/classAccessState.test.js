import assert from 'node:assert/strict'
import test from 'node:test'

import { getClassAccessFailure } from '../../src/classAccessState.js'

test('explains a genuinely unknown class without exposing an HTTP error', () => {
  assert.deepEqual(getClassAccessFailure(404), {
    kind: 'not-found',
    title: 'Votre classe est introuvable',
    message: 'Vérifiez le lien transmis par votre centre de formation.',
    action: 'home',
  })
})

test('explains a class that has not been published yet', () => {
  assert.equal(
    getClassAccessFailure(403).title,
    'Votre classe n’est pas encore accessible',
  )
})

test('turns network and server failures into a retryable learner message', () => {
  for (const status of [undefined, 0, 500, 503]) {
    const failure = getClassAccessFailure(status)
    assert.equal(failure.kind, 'unavailable')
    assert.equal(failure.action, 'retry')
    assert.doesNotMatch(`${failure.title} ${failure.message}`, /failed to fetch|cors|http|api/i)
  }
})
