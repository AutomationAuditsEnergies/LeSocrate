import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const dashboardSource = readFileSync(
  new URL('../../src/pages/HRDashboard.jsx', import.meta.url),
  'utf8',
)

test('smoothly keeps the latest recruitment exchange above the composer', () => {
  assert.match(dashboardSource, /scrollArea\.scrollTo\(\{/)
  assert.match(
    dashboardSource,
    /behavior: prefersReducedMotionRef\.current \? 'auto' : 'smooth'/,
  )
  assert.match(dashboardSource, /h-\[clamp\(72px,14vh,144px\)\]/)
  assert.doesNotMatch(
    dashboardSource,
    /scrollArea\.scrollTop = scrollArea\.scrollHeight/,
  )
})
