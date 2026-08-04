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
  assert.doesNotMatch(dashboardSource, /activeTool === 'pdf'/)
  assert.doesNotMatch(dashboardSource, /key: 'pdf'/)
  assert.match(dashboardSource, /<CourseTimeModal[\s\S]*?embedded/)
  assert.match(dashboardSource, /<CoursFoldersModal[\s\S]*?embedded/)
  assert.match(dashboardSource, /max-w-3xl/)
  assert.match(dashboardSource, /sm:w-1\/2/)
  assert.doesNotMatch(dashboardSource, /max-w-\[1180px\]/)
  assert.match(coursesSource, /embedded = false/)
  assert.match(coursesSource, /embedded \? 'h-full min-h-0 w-full'/)
  assert.match(dashboardSource, /activeTool \? 'hidden' : 'flex min-h-\[430px\]'/)
  assert.doesNotMatch(dashboardSource, /activeTool \? 'hidden sm:flex'/)
  assert.doesNotMatch(dashboardSource, /absolute left-5 top-5[\s\S]*?rosterMeta\.label/)
  assert.match(coursesSource, /Support PDF de la journée/)
  assert.match(coursesSource, /Support PDF prêt/)
  assert.match(coursesSource, /fin de la pipeline/)
  assert.doesNotMatch(coursesSource, /avec les audios à H-48/)
  assert.match(coursesSource, /course-materials/)
})
