import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen,
  Check,
  CircleAlert,
  Clock3,
  Coffee,
  Copy,
  GripHorizontal,
  GripVertical,
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
  createScheduleTemplateDraft,
  DAY_SCHEDULE_RULES,
  formatScheduleMinute,
  getScheduleStats,
  isScheduleTemplateUsed,
  parseScheduleTime,
  removeLastScheduleSequence,
  setScheduleFinalPause,
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
}) {
  const adjustmentRef = useRef(null)

  useEffect(() => () => {
    const adjustment = adjustmentRef.current
    if (!adjustment) return
    window.removeEventListener('pointermove', adjustment.onMove)
    window.removeEventListener('pointerup', adjustment.onEnd)
  }, [])

  const beginAdjustment = (event, blockIndex, mode) => {
    if (readOnly) return
    event.preventDefault()
    const startY = event.clientY
    const original = blocks.map((block) => ({ ...block }))
    const initialStart = original[blockIndex].start_minute
    const initialDuration = original[blockIndex].duration_minutes

    const onMove = (pointerEvent) => {
      const deltaMinutes = Math.round((pointerEvent.clientY - startY) / 1.15)
      const next = mode === 'move'
        ? updateScheduleBlockStart(original, blockIndex, initialStart + deltaMinutes)
        : updateScheduleBlockDuration(original, blockIndex, initialDuration + deltaMinutes)
      onBlocksChange(next)
    }
    const onEnd = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onEnd)
      adjustmentRef.current = null
    }
    adjustmentRef.current = { onMove, onEnd }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onEnd, { once: true })
  }

  const counters = { course: 0, qa: 0 }

  return (
    <div className="day-schedule-timeline" aria-label="Déroulé de la journée">
      {blocks.map((block, index) => {
        const presentation = blockPresentation(block, counters)
        const BlockIcon = presentation.icon
        const bounds = durationBounds(block)
        const errors = blockErrors[block.block_key] || []
        const minimumBlockHeight = readOnly ? 76 : 132
        const blockHeight = Math.max(
          minimumBlockHeight,
          Math.min(block.duration_minutes * 1.15, 150),
        )
        return (
          <div
            key={block.block_key}
            className="day-schedule-timeline-row"
            data-editable={readOnly ? 'false' : 'true'}
            style={{ '--day-schedule-row-height': `${blockHeight}px` }}
          >
            <time className="day-schedule-timeline-time" dateTime={formatScheduleMinute(block.start_minute)}>
              {formatScheduleMinute(block.start_minute)}
            </time>
            <div className="day-schedule-block-wrap">
              <article
                className="day-schedule-block"
                data-kind={presentation.kind}
                data-invalid={errors.length ? 'true' : 'false'}
              >
                <div className="flex min-w-0 items-start gap-2.5 pr-8">
                  <BlockIcon size={16} strokeWidth={1.7} className="mt-0.5 shrink-0 text-[#52525B]" aria-hidden="true" />
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold text-[#18181B]">{presentation.title}</h3>
                    <p className="mt-0.5 text-xs tabular-nums text-[#71717A]">
                      {formatScheduleMinute(block.start_minute)} à {formatScheduleMinute(block.end_minute)}
                    </p>
                  </div>
                </div>

                {!readOnly && (
                  <>
                    <span
                      className="day-schedule-drag-button"
                      onPointerDown={(event) => beginAdjustment(event, index, 'move')}
                      aria-hidden="true"
                      title="Déplacer le début du bloc"
                    >
                      <GripVertical size={16} aria-hidden="true" />
                    </span>
                    <span
                      className="day-schedule-resize-button"
                      onPointerDown={(event) => beginAdjustment(event, index, 'resize')}
                      aria-hidden="true"
                      title="Modifier la durée"
                    >
                      <GripHorizontal size={16} aria-hidden="true" />
                    </span>
                  </>
                )}

                <div className="day-schedule-block-controls">
                  <div className="day-schedule-field">
                    <label htmlFor={`schedule-start-${block.block_key}`}>Début</label>
                    <input
                      id={`schedule-start-${block.block_key}`}
                      type="time"
                      step="60"
                      value={formatScheduleMinute(block.start_minute)}
                      disabled={readOnly}
                      onChange={(event) => {
                        const minute = parseScheduleTime(event.target.value)
                        if (minute !== null) onBlocksChange(updateScheduleBlockStart(blocks, index, minute))
                      }}
                    />
                  </div>
                  <div className="day-schedule-field">
                    <label htmlFor={`schedule-duration-${block.block_key}`}>Durée (min)</label>
                    <input
                      id={`schedule-duration-${block.block_key}`}
                      type="number"
                      min={bounds.min}
                      max={bounds.max}
                      step="1"
                      value={block.duration_minutes}
                      disabled={readOnly}
                      onChange={(event) => {
                        if (event.target.value === '') return
                        onBlocksChange(updateScheduleBlockDuration(blocks, index, event.target.value))
                      }}
                    />
                  </div>
                  {block.block_type === 'pause' ? (
                    <div className="day-schedule-field">
                      <label htmlFor={`schedule-kind-${block.block_key}`}>Type de pause</label>
                      <select
                        id={`schedule-kind-${block.block_key}`}
                        value={block.pause_kind}
                        disabled={readOnly || index === blocks.length - 1}
                        onChange={(event) => onBlocksChange(
                          setSchedulePauseKind(blocks, index, event.target.value),
                        )}
                      >
                        <option value="short">Pause courte</option>
                        <option value="lunch">Pause déjeuner</option>
                      </select>
                    </div>
                  ) : (
                    <div className="day-schedule-field">
                      <label>Durée autorisée</label>
                      <div className="flex min-h-11 items-center rounded-lg border border-[#E4E4E7] bg-white px-2.5 text-xs text-[#71717A]">
                        {bounds.min} à {bounds.max} min
                      </div>
                    </div>
                  )}
                </div>

                {errors.length > 0 && (
                  <p className="mt-2 text-xs font-medium leading-5 text-[#3F3F46]" role="alert">
                    {errors.join(' ')}
                  </p>
                )}
              </article>
            </div>
          </div>
        )
      })}
      {blocks.length > 0 && (
        <div className="grid grid-cols-[52px_minmax(0,1fr)] sm:grid-cols-[64px_minmax(0,1fr)]">
          <time className="day-schedule-timeline-time pb-3" dateTime={formatScheduleMinute(blocks.at(-1).end_minute)}>
            {formatScheduleMinute(blocks.at(-1).end_minute)}
          </time>
          <div className="mx-3 border-t border-[#D4D4D8]" />
        </div>
      )}
    </div>
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
    setDraft(createScheduleTemplateDraft())
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
        <button type="button" className={`${BUTTON_PRIMARY} shrink-0`} onClick={startCreate}>
          <Plus size={16} aria-hidden="true" />
          Créer un template
        </button>
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

      <div className="day-schedule-layout">
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

        <div className="day-schedule-workspace">
          {!visibleTemplate ? (
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
          ) : (
            <>
              <div className="border-b border-[#ECECEF] p-4 sm:p-5">
                <div className="flex flex-col justify-between gap-4 xl:flex-row xl:items-start">
                  <div className="min-w-0 flex-1">
                    {mode === 'edit' ? (
                      <div>
                        <label htmlFor="day-schedule-template-name" className="mb-1.5 block text-xs font-semibold text-[#52525B]">
                          Nom du template
                        </label>
                        <input
                          id="day-schedule-template-name"
                          className="day-schedule-name-input max-w-lg text-base font-semibold"
                          value={draft.name}
                          placeholder="Ex. Journée standard"
                          autoFocus={!draft.id}
                          onChange={(event) => setDraft((current) => ({
                            ...current,
                            name: event.target.value,
                          }))}
                        />
                      </div>
                    ) : (
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="min-w-0 truncate text-lg font-semibold text-[#18181B]">
                          {selectedTemplate.name}
                        </h2>
                        <TemplateState template={selectedTemplate} />
                      </div>
                    )}
                    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[#71717A]">
                      <span>{validation.stats.courseCount} cours</span>
                      <span>{formatDuration(validation.stats.courseMinutes)} de cours vocal</span>
                      <span>{formatDuration(validation.stats.dayMinutes)} d’amplitude</span>
                      <span>{validation.stats.blockCount} fichiers prévus</span>
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    {mode === 'edit' ? (
                      <>
                        <button type="button" className={BUTTON_SECONDARY} onClick={cancelEdit} disabled={saving}>
                          <X size={15} aria-hidden="true" />
                          Annuler
                        </button>
                        <button type="button" className={BUTTON_PRIMARY} onClick={saveDraft} disabled={saving}>
                          <Save size={15} aria-hidden="true" />
                          {saving ? 'Enregistrement…' : 'Enregistrer'}
                        </button>
                      </>
                    ) : (
                      <>
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
                      </>
                    )}
                  </div>
                </div>

                <div className="day-schedule-rule-strip mt-4" aria-label="Règles de validation">
                  {rules.map((rule) => <span key={rule} className="day-schedule-rule">{rule}</span>)}
                </div>

                {mode === 'edit' && (
                  <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-[#ECECEF] pt-4">
                    <button
                      type="button"
                      className={BUTTON_SECONDARY}
                      onClick={() => updateDraftBlocks(addScheduleSequence(draft.blocks))}
                      disabled={validation.stats.courseCount >= DAY_SCHEDULE_RULES.maxCourses}
                    >
                      <Plus size={15} aria-hidden="true" />
                      Ajouter une séquence
                    </button>
                    <button
                      type="button"
                      className={BUTTON_SECONDARY}
                      onClick={() => updateDraftBlocks(removeLastScheduleSequence(draft.blocks))}
                      disabled={validation.stats.courseCount <= DAY_SCHEDULE_RULES.minCourses}
                    >
                      Retirer la dernière séquence
                    </button>
                    <label className="day-schedule-focusable ml-auto inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-lg px-2 text-sm font-medium text-[#52525B]">
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-[#18181B]"
                        checked={validation.stats.hasFinalPause}
                        onChange={(event) => updateDraftBlocks(
                          setScheduleFinalPause(draft.blocks, event.target.checked),
                        )}
                      />
                      Ajouter une pause finale
                    </label>
                  </div>
                )}
              </div>

              {mode === 'preview' && isScheduleTemplateUsed(selectedTemplate) && (
                <div className="mx-4 mt-4 flex items-start gap-2.5 rounded-lg border border-[#D4D4D8] bg-[#F4F4F5] px-3.5 py-3 text-xs leading-5 text-[#52525B] sm:mx-5">
                  <LockKeyhole size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
                  <p>
                    Ce template a déjà été utilisé. Son organisation est verrouillée. Dupliquez-le pour créer une variante.
                  </p>
                </div>
              )}

              <div className="p-4 sm:p-5">
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

                <ScheduleTimeline
                  blocks={visibleTemplate.blocks}
                  readOnly={mode !== 'edit'}
                  blockErrors={validation.blockErrors}
                  onBlocksChange={updateDraftBlocks}
                />
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  )
}
