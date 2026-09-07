function audioBasename(name) {
  const normalized = String(name || '').replaceAll('\\', '/')
  return normalized.split('/').filter(Boolean).at(-1) || normalized
}
function audioKind(name) {
  const basename = audioBasename(name).toLowerCase()
  if (/^(cours|course)(?:[_-]|$)/.test(basename)) return 'courses'
  if (/^(pause|break)(?:[_-]|$)/.test(basename)) return 'pauses'
  if (/^(qa|qr|q-r|questions?[_-]?r[eé]ponses?)(?:[_-]|$)/.test(basename)) return 'questions'
  return 'other'
}

export function classifyFormationAudios(audios) {
  const groups = {
    courses: [],
    pauses: [],
    questions: [],
    other: [],
  }

  for (const audio of Array.isArray(audios) ? audios : []) {
    if (!audio || typeof audio !== 'object') continue
    const name = String(audio.name || '').trim()
    if (!name) continue
    groups[audioKind(name)].push({
      ...audio,
      name,
      displayName: audioBasename(name),
    })
  }

  return groups
}
