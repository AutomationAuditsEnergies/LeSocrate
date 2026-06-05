/* eslint-disable react-refresh/only-export-components */
import {
  DeckCaseStudy,
  DeckChapterOpener,
  DeckComparison,
  DeckDayProgram7Steps,
  DeckDefinition,
  DeckPause,
  DeckProcess,
  DeckProgramYear,
  DeckQA,
  DeckQuote,
  DeckRecap,
  DeckStatement,
  DeckTip,
  DeckWarning,
  DeckWelcome,
} from './templates/DeckTemplates'

export const COMMON_SLIDE_PROPS = {
  badge: 'TP-CRCD',
  brandName: 'SALES HACKING',
}

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
  opinion: 'reflection',
  transition: 'reflection',
  analogy: 'reflection',
  metaphor: 'reflection',
  paradox: 'reflection',
  definition: 'definition',
  comparison: 'comparison',
  'comparison-ternary': 'comparison',
  beforeafter: 'comparison',
  chart: 'comparison',
  matrix: 'comparison',
  diagnostic: 'comparison',
  warning: 'warning',
  mistake: 'warning',
  risk: 'warning',
  casestudy: 'casestudy',
  case: 'casestudy',
  example: 'casestudy',
  story: 'casestudy',
  scenario: 'casestudy',
  profiles: 'casestudy',
  script: 'casestudy',
  steps: 'steps',
  'steps-mini': 'steps',
  facilitator: 'steps',
  process: 'steps',
  method: 'steps',
  framework: 'steps',
  channel: 'steps',
  escalation: 'steps',
  toolkit: 'steps',
  decisiontree: 'steps',
  learningpath: 'steps',
  selfmanagement: 'steps',
  exercise: 'steps',
  recap: 'recap',
  checklist: 'recap',
  takeaways: 'recap',
  stats: 'recap',
  data: 'recap',
  numbers: 'recap',
  signals: 'recap',
  signalradar: 'recap',
  temperature: 'recap',
  kpi: 'recap',
  selfdiag: 'recap',
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
  context: 'context',
}

export const normalizeSlideType = (type, data = {}) => {
  const key = String(type || '').trim().toLowerCase()
  if (key === 'day_program') {
    return Array.isArray(data.items) && data.items.length === 7 ? 'day_program_7_steps' : 'program_year'
  }
  if (key === 'agenda') {
    return Array.isArray(data.items) && data.items.length === 7 ? 'day_program_7_steps' : 'steps'
  }
  return ALIASES[key] || 'reflection'
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

  if (canonicalType === 'steps' && !Array.isArray(data.steps)) {
    const steps = normalizeItems(data.items || data.segments || data.phases || data.points, 4)
    return { ...data, steps: steps.length ? steps : data.steps }
  }

  if (canonicalType === 'recap' && !Array.isArray(data.points)) {
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
    return { ...data, points: points.filter(Boolean).slice(0, 4) }
  }

  return data
}

function ContextSlidePreview({
  formation_name,
  chapter,
  label,
  badge = COMMON_SLIDE_PROPS.badge,
  brandName = COMMON_SLIDE_PROPS.brandName,
}) {
  return (
    <div style={{
      width: '100%',
      height: '100%',
      background: '#f8fafc',
      color: '#0f172a',
      fontFamily: 'Inter, system-ui, sans-serif',
      display: 'flex',
      flexDirection: 'column',
      padding: '36px 44px',
      boxSizing: 'border-box',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: '#64748b', fontSize: '16px', fontWeight: 800 }}>
        <span>{badge}</span>
        <span>{brandName}</span>
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
        <div style={{ color: '#dc2626', fontSize: '18px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '18px' }}>
          {label || 'Séquence en cours'}
        </div>
        <div style={{ fontSize: '42px', lineHeight: 1.08, fontWeight: 900, maxWidth: '820px' }}>
          {formation_name || 'Formation'}
        </div>
        <div style={{ marginTop: '24px', height: '3px', width: '88px', background: '#dc2626', borderRadius: '999px' }} />
        <div style={{ marginTop: '24px', fontSize: '28px', lineHeight: 1.25, fontWeight: 800, color: '#334155', maxWidth: '780px' }}>
          {chapter || 'Chapitre en cours'}
        </div>
      </div>
    </div>
  )
}

export function renderSlideTemplate(slide = {}, extraProps = {}) {
  const originalType = slide.template_type || slide.type || ''
  const data = slide.data || {}
  const canonicalType = normalizeSlideType(originalType, data)
  const props = {
    ...normalizeRegistryData(canonicalType, originalType, data),
    ...COMMON_SLIDE_PROPS,
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
    case 'steps':
      return <DeckProcess {...props} />
    case 'recap':
      return <DeckRecap {...props} />
    case 'pause':
      return <DeckPause {...props} />
    case 'qa':
      return <DeckQA {...props} />
    case 'quotable':
      return <DeckQuote {...props} />
    case 'tip':
      return <DeckTip {...props} />
    case 'context':
      return <ContextSlidePreview {...props} />
    case 'reflection':
    default:
      return <DeckStatement {...props} />
  }
}
