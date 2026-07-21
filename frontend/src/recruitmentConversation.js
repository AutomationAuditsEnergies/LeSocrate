const normalizeText = (value) => String(value || '')
  .normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '')
  .toLowerCase()
  .replace(/[^a-z0-9\s]/g, ' ')
  .replace(/\s+/g, ' ')
  .trim()

const UNCERTAIN_ANSWER = /^(je ne sais pas|j sais pas|jsp|aucune idee|n importe quoi|comme vous voulez|peu importe|a voir|autre)$/
const GENERIC_TRAINING_WORDS = new Set([
  'un', 'une', 'le', 'la', 'les', 'de', 'des', 'du', 'en', 'pour', 'sur',
  'formation', 'formations', 'cours', 'programme', 'parcours',
  'long', 'longue', 'court', 'courte', 'general', 'generale',
  'professionnel', 'professionnelle', 'complete', 'complet',
  'certifiant', 'certifiante', 'qualifiant', 'qualifiante',
])

export function validateRecruitmentAnswer(stepId, rawValue) {
  const value = String(rawValue || '').trim().replace(/\s+/g, ' ')
  const normalized = normalizeText(value)

  if (!value) {
    return { valid: false, message: 'J’ai besoin d’une réponse pour continuer.' }
  }

  if (stepId === 'teacherName') {
    const isGeneric = UNCERTAIN_ANSWER.test(normalized)
      || /\b(professeur|enseignant|formateur|robot|ia)\b/.test(normalized)
    if (value.length < 2 || isGeneric) {
      return {
        valid: false,
        message: 'J’ai besoin d’un prénom ou d’un nom pour identifier ce professeur, par exemple « Pierre » ou « Sofia ».',
      }
    }
  }

  if (stepId === 'trainingName') {
    const specificWords = normalized
      .split(' ')
      .filter((word) => word.length >= 3 && !GENERIC_TRAINING_WORDS.has(word))
    if (UNCERTAIN_ANSWER.test(normalized) || specificWords.length === 0) {
      return {
        valid: false,
        message: `« ${value} » décrit le format ou la durée, mais pas le sujet de la formation. Donnez-moi son intitulé précis, par exemple « TP Conseiller relation client à distance » ou « Développeur web ».`,
      }
    }
  }

  if (stepId === 'rncpCode' && !/^\d{4,6}$/.test(normalized)) {
    return {
      valid: false,
      message: 'Le code RNCP doit contenir entre 4 et 6 chiffres, par exemple « 35304 ». Vérifiez le code puis réessayez.',
    }
  }

  if (stepId === 'trainingDays') {
    const days = Number(normalized)
    if (!Number.isInteger(days) || days < 1 || days > 365) {
      return {
        valid: false,
        message: 'Indiquez un nombre de journées compris entre 1 et 365.',
      }
    }
  }

  return { valid: true, value }
}

export function applyKnownRncpTraining(draft, modules, rncpCode) {
  const normalizedCode = String(rncpCode || '').replace(/\D/g, '')
  const matchingModule = modules.find((module) => (
    String(module.rncp_code || '').replace(/\D/g, '') === normalizedCode
  ))

  return {
    draft: {
      ...draft,
      rncpCode: normalizedCode,
      trainingName: matchingModule?.tp_name || draft.trainingName,
    },
    matchingModule,
  }
}
