import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

test('keeps teacher tools inside one workspace without an archive action', async () => {
  const dashboardSource = await readFile(
    new URL('../../src/pages/HRDashboard.jsx', import.meta.url),
    'utf8',
  )
  const coursesSource = await readFile(
    new URL('../../src/components/CoursFolders.jsx', import.meta.url),
    'utf8',
  )

  assert.doesNotMatch(dashboardSource, />\s*Archiver\s*</)
  assert.doesNotMatch(dashboardSource, /function CardToolModal/)
  assert.match(dashboardSource, /function TeacherToolPanel/)
  assert.match(dashboardSource, /const \[activeTool, setActiveTool\] = useState\(null\)/)
  assert.match(dashboardSource, /activeTool === 'students'/)
  assert.match(dashboardSource, /activeTool === 'attendance'/)
  assert.match(dashboardSource, /<AudiosModal[\s\S]*?embedded/)
  assert.match(dashboardSource, /<PDFModal[\s\S]*?embedded/)
  assert.match(dashboardSource, /<CourseTimeModal[\s\S]*?embedded/)
  assert.match(dashboardSource, /<CoursFoldersModal[\s\S]*?embedded/)
  assert.match(dashboardSource, /max-w-3xl/)
  assert.match(dashboardSource, /sm:w-1\/2/)
  assert.doesNotMatch(dashboardSource, /max-w-\[1180px\]/)
  assert.match(coursesSource, /embedded = false/)
  assert.match(coursesSource, /embedded \? 'h-full min-h-0 w-full'/)
})
