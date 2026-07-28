import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen,
  Check,
  CircleAlert,
  Clock3,
  Coffee,
  Copy,
  GripHorizontal,
  LockKeyhole,
  MessageCircleQuestion,
  PencilLine,
  Plus,
  Save,
  Search,
  Trash2,
  Utensils,
  X,
} from 'lucide-react'

import {
  addScheduleSequence,
  cloneScheduleTemplateAsDraft,
  createEmptyScheduleTemplateDraft,
  DAY_SCHEDULE_RULES,
  formatScheduleMinute,
  getScheduleStats,
  isScheduleTemplateUsed,
  parseScheduleTime,
  setSchedulePauseKind,
  updateScheduleBlockDuration,
  updateScheduleBlockStart,
  validateScheduleTemplate,
} from '../dayScheduleTemplates.js'
import {
  createDayScheduleTemplate,
  deleteDayScheduleTemplate,
  listDayScheduleTemplates,
  updateDayScheduleTemplate,
} from '../dayScheduleTemplateApi.js'
import './DayScheduleTemplates.css'

const BUTTON_BASE = 'day-schedule-focusable inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40'
const BUTTON_PRIMARY = `${BUTTON_BASE} bg-[#18181B] text-white hover:bg-black`
const BUTTON_SECONDARY = `${BUTTON_BASE} border border-[#D4D4D8] bg-white text-[#3F3F46] hover:bg-[#F4F4F5]`
const BUTTON_GHOST = `${BUTTON_BASE} text-[#52525B] hover:bg-[#F4F4F5]`
const CALENDAR_START_MINUTE = 8 * 60
const CALENDAR_MIN_END_MINUTE = 18 * 60
const CALENDAR_PIXELS_PER_MINUTE = 0.9

function TemplateState({ template }) {
  const used = isScheduleTemplateUsed(template)
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-[#D4D4D8] bg-white px-2 py-1 text-[10px] font-semibold text-[#52525B]">
      {used ? <LockKeyhole size={11} aria-hidden="true" /> : <PencilLine size={11} aria-hidden="true" />}
      {used ? 'Utilisé' : 'Modifiable'}
    </span>
  )
}

function formatDuration(minutes) {
  const value = Number(minutes || 0)
  const hours = Math.floor(value / 60)
  const remainder = value % 60
  if (!hours) return `${remainder} min`
  return remainder ? `${hours} h ${String(remainder).padStart(2, '0')}` : `${hours} h`
}

function blockPresentation(block, counters) {
  if (block.block_type === 'course') {
    counters.course += 1
    return {
      title: `Cours vocal ${counters.course}`,
      icon: BookOpen,
      kind: 'course',
    }
  }
  if (block.block_type === 'qa') {
    counters.qa += 1
    return {
      title: `Questions-réponses ${counters.qa}`,
      icon: MessageCircleQuestion,
      kind: 'qa',
    }
  }
  return {
    title: block.pause_kind === 'lunch' ? 'Pause déjeuner' : 'Pause',
    icon: block.pause_kind === 'lunch' ? Utensils : Coffee,
    kind: block.pause_kind === 'lunch' ? 'lunch' : 'pause',
  }
}

function durationBounds(block) {
  if (block.block_type === 'course') return DAY_SCHEDULE_RULES.course
  if (block.block_type === 'qa') return DAY_SCHEDULE_RULES.qa
  return block.pause_kind === 'lunch'
    ? DAY_SCHEDULE_RULES.lunchPause
    : DAY_SCHEDULE_RULES.shortPause
}

function ScheduleTimeline({
  blocks,
  readOnly,
  blockErrors,
  onBlocksChange,
  onAddSequence,
  canAddSequence,
}) {
  const adjustmentRef = useRef(null)
  const [activeResizeIndex, setActiveResizeIndex] = useState(null)
  const [dropActive, setDropActive] = useState(false)

  useEffect(() => () => {
    const adjustment = adjustmentRef.current
    if (!adjustment) return
    window.removeEventListener('pointermove', adjustment.onMove)
    window.removeEventListener('pointerup', adjustment.onEnd)
    window.removeEventListener('pointercancel', adjustment.onEnd)
  }, [])

  const updateDuration = (blockIndex, duration) => {
    const block = blocks[blockIndex]
    if (!block) return
    const bounds = durationBounds(block)
    const snapped = Math.round(Number(duration) / 5) * 5
    const constrained = Math.min(bounds.max, Math.max(bounds.min, snapped))
    onBlocksChange(updateScheduleBlockDuration(blocks, blockIndex, constrained))
  }

  const beginAdjustment = (event, blockIndex) => {
    if (readOnly) return
    event.preventDefault()
    const startY = event.clientY
    const original = blocks.map((block) => ({ ...block }))
    const initialDuration = original[blockIndex].duration_minutes
    const bounds = durationBounds(original[blockIndex])
    setActiveResizeIndex(blockIndex)

    const onMove = (pointerEvent) => {
      const deltaSteps = Math.round(
        (pointerEvent.clientY - startY) / (CALENDAR_PIXELS_PER_MINUTE * 5),
      )
      const requestedDuration = initialDuration + (deltaSteps * 5)
      const nextDuration = Math.min(bounds.max, Math.max(bounds.min, requestedDuration))
      const next = updateScheduleBlockDuration(original, blockIndex, nextDuration)
      onBlocksChange(next)
    }
    const onEnd = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onEnd)
      window.removeEventListener('pointercancel', onEnd)
      adjustmentRef.current = null
      setActiveResizeIndex(null)
    }
    adjustmentRef.current = { onMove, onEnd }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onEnd, { once: true })
    window.addEventListener('pointercancel', onEnd, { once: true })
  }

  const counters = { course: 0, qa: 0 }
  const firstBlock = blocks[0]
  const lastBlock = blocks.at(-1)
  const calendarEndMinute = Math.min(
    24 * 60,
    Math.max(CALENDAR_MIN_END_MINUTE, (lastBlock?.end_minute || CALENDAR_MIN_END_MINUTE) + 60),
  )
  const calendarMinutes = calendarEndMinute - CALENDAR_START_MINUTE
  const calendarHeight = calendarMinutes * CALENDAR_PIXELS_PER_MINUTE
  const hourMarkers = Array.from(
    { length: Math.floor(calendarMinutes / 60) + 1 },
    (_, index) => CALENDAR_START_MINUTE + (index * 60),
  )

  const handleDrop = (event) => {
    if (readOnly || !canAddSequence) return
    if (event.dataTransfer.getData('application/x-day-sequence') !== 'course-qa-pause') return
    event.preventDefault()
    setDropActive(false)
    onAddSequence()
  }

  return (
    <div
      className="day-schedule-timeline-shell"
      data-drop-active={dropActive ? 'true' : 'false'}
      onDragEnter={(event) => {
        if (readOnly || !canAddSequence) return
        if (!Array.from(event.dataTransfer.types).includes('application/x-day-sequence')) return
        event.preventDefault()
        setDropActive(true)
      }}
      onDragOver={(event) => {
        if (readOnly || !canAddSequence) return
        if (!Array.from(event.dataTransfer.types).includes('application/x-day-sequence')) return
        event.preventDefault()
        event.dataTransfer.dropEffect = 'copy'
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setDropActive(false)
      }}
      onDrop={handleDrop}
    >
      <div className="day-schedule-timeline-toolbar">
        <div className="day-schedule-calendar-heading">
          <span className="day-schedule-calendar-kicker">Calendrier</span>
          <h3>Journée de formation</h3>
        </div>
        {firstBlock && (
          <label className="day-schedule-start-control">
            <span>Début</span>
            <input
              type="time"
              step="300"
              value={formatScheduleMinute(firstBlock.start_minute)}
              disabled={readOnly}
              onChange={(event) => {
                const minute = parseScheduleTime(event.target.value)
                if (minute !== null) onBlocksChange(updateScheduleBlockStart(blocks, 0, minute))
              }}
            />
          </label>
        )}
      </div>

      <div
        className="day-schedule-calendar"
        aria-label="Déroulé de la journée"
        style={{ '--day-schedule-calendar-height': `${calendarHeight}px` }}
      >
        <div className="day-schedule-calendar-hours" aria-hidden="true">
          {hourMarkers.map((minute) => (
            <div
              key={minute}
              className="day-schedule-calendar-hour"
              style={{
                '--day-schedule-hour-top': `${(minute - CALENDAR_START_MINUTE) * CALENDAR_PIXELS_PER_MINUTE}px`,
              }}
            >
              <time>{formatScheduleMinute(minute)}</time>
              <span />
            </div>
          ))}
        </div>

        {blocks.length === 0 ? (
          <button
            type="button"
            className="day-schedule-empty-timeline"
            onClick={onAddSequence}
            disabled={readOnly || !canAddSequence}
          >
            <Plus size={16} aria-hidden="true" />
            <strong>Planifier une séquence</strong>
            <span>Glissez la carte depuis la colonne de gauche.</span>
          </button>
        ) : (
          <div className="day-schedule-calendar-events">
          {blocks.map((block, index) => {
            const presentation = blockPresentation(block, counters)
            const BlockIcon = presentation.icon
            const bounds = durationBounds(block)
            const errors = blockErrors[block.block_key] || []
            const blockHeight = Math.max(12, block.duration_minutes * CALENDAR_PIXELS_PER_MINUTE)
            const blockTop = (block.start_minute - CALENDAR_START_MINUTE) * CALENDAR_PIXELS_PER_MINUTE
            const sequenceNumber = counters.course
            const isCourse = block.block_type === 'course'
            return (
              <article
                key={block.block_key}
                className="day-schedule-calendar-event"
                data-kind={presentation.kind}
                data-invalid={errors.length ? 'true' : 'false'}
                data-resizing={activeResizeIndex === index ? 'true' : 'false'}
                data-compact={blockHeight < 34 ? 'true' : 'false'}
                title={errors.join(' ')}
                style={{
                  '--day-schedule-event-top': `${blockTop}px`,
                  '--day-schedule-event-height': `${blockHeight}px`,
                }}
              >
                <div className="day-schedule-event-copy">
                  <BlockIcon size={14} strokeWidth={1.8} aria-hidden="true" />
                  <div className="min-w-0">
                    <h3>
                      {presentation.title}
                      {isCourse && <span> · Séquence {sequenceNumber}</span>}
                    </h3>
                    <p>
                      {formatScheduleMinute(block.start_minute)} – {formatScheduleMinute(block.end_minute)}
                    </p>
                  </div>
                </div>

                {block.block_type === 'pause' && !readOnly && index < blocks.length - 1 && (
                  <button
                    type="button"
                    className="day-schedule-pause-kind"
                    onClick={() => onBlocksChange(setSchedulePauseKind(
                      blocks,
                      index,
                      block.pause_kind === 'lunch' ? 'short' : 'lunch',
                    ))}
                  >
                    {block.pause_kind === 'lunch' ? 'Déjeuner' : 'Pause courte'}
                  </button>
                )}

                {!readOnly && (
                  <button
                    type="button"
                    className="day-schedule-resize-button"
                    onPointerDown={(event) => beginAdjustment(event, index)}
                    onKeyDown={(event) => {
                      if (!['ArrowUp', 'ArrowDown'].includes(event.key)) return
                      event.preventDefault()
                      updateDuration(
                        index,
                        block.duration_minutes + (event.key === 'ArrowDown' ? 5 : -5),
                      )
                    }}
                    aria-label={`Modifier la durée de ${presentation.title}, ${bounds.min} à ${bounds.max} minutes`}
                    title={`Étirez pour régler la durée, ${bounds.min} à ${bounds.max} min`}
                  >
                    <GripHorizontal size={18} aria-hidden="true" />
                  </button>
                )}
              </article>
            )
          })}
          </div>
        )}
      </div>

      {dropActive && (
        <div className="day-schedule-drop-overlay" aria-hidden="true">
          Relâchez pour ajouter la séquence
        </div>
      )}
    </div>
  )
}

function SequencePalette({
  blocks,
  onAdd,
}) {
  const courseCount = blocks.filter((block) => block.block_type === 'course').length
  const atMaximum = courseCount >= DAY_SCHEDULE_RULES.maxCourses
  return (
    <aside className="day-schedule-palette" aria-label="Séquence à planifier">
      <div className="day-schedule-palette-title">
        <div>
          <h2>Séquence</h2>
          <p>À glisser dans le calendrier</p>
        </div>
        <span>{courseCount}/{DAY_SCHEDULE_RULES.maxCourses}</span>
      </div>

      <button
        type="button"
        className="day-schedule-add-task day-schedule-sequence-source"
        draggable={!atMaximum}
        disabled={atMaximum}
        onDragStart={(event) => {
          event.dataTransfer.effectAllowed = 'copy'
          event.dataTransfer.setData('application/x-day-sequence', 'course-qa-pause')
        }}
        onClick={onAdd}
      >
        <Plus size={15} aria-hidden="true" />
        <span>Séquence pédagogique</span>
        <small>1 h 30</small>
      </button>
    </aside>
  )
}

function TemplateList({
  templates,
  selectedId,
  loading,
  search,
  onSearchChange,
  onSelect,
  onCreate,
  onRetry,
  error,
}) {
  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('fr')
    if (!query) return templates
    return templates.filter((template) => template.name.toLocaleLowerCase('fr').includes(query))
  }, [search, templates])

  return (
    <aside className="day-schedule-library" aria-label="Bibliothèque des templates">
      <div className="border-b border-[#ECECEF] p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-[#18181B]">Bibliothèque</h2>
            <p className="mt-0.5 text-xs text-[#71717A]">{templates.length} template{templates.length > 1 ? 's' : ''}</p>
          </div>
          <button type="button" className={BUTTON_PRIMARY} onClick={onCreate}>
            <Plus size={15} aria-hidden="true" />
            Créer
          </button>
        </div>
        <label className="relative mt-3 block">
          <span className="sr-only">Rechercher un template</span>
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#71717A]" aria-hidden="true" />
          <input
            type="search"
            className="day-schedule-search pl-9"
            placeholder="Rechercher"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
          />
        </label>
      </div>

      {loading ? (
        <div className="space-y-3 p-4" aria-label="Chargement des templates">
          {[1, 2, 3].map((item) => (
            <div key={item} className="h-16 animate-pulse rounded-lg bg-[#EEEEEF]" />
          ))}
        </div>
      ) : error ? (
        <div className="p-4" role="alert">
          <p className="text-sm font-semibold text-[#18181B]">Bibliothèque indisponible</p>
          <p className="mt-1 text-xs leading-5 text-[#71717A]">{error}</p>
          <button type="button" className={`${BUTTON_SECONDARY} mt-3`} onClick={onRetry}>
            Réessayer
          </button>
        </div>
      ) : filtered.length === 0 ? (
        <div className="p-5">
          <p className="text-sm font-semibold text-[#18181B]">
            {templates.length ? 'Aucun résultat' : 'Aucun template'}
          </p>
          <p className="mt-1 text-xs leading-5 text-[#71717A]">
            {templates.length
              ? 'Modifiez votre recherche.'
              : 'Créez une première organisation de journée.'}
          </p>
        </div>
      ) : (
        <div className="day-schedule-library-list">
          {filtered.map((template) => {
            const stats = getScheduleStats(template.blocks)
            return (
              <button
                type="button"
                key={template.id}
                className="day-schedule-template-row"
                aria-current={String(template.id) === String(selectedId) ? 'true' : undefined}
                onClick={() => onSelect(template.id)}
              >
                <span className="flex items-start justify-between gap-2">
                  <span className="min-w-0 truncate text-sm font-semibold">{template.name}</span>
                  <TemplateState template={template} />
                </span>
                <span className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-[#71717A]">
                  <span>{stats.courseCount} cours</span>
                  <span>{formatDuration(stats.dayMinutes)}</span>
                  <span>{stats.blockCount} blocs</span>
                </span>
              </button>
            )
          })}
        </div>
      )}
    </aside>
  )
}

export default function DayScheduleTemplates({ onUseTemplate }) {
  const [templates, setTemplates] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [draft, setDraft] = useState(null)
  const [mode, setMode] = useState('preview')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState(null)
  const [search, setSearch] = useState('')

  const loadTemplates = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const nextTemplates = await listDayScheduleTemplates()
      setTemplates(nextTemplates)
      setSelectedId((current) => (
        nextTemplates.some((template) => String(template.id) === String(current))
          ? current
          : (nextTemplates[0]?.id ?? null)
      ))
    } catch (loadError) {
      setError(loadError.message || 'Impossible de charger les templates.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadTemplates()
  }, [loadTemplates])

  const selectedTemplate = templates.find(
    (template) => String(template.id) === String(selectedId),
  ) || null
  const visibleTemplate = mode === 'edit' ? draft : selectedTemplate
  const validation = useMemo(
    () => visibleTemplate
      ? validateScheduleTemplate(visibleTemplate)
      : { valid: false, errors: [], blockErrors: {}, stats: getScheduleStats([]) },
    [visibleTemplate],
  )

  const startCreate = () => {
    setDraft(createEmptyScheduleTemplateDraft())
    setMode('edit')
    setFeedback(null)
  }

  const startEdit = () => {
    if (!selectedTemplate || isScheduleTemplateUsed(selectedTemplate)) return
    setDraft({
      ...selectedTemplate,
      blocks: selectedTemplate.blocks.map((block) => ({ ...block })),
    })
    setMode('edit')
    setFeedback(null)
  }

  const startDuplicate = (template = selectedTemplate) => {
    if (!template) return
    setDraft(cloneScheduleTemplateAsDraft(template))
    setMode('edit')
    setFeedback(null)
  }

  const cancelEdit = () => {
    setMode('preview')
    setDraft(null)
    setFeedback(null)
  }

  const saveDraft = async () => {
    if (!draft || saving) return
    const result = validateScheduleTemplate(draft)
    if (!result.valid) {
      setFeedback({
        tone: 'error',
        message: 'Corrigez les points signalés avant d’enregistrer.',
      })
      return
    }
    setSaving(true)
    setFeedback(null)
    try {
      const saved = draft.id
        ? await updateDayScheduleTemplate(result.template)
        : await createDayScheduleTemplate(result.template)
      setTemplates((current) => {
        const exists = current.some((template) => String(template.id) === String(saved.id))
        return exists
          ? current.map((template) => String(template.id) === String(saved.id) ? saved : template)
          : [saved, ...current]
      })
      setSelectedId(saved.id)
      setMode('preview')
      setDraft(null)
      setFeedback({ tone: 'success', message: 'Template enregistré.' })
    } catch (saveError) {
      setFeedback({
        tone: 'error',
        message: saveError.message || 'Impossible d’enregistrer le template.',
      })
    } finally {
      setSaving(false)
    }
  }

  const removeTemplate = async () => {
    if (!selectedTemplate || deleting) return
    const confirmed = window.confirm(
      `Supprimer « ${selectedTemplate.name} » de la bibliothèque ? Les formations existantes conserveront leur organisation.`,
    )
    if (!confirmed) return

    setDeleting(true)
    setFeedback(null)
    try {
      await deleteDayScheduleTemplate(selectedTemplate.id)
      const remaining = templates.filter(
        (template) => String(template.id) !== String(selectedTemplate.id),
      )
      setTemplates(remaining)
      setSelectedId(remaining[0]?.id ?? null)
      setFeedback({
        tone: 'success',
        message: 'Template supprimé de la bibliothèque.',
      })
    } catch (deleteError) {
      setFeedback({
        tone: 'error',
        message: deleteError.message || 'Impossible de supprimer le template.',
      })
    } finally {
      setDeleting(false)
    }
  }

  const useTemplate = () => {
    if (!selectedTemplate) return
    window.sessionStorage.setItem('selected_day_schedule_template_id', String(selectedTemplate.id))
    setFeedback({
      tone: 'success',
      message: `« ${selectedTemplate.name} » est retenu pour la prochaine formation.`,
    })
    onUseTemplate?.(selectedTemplate)
  }

  const updateDraftBlocks = (blocks) => {
    setDraft((current) => current ? { ...current, blocks } : current)
  }

  const rules = [
    '4 à 10 cours',
    'Cours 35 à 90 min',
    'Q&R 5 à 30 min',
    'Pause 5 à 30 min',
    'Déjeuner 60 à 120 min',
    'Cours cumulés ≥ 4 h',
    'Journée ≥ 6 h',
  ]
  const showTemplateLibrary = mode === 'preview' && templates.length > 0
  const showSequencePalette = mode === 'edit'
  const hasSidePanel = showTemplateLibrary || showSequencePalette

  return (
    <section className="day-schedule-page pb-12" aria-labelledby="day-schedule-title">
      <header className="mb-6 flex flex-col justify-between gap-4 border-b border-[#ECECEF] pb-5 sm:flex-row sm:items-end">
        <div>
          <h1 id="day-schedule-title" className="text-2xl font-semibold tracking-[-0.025em] text-[#18181B]">
            Organisation des cours
          </h1>
          <p className="mt-1.5 max-w-[68ch] text-sm leading-6 text-[#52525B]">
            Préparez des journées réutilisables. Un template devient immuable dès sa première utilisation dans une formation.
          </p>
        </div>
        {mode !== 'edit' && (
          <button type="button" className={`${BUTTON_PRIMARY} shrink-0`} onClick={startCreate}>
            <Plus size={16} aria-hidden="true" />
            Créer un template
          </button>
        )}
      </header>

      {feedback && (
        <div
          className="mb-4 flex items-start gap-2 rounded-lg border border-[#D4D4D8] bg-[#F4F4F5] px-3.5 py-3 text-sm text-[#3F3F46]"
          role={feedback.tone === 'error' ? 'alert' : 'status'}
        >
          {feedback.tone === 'error'
            ? <CircleAlert size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
            : <Check size={16} className="mt-0.5 shrink-0" aria-hidden="true" />}
          <span>{feedback.message}</span>
        </div>
      )}

      <div className={`day-schedule-layout${hasSidePanel ? '' : ' day-schedule-layout--single'}${mode === 'edit' ? ' day-schedule-layout--editor' : ''}`}>
        {mode === 'edit' && visibleTemplate && (
          <div className="day-schedule-editor-header">
            <div className="day-schedule-editor-header-main">
              <div className="day-schedule-editor-name">
                <label htmlFor="day-schedule-template-name">Nom du template</label>
                <input
                  id="day-schedule-template-name"
                  className="day-schedule-name-input"
                  value={draft.name}
                  placeholder="Ex. Journée standard"
                  autoFocus={!draft.id}
                  onChange={(event) => setDraft((current) => ({
                    ...current,
                    name: event.target.value,
                  }))}
                />
                <div className="day-schedule-editor-stats">
                  <span>{validation.stats.courseCount} cours</span>
                  <span>{formatDuration(validation.stats.courseMinutes)} de cours</span>
                  <span>{formatDuration(validation.stats.dayMinutes)} d’amplitude</span>
                </div>
              </div>
              <div className="day-schedule-editor-actions">
                <button type="button" className={BUTTON_SECONDARY} onClick={cancelEdit} disabled={saving}>
                  <X size={15} aria-hidden="true" />
                  Annuler
                </button>
                <button type="button" className={BUTTON_PRIMARY} onClick={saveDraft} disabled={saving}>
                  <Save size={15} aria-hidden="true" />
                  {saving ? 'Enregistrement…' : 'Enregistrer'}
                </button>
              </div>
            </div>
            <div className="day-schedule-rule-strip" aria-label="Règles de validation">
              {rules.map((rule) => <span key={rule} className="day-schedule-rule">{rule}</span>)}
            </div>
            <div
              className="day-schedule-editor-validation"
              data-valid={validation.valid ? 'true' : 'false'}
              role={validation.valid ? 'status' : undefined}
            >
              {validation.valid
                ? <Check size={13} aria-hidden="true" />
                : <Clock3 size={13} aria-hidden="true" />}
              <strong>{validation.valid ? 'Planning conforme' : 'Planning à compléter'}</strong>
              {!validation.valid && validation.errors.length > 0 && (
                <span>
                  {validation.errors[0]}
                  {validation.errors.length > 1 ? ` + ${validation.errors.length - 1} critères` : ''}
                </span>
              )}
            </div>
          </div>
        )}

        {showTemplateLibrary && (
          <TemplateList
            templates={templates}
            selectedId={selectedId}
            loading={loading}
            search={search}
            onSearchChange={setSearch}
            onSelect={(templateId) => {
              setSelectedId(templateId)
              setMode('preview')
              setDraft(null)
              setFeedback(null)
            }}
            onCreate={startCreate}
            onRetry={loadTemplates}
            error={error}
          />
        )}
        {showSequencePalette && (
          <SequencePalette
            blocks={visibleTemplate.blocks}
            onAdd={() => updateDraftBlocks(addScheduleSequence(draft.blocks))}
          />
        )}

        <div className={`day-schedule-workspace${mode === 'edit' ? ' day-schedule-workspace--editor' : ''}`}>
          {!visibleTemplate ? (
            loading ? (
              <div className="flex min-h-80 flex-col items-center justify-center px-6 py-12 text-center" aria-live="polite">
                <div className="h-7 w-7 animate-pulse rounded-full bg-[#E4E4E7]" aria-hidden="true" />
                <p className="mt-4 text-sm font-semibold text-[#52525B]">Chargement des templates…</p>
              </div>
            ) : error ? (
              <div className="flex min-h-80 flex-col items-center justify-center px-6 py-12 text-center" role="alert">
                <CircleAlert size={28} strokeWidth={1.5} className="text-[#71717A]" aria-hidden="true" />
                <h2 className="mt-4 text-base font-semibold text-[#18181B]">Templates indisponibles</h2>
                <p className="mt-1 max-w-sm text-sm leading-6 text-[#71717A]">{error}</p>
                <button type="button" className={`${BUTTON_SECONDARY} mt-5`} onClick={loadTemplates}>
                  Réessayer
                </button>
              </div>
            ) : (
              <div className="flex min-h-80 flex-col items-center justify-center px-6 py-12 text-center">
                <Clock3 size={28} strokeWidth={1.5} className="text-[#71717A]" aria-hidden="true" />
                <h2 className="mt-4 text-base font-semibold text-[#18181B]">Créez une organisation de journée</h2>
                <p className="mt-1 max-w-sm text-sm leading-6 text-[#71717A]">
                  La timeline impose l’ordre cours, questions-réponses et pause.
                </p>
                <button type="button" className={`${BUTTON_PRIMARY} mt-5`} onClick={startCreate}>
                  <Plus size={15} aria-hidden="true" />
                  Créer le premier template
                </button>
              </div>
            )
          ) : (
            <>
              {mode === 'preview' && (
                <div className="border-b border-[#ECECEF] p-4 sm:p-5">
                <div className="flex flex-col justify-between gap-4 xl:flex-row xl:items-start">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="min-w-0 truncate text-lg font-semibold text-[#18181B]">
                        {selectedTemplate.name}
                      </h2>
                      <TemplateState template={selectedTemplate} />
                    </div>
                    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[#71717A]">
                      <span>{validation.stats.courseCount} cours</span>
                      <span>{formatDuration(validation.stats.courseMinutes)} de cours vocal</span>
                      <span>{formatDuration(validation.stats.dayMinutes)} d’amplitude</span>
                      <span>{validation.stats.blockCount} fichiers prévus</span>
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    {!isScheduleTemplateUsed(selectedTemplate) && (
                      <button type="button" className={BUTTON_SECONDARY} onClick={startEdit}>
                        <PencilLine size={15} aria-hidden="true" />
                        Modifier
                      </button>
                    )}
                    <button type="button" className={BUTTON_SECONDARY} onClick={() => startDuplicate()}>
                      <Copy size={15} aria-hidden="true" />
                      Dupliquer
                    </button>
                    <button type="button" className={BUTTON_GHOST} onClick={removeTemplate} disabled={deleting}>
                      <Trash2 size={15} aria-hidden="true" />
                      {deleting ? 'Suppression…' : 'Supprimer'}
                    </button>
                    <button type="button" className={BUTTON_PRIMARY} onClick={useTemplate}>
                      Utiliser
                    </button>
                  </div>
                </div>

                <div className="day-schedule-rule-strip mt-4" aria-label="Règles de validation">
                  {rules.map((rule) => <span key={rule} className="day-schedule-rule">{rule}</span>)}
                </div>

                </div>
              )}

              {mode === 'preview' && isScheduleTemplateUsed(selectedTemplate) && (
                <div className="mx-4 mt-4 flex items-start gap-2.5 rounded-lg border border-[#D4D4D8] bg-[#F4F4F5] px-3.5 py-3 text-xs leading-5 text-[#52525B] sm:mx-5">
                  <LockKeyhole size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
                  <p>
                    Ce template a déjà été utilisé. Son organisation est verrouillée. Dupliquez-le pour créer une variante.
                  </p>
                </div>
              )}

              <div className="p-4 sm:p-5">
                {mode === 'preview' && (
                  <div className="day-schedule-validation mb-4">
                    <div className="flex items-center gap-2">
                      {validation.valid
                        ? <Check size={15} aria-hidden="true" />
                        : <Clock3 size={15} aria-hidden="true" />}
                      <p className="text-xs font-semibold text-[#18181B]">
                        {validation.valid ? 'Planning conforme' : 'Planning à compléter'}
                      </p>
                    </div>
                    {!validation.valid && validation.errors.length > 0 && (
                      <ul className="text-xs leading-5 text-[#52525B]">
                        {validation.errors.map((message) => <li key={message}>{message}</li>)}
                      </ul>
                    )}
                  </div>
                )}

                <ScheduleTimeline
                  blocks={visibleTemplate.blocks}
                  readOnly={mode !== 'edit'}
                  blockErrors={validation.blockErrors}
                  onBlocksChange={updateDraftBlocks}
                  onAddSequence={() => updateDraftBlocks(addScheduleSequence(draft.blocks))}
                  canAddSequence={validation.stats.courseCount < DAY_SCHEDULE_RULES.maxCourses}
                />
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  )
}
