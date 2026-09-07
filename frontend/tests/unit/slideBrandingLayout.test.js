import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const deckStyles = readFileSync(
  new URL('../../src/components/slides/templates/DeckTemplates.css', import.meta.url),
  'utf8',
)

const ruleBody = (selector) => {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = deckStyles.match(new RegExp(`${escapedSelector}\\s*\\{([^}]+)\\}`))
  assert.ok(match, `Règle CSS introuvable : ${selector}`)
  return match[1]
}

test('keeps the complete slide brand when the available chrome has enough room', () => {
  const brand = ruleBody('.deck-brand')
  const head = ruleBody('.deck-brand-mark')
  const tail = ruleBody('.deck-brand-tag')

  assert.match(brand, /min-width:\s*0/)
  assert.match(head, /flex:\s*0 1 auto/)
  assert.match(tail, /flex:\s*0 1 auto/)
  assert.doesNotMatch(head, /max-width:\s*42%/)
  assert.doesNotMatch(tail, /max-width:\s*58%/)
})
