const CRCD_PATTERN = /\b(?:tp\s*)?crcd\b|conseill(?:er|ère).*relation client.*distance/i

export function buildTeacherDescription(trainingName = '') {
  const title = String(trainingName || '').trim().replace(/\s+/g, ' ')
  if (title.length < 3) return ''

  if (CRCD_PATTERN.test(title)) {
    return 'Spécialisé dans le titre professionnel Conseiller relation client à distance, ce professeur accompagne les apprenants dans la maîtrise de la relation client, des outils multicanaux et des situations professionnelles à distance.'
  }

  return `Spécialisé dans la formation ${title}, ce professeur accompagne les apprenants avec un parcours structuré, des exemples professionnels et des mises en pratique adaptées au titre préparé.`
}
