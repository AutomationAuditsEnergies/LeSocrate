// Audit de débordement des slides : charge le banc overflow-test.html,
// mesure le DOM (scrollWidth/scrollHeight, data-fit-overflow, ellipses)
// et screenshote chaque cas en anomalie.
import { chromium } from 'playwright'
import fs from 'node:fs'

const BASE = process.env.BENCH_URL || 'http://127.0.0.1:5173/overflow-test.html'
const OUT = '/tmp/slide-audit'
fs.mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1040, height: 900 } })
await page.goto(BASE, { waitUntil: 'networkidle' })
await page.waitForTimeout(1500)

const report = await page.evaluate(() => {
  const results = []
  document.querySelectorAll('.case').forEach((caseEl) => {
    const index = caseEl.dataset.caseIndex
    const label = caseEl.querySelector('.case-label')?.textContent?.trim() || index
    const stage = caseEl.querySelector('.pipeline-slide-preview-stage')
    if (!stage) return
    const stageRect = stage.getBoundingClientRect()
    const issues = []

    stage.querySelectorAll('*').forEach((el) => {
      if (el.children.length > 0 && !el.matches('h1,h2,h3,p,li,span')) return
      const text = (el.textContent || '').trim()
      if (!text) return

      if (/…$/.test(text) || /\.\.\.$/.test(text)) {
        // ellipse en fin de texte = suspect (sauf dialogues volontaires)
        issues.push({ kind: 'ellipsis', tag: el.tagName, text: text.slice(-60) })
      }
      const horiz = el.scrollWidth > el.clientWidth + 4
      const vert = el.scrollHeight > el.clientHeight + 14
      if (horiz || vert) {
        issues.push({
          kind: 'scroll-overflow',
          tag: el.tagName,
          cls: el.className?.toString?.().slice(0, 60),
          sw: el.scrollWidth, cw: el.clientWidth,
          sh: el.scrollHeight, ch: el.clientHeight,
          text: text.slice(0, 60),
        })
      }
      const rect = el.getBoundingClientRect()
      if (rect.right > stageRect.right + 4 || rect.bottom > stageRect.bottom + 4 || rect.left < stageRect.left - 4) {
        issues.push({
          kind: 'outside-stage',
          tag: el.tagName,
          cls: el.className?.toString?.().slice(0, 60),
          text: text.slice(0, 60),
        })
      }

      // Texte rogné par un ancêtre overflow:hidden (ex : tableau du template
      // story) — invisible pour les checks scroll/stage car le clipping est
      // local au conteneur.
      let ancestor = el.parentElement
      while (ancestor && ancestor !== stage) {
        const overflow = getComputedStyle(ancestor).overflow
        if (overflow === 'hidden' || overflow === 'clip') {
          const aRect = ancestor.getBoundingClientRect()
          if (
            rect.top < aRect.top - 4
            || rect.bottom > aRect.bottom + 4
            || rect.left < aRect.left - 4
            || rect.right > aRect.right + 4
          ) {
            issues.push({
              kind: 'clipped-by-ancestor',
              tag: el.tagName,
              cls: el.className?.toString?.().slice(0, 60),
              ancestorCls: ancestor.className?.toString?.().slice(0, 60),
              text: text.slice(0, 60),
            })
            break
          }
        }
        ancestor = ancestor.parentElement
      }
    })

    stage.querySelectorAll('[data-fit-overflow="true"]').forEach((el) => {
      issues.push({ kind: 'fit-floor-overflow', cls: el.className?.toString?.().slice(0, 60), text: (el.textContent || '').slice(0, 60) })
    })

    results.push({ index, label, issueCount: issues.length, issues })
  })
  return results
})

let bad = 0
for (const entry of report) {
  if (entry.issueCount > 0) {
    bad += 1
    const caseEl = page.locator(`[data-case-index="${entry.index}"]`)
    await caseEl.scrollIntoViewIfNeeded()
    await page.waitForTimeout(120)
    await caseEl.screenshot({ path: `${OUT}/case-${entry.index}.png` })
  }
}

fs.writeFileSync(`${OUT}/report.json`, JSON.stringify(report, null, 1))
console.log(`cases=${report.length} with_issues=${bad}`)
for (const entry of report.filter((r) => r.issueCount > 0)) {
  console.log(`\n#${entry.index} ${entry.label}`)
  for (const issue of entry.issues.slice(0, 6)) console.log('  -', JSON.stringify(issue))
}

await browser.close()
