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
  Minus,
  PencilLine,
  Plus,
  Search,
  Trash2,
  Utensils,
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
  removeLastScheduleSequence,
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

const BUTTON_BASE = 'day-schedule-focusable inline-flex min-h-10 items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40'
const BUTTON_PRIMARY = `${BUTTON_BASE} bg-[#18181B] text-white hover:bg-[#27272A] active:bg-[#09090B]`
const BUTTON_SECONDARY = `${BUTTON_BASE} border border-[#D4D4D8] bg-white text-[#3F3F46] hover:bg-[#F4F4F5] active:bg-[#E4E4E7]`
const CALENDAR_START_MINUTE = 0
const CALENDAR_END_MINUTE = 24 * 60
const CALENDAR_INITIAL_MINUTE = 8 * 60
const CALENDAR_PIXELS_PER_MINUTE = 1.05
const CALENDAR_EDGE_PADDING = 24

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
  const calendarScrollRef = useRef(null)
  const [activeResizeIndex, setActiveResizeIndex] = useState(null)
  const [dropActive, setDropActive] = useState(false)

  useEffect(() => {
    const scrollContainer = calendarScrollRef.current
    if (!scrollContainer) return
    scrollContainer.scrollTop = (
      (CALENDAR_INITIAL_MINUTE - CALENDAR_START_MINUTE) * CALENDAR_PIXELS_PER_MINUTE
    )
  }, [])

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
  const calendarMinutes = CALENDAR_END_MINUTE - CALENDAR_START_MINUTE
  const calendarHeight = (
    calendarMinutes * CALENDAR_PIXELS_PER_MINUTE
  ) + (CALENDAR_EDGE_PADDING * 2)
  const hourMarkers = Array.from(
    { length: Math.ceil(calendarMinutes / 60) },
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

      <div ref={calendarScrollRef} className="day-schedule-calendar-scroll">
        <div
          className="day-schedule-calendar"
          aria-label="Déroulé de la journée"
          style={{
            '--day-schedule-calendar-height': `${calendarHeight}px`,
            '--day-schedule-edge-padding': `${CALENDAR_EDGE_PADDING}px`,
            '--day-schedule-empty-top': `${
              CALENDAR_EDGE_PADDING + ((10 * 60 - CALENDAR_START_MINUTE) * CALENDAR_PIXELS_PER_MINUTE)
            }px`,
          }}
        >
          <div className="day-schedule-calendar-hours" aria-hidden="true">
            {hourMarkers.map((minute) => (
              <div
                key={minute}
                className="day-schedule-calendar-hour"
                style={{
                  '--day-schedule-hour-top': `${
                    CALENDAR_EDGE_PADDING
                    + ((minute - CALENDAR_START_MINUTE) * CALENDAR_PIXELS_PER_MINUTE)
                  }px`,
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
            const blockTop = (
              CALENDAR_EDGE_PADDING
              + ((block.start_minute - CALENDAR_START_MINUTE) * CALENDAR_PIXELS_PER_MINUTE)
            )
            const sequenceNumber = counters.course
            const isCourse = block.block_type === 'course'
            const canSelectAsLunch = (
              !readOnly
              && block.block_type === 'pause'
            )
            const toggleLunch = () => {
              if (!canSelectAsLunch) return
              onBlocksChange(setSchedulePauseKind(
                blocks,
                index,
                block.pause_kind === 'lunch' ? 'short' : 'lunch',
              ))
            }
            return (
              <article
                key={block.block_key}
                className="day-schedule-calendar-event"
                data-kind={presentation.kind}
                data-invalid={errors.length ? 'true' : 'false'}
                data-resizing={activeResizeIndex === index ? 'true' : 'false'}
                data-compact={blockHeight < 34 ? 'true' : 'false'}
                data-selectable={canSelectAsLunch ? 'true' : 'false'}
                title={errors.join(' ')}
                style={{
                  '--day-schedule-event-top': `${blockTop}px`,
                  '--day-schedule-event-height': `${blockHeight}px`,
                }}
              >
                {canSelectAsLunch && (
                  <button
                    type="button"
                    className="day-schedule-pause-select"
                    aria-label={block.pause_kind === 'lunch'
                      ? 'Repasser cette pause en pause courte'
                      : 'Choisir cette pause comme pause déjeuner'}
                    aria-pressed={block.pause_kind === 'lunch'}
                    title={block.pause_kind === 'lunch'
                      ? 'Cliquez pour repasser en pause courte'
                      : 'Cliquez pour choisir la pause déjeuner'}
                    onClick={toggleLunch}
                  />
                )}

                <div className="day-schedule-event-copy">
                  <BlockIcon size={16} strokeWidth={1.8} aria-hidden="true" />
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

                {canSelectAsLunch && (
                  <span className="day-schedule-pause-kind" aria-hidden="true">
                    {block.pause_kind === 'lunch' ? 'Déjeuner choisi' : 'Choisir déjeuner'}
                  </span>
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
                    <GripHorizontal size={20} aria-hidden="true" />
                  </button>
                )}
              </article>
            )
            })}
            </div>
          )}
        </div>
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
  onRemove,
}) {
  const courseCount = blocks.filter((block) => block.block_type === 'course').length
  const atMaximum = courseCount >= DAY_SCHEDULE_RULES.maxCourses
  const isEmpty = courseCount === 0
  return (
    <aside className="day-schedule-palette" aria-label="Séquence à planifier">
      <div className="day-schedule-palette-title">
        <div>
          <h2>Séquence</h2>
          <p>À glisser dans le calendrier</p>
        </div>
        <span>{courseCount}/{DAY_SCHEDULE_RULES.maxCourses}</span>
      </div>

      <div className="day-schedule-palette-actions">
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
          <Plus size={18} aria-hidden="true" />
          <span>Séquence pédagogique</span>
        </button>
        <button
          type="button"
          className="day-schedule-remove-task day-schedule-focusable"
          disabled={isEmpty}
          onClick={onRemove}
        >
          <Minus size={16} aria-hidden="true" />
          <span>Retirer la dernière séquence</span>
        </button>
      </div>
    </aside>
  )
}

function TemplateList({
  templates,
  loading,
  search,
  onSearchChange,
  onRetry,
  onEdit,
  onDuplicate,
  onDelete,
  onUse,
  deleting,
  error,
}) {
  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('fr')
    if (!query) return templates
    return templates.filter((template) => template.name.toLocaleLowerCase('fr').includes(query))
  }, [search, templates])

  return (
    <section className="day-schedule-library" aria-labelledby="day-schedule-library-title">
      <div className="day-schedule-library-toolbar">
        <div>
          <h2 id="day-schedule-library-title">Mes templates</h2>
          <p>{templates.length} organisation{templates.length > 1 ? 's' : ''} enregistrée{templates.length > 1 ? 's' : ''}</p>
        </div>
        {templates.length > 3 && (
          <label className="relative block">
            <span className="sr-only">Rechercher un template</span>
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#71717A]" aria-hidden="true" />
            <input
              type="search"
              className="day-schedule-search pl-9"
              placeholder="Rechercher un template"
              value={search}
              onChange={(event) => onSearchChange(event.target.value)}
            />
          </label>
        )}
      </div>

      {loading ? (
        <div className="day-schedule-library-list" aria-label="Chargement des templates">
          {[1, 2, 3].map((item) => (
            <div key={item} className="h-40 animate-pulse rounded-lg bg-[#EEEEEF]" />
          ))}
        </div>
      ) : error ? (
        <div className="day-schedule-library-message" role="alert">
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
              <article key={template.id} className="day-schedule-template-card">
                <div className="day-schedule-template-card-heading">
                  <h3>{template.name}</h3>
                  <TemplateState template={template} />
                </div>
                <div className="day-schedule-template-card-stats">
                  <span>{stats.courseCount} cours</span>
                  <span>{formatDuration(stats.dayMinutes)}</span>
                  <span>{stats.blockCount} blocs</span>
                </div>
                <div className="day-schedule-template-card-actions">
                  {!isScheduleTemplateUsed(template) && (
                    <button type="button" className={BUTTON_SECONDARY} onClick={() => onEdit(template)}>
                      <PencilLine size={14} aria-hidden="true" />
                      Modifier
                    </button>
                  )}
                  <button type="button" className={BUTTON_SECONDARY} onClick={() => onDuplicate(template)}>
                    <Copy size={14} aria-hidden="true" />
                    Dupliquer
                  </button>
                  <button
                    type="button"
                    className="day-schedule-template-delete day-schedule-focusable"
                    onClick={() => onDelete(template)}
                    disabled={deleting}
                    aria-label={`Supprimer ${template.name}`}
                    title="Supprimer"
                  >
                    <Trash2 size={15} aria-hidden="true" />
                  </button>
                  <button type="button" className={BUTTON_PRIMARY} onClick={() => onUse(template)}>
                    Utiliser
                  </button>
                </div>
              </article>
            )
          })}
        </div>
      )}
    </section>
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

  const startEdit = (template = selectedTemplate) => {
    if (!template || isScheduleTemplateUsed(template)) return
    setSelectedId(template.id)
    setDraft({
      ...template,
      blocks: template.blocks.map((block) => ({ ...block })),
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
      const createdNow = !draft.id
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
      if (createdNow && onUseTemplate) {
        window.sessionStorage.setItem('selected_day_schedule_template_id', String(saved.id))
        onUseTemplate(saved)
      }
    } catch (saveError) {
      setFeedback({
        tone: 'error',
        message: saveError.message || 'Impossible d’enregistrer le template.',
      })
    } finally {
      setSaving(false)
    }
  }

  const removeTemplate = async (template = selectedTemplate) => {
    if (!template || deleting) return
    const confirmed = window.confirm(
      `Supprimer « ${template.name} » de la bibliothèque ? Les formations existantes conserveront leur organisation.`,
    )
    if (!confirmed) return

    setDeleting(true)
    setFeedback(null)
    try {
      await deleteDayScheduleTemplate(template.id)
      const remaining = templates.filter(
        (item) => String(item.id) !== String(template.id),
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

  const useTemplate = (template = selectedTemplate) => {
    if (!template) return
    setSelectedId(template.id)
    window.sessionStorage.setItem('selected_day_schedule_template_id', String(template.id))
    setFeedback({
      tone: 'success',
      message: `« ${template.name} » est retenu pour la prochaine formation.`,
    })
    onUseTemplate?.(template)
  }

  const updateDraftBlocks = (blocks) => {
    setDraft((current) => current ? { ...current, blocks } : current)
  }

  const showTemplateOverview = mode === 'preview' && templates.length > 0
  const showSequencePalette = mode === 'edit'
  const hasSidePanel = showSequencePalette

  return (
    <section
      className={`day-schedule-page pb-12${mode === 'edit' ? ' day-schedule-page--editor' : ''}`}
      aria-labelledby="day-schedule-title"
    >
      <header className="day-schedule-page-header">
        <div>
          <h1 id="day-schedule-title" className="text-2xl font-semibold tracking-[-0.025em] text-[#18181B]">
            Organisation des cours
          </h1>
          <p className="mt-1.5 max-w-[68ch] text-sm leading-6 text-[#52525B]">
            Préparez des journées réutilisables. Un template devient immuable dès sa première utilisation dans une formation.
          </p>
        </div>
        <div className="day-schedule-page-actions">
          {mode === 'edit' ? (
            <>
              <button type="button" className={BUTTON_SECONDARY} onClick={cancelEdit} disabled={saving}>
                Annuler
              </button>
              <button type="button" className={BUTTON_PRIMARY} onClick={saveDraft} disabled={saving}>
                {saving ? 'Enregistrement…' : 'Enregistrer le template'}
              </button>
            </>
          ) : templates.length > 0 && (
            <button type="button" className={BUTTON_PRIMARY} onClick={startCreate}>
              <Plus size={16} aria-hidden="true" />
              Créer un template
            </button>
          )}
        </div>
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

      {mode === 'edit' && visibleTemplate && (
        <div className="day-schedule-editor-name-row">
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
          </div>
        </div>
      )}

      <div className={`day-schedule-layout${hasSidePanel ? '' : ' day-schedule-layout--single'}${mode === 'edit' ? ' day-schedule-layout--editor' : ''}${showTemplateOverview ? ' day-schedule-layout--overview' : ''}`}>
        {showTemplateOverview && (
          <TemplateList
            templates={templates}
            loading={loading}
            search={search}
            onSearchChange={setSearch}
            onRetry={loadTemplates}
            onEdit={startEdit}
            onDuplicate={startDuplicate}
            onDelete={removeTemplate}
            onUse={useTemplate}
            deleting={deleting}
            error={error}
          />
        )}
        {showSequencePalette && (
          <SequencePalette
            blocks={visibleTemplate.blocks}
            onAdd={() => updateDraftBlocks(addScheduleSequence(draft.blocks))}
            onRemove={() => updateDraftBlocks(removeLastScheduleSequence(draft.blocks))}
          />
        )}

        {!showTemplateOverview && (
          <div className={`day-schedule-workspace${mode === 'edit' ? ' day-schedule-workspace--editor' : ' day-schedule-workspace--empty'}`}>
            {!visibleTemplate ? (
              loading ? (
                <div className="day-schedule-empty-state" aria-live="polite">
                  <div className="h-7 w-7 animate-pulse rounded-full bg-[#E4E4E7]" aria-hidden="true" />
                  <p className="mt-4 text-sm font-semibold text-[#52525B]">Chargement des templates…</p>
                </div>
              ) : error ? (
                <div className="day-schedule-empty-state" role="alert">
                  <CircleAlert size={28} strokeWidth={1.5} className="text-[#71717A]" aria-hidden="true" />
                  <h2 className="mt-4 text-base font-semibold text-[#18181B]">Templates indisponibles</h2>
                  <p className="mt-1 max-w-sm text-sm leading-6 text-[#71717A]">{error}</p>
                  <button type="button" className={`${BUTTON_SECONDARY} mt-5`} onClick={loadTemplates}>
                    Réessayer
                  </button>
                </div>
              ) : (
                <div className="day-schedule-empty-state">
                  <span className="day-schedule-empty-state__icon" aria-hidden="true">
                    <Clock3 size={18} strokeWidth={1.7} />
                  </span>
                  <div className="day-schedule-empty-state__copy">
                    <h2>Aucun template</h2>
                    <p>Créez une journée type, puis réutilisez-la dans vos formations.</p>
                  </div>
                  <button type="button" className={BUTTON_PRIMARY} onClick={startCreate}>
                    <Plus size={15} aria-hidden="true" />
                    Créer un template
                  </button>
                </div>
              )
            ) : (
              <>
              <div className="p-4 sm:p-5">
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
        )}
      </div>
    </section>
  )
}
