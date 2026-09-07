/* eslint-disable react-refresh/only-export-components */
import {
  DeckCaseStudy,
  DeckChapterOpener,
  DeckComparison,
  DeckAnalogy,
  DeckDayProgram7Steps,
  DeckDefinition,
  DeckFlow,
  DeckFramework,
  DeckOpinion,
  DeckPause,
  DeckProcess,
  DeckProgramYear,
  DeckQA,
  DeckQuote,
  DeckRecap,
  DeckRepriseRecap,
  DeckSituations,
  DeckStatement,
  DeckStory,
  DeckTip,
  DeckWarning,
  DeckWelcome,
} from './templates/DeckTemplates'

export const COMMON_SLIDE_PROPS = {
  badge: 'TP-CRCD',
  brandName: 'LE SOCRATE',
}

export const OFFICIAL_SOURCE_TEMPLATE_IDS = new Set([
  'welcome',
  'program_year',
  'day_program_7_steps',
  'chapter_opener',
  'reflection',
  'definition',
  'comparison',
  'warning',
  'casestudy',
  'situations',
  'steps',
  'recap',
  'reprise_recap',
  'pause',
  'qa',
  'quotable',
  'tip',
  'flow',
  'story',
  'analogy',
  'framework',
  'opinion',
])

const ALIASES = {
  welcome: 'welcome',
  day_welcome: 'welcome',
  opening: 'welcome',
  program_year: 'program_year',
  day_year: 'program_year',
  annual_program: 'program_year',
  parcours_annuel: 'program_year',
  day_program_7_steps: 'day_program_7_steps',
  program_7_steps: 'day_program_7_steps',
  roadmap_7_steps: 'day_program_7_steps',
  chapter_opener: 'chapter_opener',
  chapter_intro: 'chapter_opener',
  theme_opening: 'chapter_opener',
  reflection: 'reflection',
  concept: 'reflection',
  key_message: 'reflection',
  opinion: 'opinion',
  transition: 'reflection',
  analogy: 'analogy',
  metaphor: 'analogy',
  paradox: 'reflection',
  definition: 'definition',
  comparison: 'comparison',
  'comparison-ternary': 'comparison',
  beforeafter: 'comparison',
  synchrone_asynchrone: 'comparison',
  synchronous_asynchronous: 'comparison',
  canaux_synchrones: 'comparison',
  canaux_asynchrones: 'comparison',
  deux_familles: 'comparison',
  chart: 'comparison',
  matrix: 'reflection',
  diagnostic: 'comparison',
  situations: 'situations',
  situation: 'situations',
  three_situations: 'situations',
  trois_piliers: 'situations',
  piliers: 'situations',
  triade: 'situations',
  triptyque: 'situations',
  trepied: 'situations',
  trépied: 'situations',
  flow: 'flow',
  request_flow: 'flow',
  warning: 'warning',
  mistake: 'warning',
  risk: 'warning',
  casestudy: 'casestudy',
  case: 'casestudy',
  example: 'casestudy',
  story: 'story',
  scenario: 'casestudy',
  profiles: 'situations',
  script: 'story',
  steps: 'steps',
  'steps-mini': 'steps',
  facilitator: 'flow',
  process: 'steps',
  method: 'steps',
  framework: 'framework',
  channel: 'casestudy',
  timeline: 'steps',
  escalation: 'steps',
  toolkit: 'recap',
  decisiontree: 'reflection',
  decision_tree: 'reflection',
  learningpath: 'steps',
  selfmanagement: 'tip',
  exercise: 'steps',
  practice_exercise: 'steps',
  recap: 'recap',
  reprise: 'reprise_recap',
  reprise_recap: 'reprise_recap',
  opening_recap: 'reprise_recap',
  rappel: 'reprise_recap',
  checklist: 'recap',
  takeaways: 'recap',
  stats: 'recap',
  data: 'recap',
  numbers: 'recap',
  signals: 'warning',
  signalradar: 'warning',
  temperature: 'comparison',
  kpi: 'recap',
  selfdiag: 'reflection',
  pause: 'pause',
  qa: 'qa',
  quotable: 'quotable',
  'quotable-2': 'quotable',
  quote: 'quotable',
  journal: 'quotable',
  tip: 'tip',
  advice: 'tip',
  good_practice: 'tip',
  playful: 'reflection',
  gradient: 'reflection',
  learning_path: 'steps',
  self_management: 'tip',
  signal_radar: 'warning',
  channel_adaptation: 'casestudy',
  chronology: 'steps',
  chronologie: 'steps',
  escalation_ladder: 'steps',
  temperature_scale: 'comparison',
  kpi_explainer: 'recap',
  self_diag: 'reflection',
  context: 'reflection',
}

const countVisualItems = (data = {}) => {
  for (const key of ['cases', 'items', 'points', 'profiles', 'scenes']) {
    if (Array.isArray(data[key])) return data[key].length
  }
  return 0
}

const flattenSlideText = (value) => {
  if (value == null) return ''
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  if (Array.isArray(value)) return value.map(flattenSlideText).join(' ')
  if (typeof value === 'object') return Object.values(value).map(flattenSlideText).join(' ')
  return ''
}

const hasAdviceSignal = (data = {}) => {
  const text = flattenSlideText(data).toLowerCase()
  return [
    'astuce',
    'conseil',
    'réflexe',
    'reflexe',
    'à adopter',
    'a adopter',
    'faire table rase',
    'micro-pause',
    'micro pause',
    'respirez',
    'dites-vous',
    'je ne sais rien de ce client',
    'écoute neuve',
    'ecoute neuve',
    'ce qu’il faut retenir',
    "ce qu'il faut retenir",
  ].some((signal) => text.includes(signal))
}

const hasTwoFamilyComparisonSignal = (data = {}) => {
  const text = flattenSlideText(data).toLowerCase()
  const hasSyncPair = text.includes('synchrone') && text.includes('asynchrone')
  const hasTwoFamilySignal = [
    'deux grandes familles',
    'deux familles',
    'deux modes',
    'deux canaux',
    "d'un côté",
    'de l’autre côté',
    "de l'autre côté",
  ].some((signal) => text.includes(signal))
  const hasExpectationContrast = [
    'réaction immédiate',
    'reaction immediate',
    'réponse complète',
    'reponse complete',
    'temps réel',
    'temps reel',
    'temps différé',
    'temps differe',
    'rapidité',
    'rapidite',
    'exhaustivité',
    'exhaustivite',
    'autoportante',
  ].some((signal) => text.includes(signal))
  return hasSyncPair || (hasTwoFamilySignal && hasExpectationContrast)
}

export const normalizeSlideType = (type, data = {}) => {
  const key = String(type || '').trim().toLowerCase()
  const itemCount = Array.isArray(data.items) ? data.items.length : 0
  const isDynamicDayProgram = itemCount >= 4 && itemCount <= 10
  if (key === 'day_program') {
    return isDynamicDayProgram ? 'day_program_7_steps' : 'program_year'
  }
  if (key === 'agenda') {
    return isDynamicDayProgram ? 'day_program_7_steps' : 'steps'
  }
  const canonical = ALIASES[key] || 'reflection'
  if (canonical !== 'comparison' && hasTwoFamilyComparisonSignal(data)) {
    return 'comparison'
  }
  if (canonical === 'casestudy' && countVisualItems(data) < 2) {
    return hasAdviceSignal(data) ? 'tip' : 'story'
  }
  return OFFICIAL_SOURCE_TEMPLATE_IDS.has(canonical) ? canonical : 'reflection'
}

const textFrom = (...values) => values.map((value) => String(value || '').trim()).find(Boolean) || ''

const normalizeItems = (items, limit = 4) => {
  if (!Array.isArray(items)) return []
  return items.slice(0, limit).map((item, index) => {
    if (typeof item === 'string') {
      return { title: item, desc: '' }
    }
    return {
      title: textFrom(item?.title, item?.label, item?.name, `Point ${index + 1}`),
      desc: textFrom(item?.desc, item?.description, item?.text, item?.detail),
      tag: textFrom(item?.tag, item?.label),
      example: textFrom(item?.example, item?.quote),
    }
  })
}

const normalizeTextList = (items, limit = 4) => {
  if (!Array.isArray(items)) return []
  return items
    .map((item, index) => {
      if (typeof item === 'string') return item
      return textFrom(item?.title, item?.label, item?.text, item?.desc, item?.description, `Point ${index + 1}`)
    })
    .filter(Boolean)
    .slice(0, limit)
}

const normalizeRegistryData = (canonicalType, originalType, data) => {
  const original = String(originalType || '').trim().toLowerCase()

  if (canonicalType === 'reflection') {
    const text = textFrom(
      data.text,
      data.takeaway,
      data.moral,
      data.description,
      data.narrative,
      data.subtitle,
      data.to_topic,
    )
    return {
      ...data,
      title: textFrom(data.title, data.concept_label, data.concept, data.to_topic, 'Idée à retenir'),
      text,
      eyebrow: textFrom(data.eyebrow, original === 'transition' ? 'Transition' : 'Principe clé'),
    }
  }

  if (canonicalType === 'casestudy' && !Array.isArray(data.cases)) {
    const cases = normalizeItems(data.items || data.profiles || data.scenes || data.steps, 6)
    if (cases.length) {
      return { ...data, cases }
    }
    return {
      ...data,
      cases: [{
        tag: textFrom(data.tag, '01 · Situation'),
        title: textFrom(data.title, 'Cas terrain'),
        desc: textFrom(data.narrative, data.text, data.description),
        example: textFrom(data.moral, data.example, data.quote),
      }],
    }
  }

  if (canonicalType === 'comparison' && !Array.isArray(data.cols)) {
    if (hasTwoFamilyComparisonSignal(data)) {
      return {
        ...data,
        title: textFrom(data.title, 'Deux logiques'),
        cols: [
          {
            label: 'Canaux synchrones',
            items: ['Temps réel', 'Réactivité immédiate', "Maintenir le lien pendant l'échange"],
          },
          {
            label: 'Canaux asynchrones',
            items: ['Temps différé', 'Réponse complète', 'Message autonome'],
          },
        ],
      }
    }
    const cols = normalizeItems(data.columns || data.items || data.points, 2).map((item, index) => ({
      label: item.title || `Option ${index + 1}`,
      items: [item.desc || item.example || item.title].filter(Boolean),
    }))
    if (cols.length >= 2) {
      return { ...data, cols }
    }
  }

  if (canonicalType === 'steps' && !Array.isArray(data.steps)) {
    const steps = normalizeItems(data.items || data.segments || data.phases || data.points, 4)
    return { ...data, steps: steps.length ? steps : data.steps }
  }

  if (canonicalType === 'facilitator' && !Array.isArray(data.steps)) {
    const steps = normalizeItems(data.items || data.segments || data.phases || data.points, 4)
    return { ...data, steps: steps.length ? steps : data.steps }
  }

  if (canonicalType === 'flow' && !Array.isArray(data.steps)) {
    const steps = normalizeItems(data.items || data.segments || data.phases || data.points, 4)
    return { ...data, steps: steps.length ? steps : data.steps }
  }

  if (canonicalType === 'framework' && !Array.isArray(data.segments)) {
    const segments = normalizeItems(data.items || data.points || data.steps, 6)
    return {
      ...data,
      center: data.center || { title: textFrom(data.center_title, data.core, data.topic, 'Point central') },
      segments: segments.length ? segments : data.segments,
    }
  }

  if (canonicalType === 'situations' && !Array.isArray(data.items)) {
    const items = normalizeItems(data.cases || data.profiles || data.scenes || data.points, 3)
    return { ...data, items }
  }

  if (canonicalType === 'story') {
    return {
      ...data,
      title: textFrom(data.title, data.event_summary, 'Cas terrain'),
      narrative: textFrom(data.narrative, data.text, data.description),
      moral: textFrom(data.moral, data.takeaway, data.quote),
    }
  }

  if (canonicalType === 'analogy') {
    return {
      ...data,
      title: textFrom(data.title, 'Analogie'),
      concept: textFrom(data.concept, data.term, data.a, 'Concept'),
      comparison: textFrom(data.comparison, data.image, data.metaphor, data.b, 'Image mentale'),
      text: textFrom(data.text, data.description, data.explanation),
    }
  }

  if (canonicalType === 'opinion') {
    return {
      ...data,
      title: textFrom(data.title, data.claim, 'Point de vue'),
      text: textFrom(data.text, data.description, data.takeaway),
    }
  }

  if (canonicalType === 'tip') {
    const firstCase = Array.isArray(data.cases) ? data.cases[0] : null
    const firstItem = Array.isArray(data.items) ? data.items[0] : null
    return {
      ...data,
      title: textFrom(data.title, firstCase?.title, firstItem?.title, 'Conseil pratique'),
      text: textFrom(
        data.text,
        data.description,
        data.takeaway,
        firstCase?.example,
        firstCase?.desc,
        firstCase?.description,
        firstItem?.desc,
        firstItem?.description,
      ),
    }
  }

  if (canonicalType === 'transition') {
    return {
      ...data,
      title: textFrom(data.title, data.to_topic, 'On passe à la pratique'),
      from_topic: textFrom(data.from_topic, data.from, data.previous),
      to_topic: textFrom(data.to_topic, data.to, data.next),
    }
  }

  if (canonicalType === 'stats' && !Array.isArray(data.stats)) {
    const stats = normalizeItems(data.items || data.points || data.columns, 4).map((item, index) => ({
      number: item.title || String(index + 1),
      label: item.desc || item.title,
    }))
    return { ...data, stats }
  }

  if (canonicalType === 'checklist' && !Array.isArray(data.points)) {
    return { ...data, points: normalizeTextList(data.items || data.checklist || data.steps, 5) }
  }

  if ((canonicalType === 'recap' || canonicalType === 'reprise_recap') && !Array.isArray(data.points)) {
    const points = []
    if (Array.isArray(data.columns)) {
      points.push(...data.columns.map((item) => textFrom(item)))
    }
    if (Array.isArray(data.stats)) {
      points.push(...data.stats.map((item) => {
        if (typeof item === 'string') return item
        return textFrom(`${item?.number || item?.value || ''} ${item?.label || ''}`.trim())
      }))
    }
    if (Array.isArray(data.items)) {
      points.push(...data.items.map((item) => (typeof item === 'string' ? item : textFrom(item?.title, item?.label, item?.text))))
    }
    if (Array.isArray(data.checklist)) {
      points.push(...data.checklist.map((item) => (typeof item === 'string' ? item : textFrom(item?.title, item?.label, item?.text, item?.desc))))
    }
    if (Array.isArray(data.steps)) {
      points.push(...data.steps.map((item) => (typeof item === 'string' ? item : textFrom(item?.title, item?.label, item?.text, item?.desc))))
    }
    return { ...data, points: points.filter(Boolean).slice(0, 4) }
  }

  return data
}

export function renderSlideTemplate(slide = {}, extraProps = {}) {
  const originalType = slide.template_type || slide.type || ''
  const data = slide.data || {}
  const canonicalType = normalizeSlideType(originalType, data)
  const props = {
    ...normalizeRegistryData(canonicalType, originalType, data),
    ...COMMON_SLIDE_PROPS,
    ...(slide.brand_name ? { brandName: slide.brand_name } : {}),
    ...extraProps,
  }

  switch (canonicalType) {
    case 'welcome':
      return <DeckWelcome {...props} />
    case 'program_year':
      return <DeckProgramYear {...props} />
    case 'day_program_7_steps':
      return <DeckDayProgram7Steps {...props} />
    case 'chapter_opener':
      return <DeckChapterOpener {...props} />
    case 'definition':
      return <DeckDefinition {...props} />
    case 'comparison':
      return <DeckComparison {...props} />
    case 'warning':
      return <DeckWarning {...props} />
    case 'casestudy':
      return <DeckCaseStudy {...props} />
    case 'story':
      return <DeckStory {...props} />
    case 'steps':
      return <DeckProcess {...props} />
    case 'flow':
      return <DeckFlow {...props} />
    case 'framework':
      return <DeckFramework {...props} />
    case 'recap':
      return <DeckRecap {...props} />
    case 'reprise_recap':
      return <DeckRepriseRecap {...props} />
    case 'analogy':
      return <DeckAnalogy {...props} />
    case 'opinion':
      return <DeckOpinion {...props} />
    case 'situations':
      return <DeckSituations {...props} />
    case 'pause':
      return <DeckPause {...props} />
    case 'qa':
      return <DeckQA {...props} />
    case 'quotable':
      return <DeckQuote {...props} />
    case 'tip':
      return <DeckTip {...props} />
    case 'reflection':
    default:
      return <DeckStatement {...props} />
  }
}
