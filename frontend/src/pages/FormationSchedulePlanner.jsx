import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ChevronDown,
  Menu,
  PlusCircle,
  Search,
} from 'lucide-react'

import { listDayScheduleTemplates } from '../dayScheduleTemplateApi.js'
import {
  TRAINING_WEEKDAYS,
  addCalendarDays,
  assignTemplateToAll,
  getCalendarMonthDays,
  isValidCalendarDate,
  normalizeSelectedTrainingDates,
  prefillTrainingDates,
  reconcileTemplateAssignments,
  serializeFormationScheduleV2,
  validateFormationScheduleV2,
} from '../formationScheduleV2.js'
import './FormationSchedulePlanner.css'

const FRENCH_WEEKDAY_TO_ISO = Object.freeze({
  lundi: 1,
  mardi: 2,
  mercredi: 3,
  jeudi: 4,
  vendredi: 5,
  samedi: 6,
  dimanche: 7,
})

const CALENDAR_DAY_ART = Object.freeze(
  Array.from({ length: 7 }, (_, index) => `/figma-week/day-${index + 1}.png`),
)
const CALENDAR_EVENT_ART = '/figma-week/event.png'

const FIGMA_WEEKDAY_LABELS = Object.freeze([
  'Mon', 'Tue', 'Wed', 'Thur', 'Fri', 'Sat', 'Sun',
])

const FIGMA_DEMO_EVENTS = Object.freeze([
  ...Array.from({ length: 5 }, (_, dayIndex) => ({
    dayIndex,
    start: 9,
    duration: 0.34,
    label: 'Daily Standup',
    time: '08:00',
    tone: 1,
  })),
  { dayIndex: 0, start: 10, duration: 0.34, label: 'Event Name', time: '08:00', tone: 1 },
  { dayIndex: 0, start: 10.34, duration: 0.34, label: 'Event Name', time: '08:00', tone: 3 },
  { dayIndex: 0, start: 10.68, duration: 0.34, label: 'Event Name', time: '08:00', tone: 4 },
  { dayIndex: 1, start: 10, duration: 0.5, label: 'Event Name', time: '08:00', tone: 2 },
  { dayIndex: 1, start: 10.5, duration: 0.5, label: 'Event Name', time: '08:00', tone: 5 },
  { dayIndex: 1, start: 11.5, duration: 2, label: 'Event Name', time: '08:00', tone: 2 },
  { dayIndex: 1, start: 14.5, duration: 1, label: 'Event Name', time: '08:00', tone: 1 },
  { dayIndex: 2, start: 12, duration: 1, label: 'Event Name', time: '08:00', tone: 5 },
  { dayIndex: 2, start: 13, duration: 1, label: 'Event Name', time: '08:00', tone: 4 },
  { dayIndex: 2, start: 15, duration: 0.5, label: 'Event Name', time: '08:00', tone: 4 },
  { dayIndex: 2, start: 15.5, duration: 0.5, label: 'Event Name', time: '08:00', tone: 5 },
  { dayIndex: 3, start: 11.5, duration: 3, label: 'Event Name', time: '08:00', description: 'Description', tone: 6 },
  {
    dayIndex: 4,
    start: 17,
    duration: 1,
    label: 'Team Drinks',
    time: '08:00',
    tone: 7,
    icon: CALENDAR_DAY_ART[5],
  },
])

function localToday() {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Europe/Paris',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(new Date())
      .filter((part) => part.type !== 'literal')
      .map((part) => [part.type, part.value]),
  )
  return `${parts.year}-${parts.month}-${parts.day}`
}

function formatLongDate(value) {
  const [year, month, day] = String(value).split('-').map(Number)
  return new Intl.DateTimeFormat('fr-FR', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(Date.UTC(year, month - 1, day)))
}

function monthLabel(year, monthIndex) {
  return new Intl.DateTimeFormat('fr-FR', {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(Date.UTC(year, monthIndex, 1)))
}

function weekLabel(startValue, endValue) {
  const parse = (value) => {
    const [year, month, day] = value.split('-').map(Number)
    return new Date(Date.UTC(year, month - 1, day))
  }
  const start = parse(startValue)
  const end = parse(endValue)
  const monthFormatter = new Intl.DateTimeFormat('fr-FR', { month: 'long', timeZone: 'UTC' })
  const sameMonth = start.getUTCMonth() === end.getUTCMonth()
    && start.getUTCFullYear() === end.getUTCFullYear()
  if (sameMonth) {
    return `${String(start.getUTCDate()).padStart(2, '0')}–${String(end.getUTCDate()).padStart(2, '0')} ${monthFormatter.format(end)} ${end.getUTCFullYear()}`
  }
  return `${String(start.getUTCDate()).padStart(2, '0')} ${monthFormatter.format(start)}–${String(end.getUTCDate()).padStart(2, '0')} ${monthFormatter.format(end)} ${end.getUTCFullYear()}`
}

function initialMonth(value) {
  const match = String(value || '').match(/^(\d{4})-(\d{2})-\d{2}$/)
  if (!match) {
    const today = new Date()
    return { year: today.getFullYear(), month: today.getMonth() }
  }
  return { year: Number(match[1]), month: Number(match[2]) - 1 }
}

function weekStart(value) {
  const [year, month, day] = String(value).split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  const isoWeekday = date.getUTCDay() === 0 ? 7 : date.getUTCDay()
  date.setUTCDate(date.getUTCDate() - (isoWeekday - 1))
  return date.toISOString().slice(0, 10)
}

function normalizeInitialAssignments(schedule) {
  if (Array.isArray(schedule?.template_assignments)) {
    return Object.fromEntries(schedule.template_assignments.map((assignment) => [
      assignment.date,
      String(assignment.template_id ?? assignment.template_key ?? ''),
    ]))
  }
  return Object.fromEntries(
    Object.entries(schedule?.template_assignments || {})
      .map(([date, templateId]) => [date, String(templateId)]),
  )
}

export default function FormationSchedulePlanner({
  reuse = false,
  expectedDayCount = null,
  initialSchedule = null,
  startDateHint = '',
  approximateDayCount = null,
  daysPerWeekHint = 2,
  preferredWeekdaysHint = [],
  identityComplete = true,
  onRequestIdentity,
  onCreateTemplate,
  onChange,
}) {
  const today = useMemo(localToday, [])
  const earliestSuggestedDate = reuse ? today : addCalendarDays(today, 3)
  const safeStartHint = isValidCalendarDate(startDateHint)
    && startDateHint >= earliestSuggestedDate
    ? startDateHint
    : earliestSuggestedDate
  const initialDates = useMemo(
    () => normalizeSelectedTrainingDates(initialSchedule?.selected_dates || []),
    [initialSchedule],
  )
  const initialPreferredDays = useMemo(() => {
    const converted = preferredWeekdaysHint
      .map((day) => FRENCH_WEEKDAY_TO_ISO[String(day).toLowerCase()] ?? Number(day))
      .filter((day) => day >= 1 && day <= 7)
    if (converted.length) return [...new Set(converted)]
    return [2, 4]
  }, [preferredWeekdaysHint])
  const initialWeeklyCount = Math.max(
    1,
    Math.min(7, Number(daysPerWeekHint) || initialPreferredDays.length || 2),
  )
  const targetDayCount = reuse
    ? Math.max(1, Number(expectedDayCount) || 1)
    : Math.max(0, Number(approximateDayCount) || 0)

  const [templates, setTemplates] = useState([])
  const [templatesLoading, setTemplatesLoading] = useState(!reuse)
  const [, setTemplatesError] = useState('')
  const [selectedDates, setSelectedDates] = useState(initialDates)
  const [assignments, setAssignments] = useState(
    () => normalizeInitialAssignments(initialSchedule),
  )
  const [bulkTemplateId, setBulkTemplateId] = useState('')
  const [applyAllDays, setApplyAllDays] = useState(false)
  const [helperStartDate, setHelperStartDate] = useState(
    initialDates[0] || safeStartHint,
  )
  const [helperWeeks, setHelperWeeks] = useState(() => String(
    Math.max(1, Math.ceil((targetDayCount || 8) / initialWeeklyCount) + (targetDayCount ? 1 : 0)),
  ))
  const [helperDaysPerWeek, setHelperDaysPerWeek] = useState(String(initialWeeklyCount))
  const [preferredWeekdays, setPreferredWeekdays] = useState(initialPreferredDays)
  const [helperError, setHelperError] = useState('')
  const [validationNow, setValidationNow] = useState(() => new Date())
  const [month, setMonth] = useState(() => initialMonth(initialDates[0] || safeStartHint))
  const [focusedWeekStart, setFocusedWeekStart] = useState(
    () => weekStart(initialDates[0] || today),
  )
  const [activeDateKey, setActiveDateKey] = useState(initialDates[0] || '')
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const didInitialPrefill = useRef(false)
  const helperRef = useRef(null)

  const loadTemplates = useCallback(async () => {
    if (reuse) return
    setTemplatesLoading(true)
    setTemplatesError('')
    try {
      const loaded = await listDayScheduleTemplates()
      setTemplates(loaded)
      const retainedTemplateId = window.sessionStorage.getItem(
        'selected_day_schedule_template_id',
      )
      const retainedExists = loaded.some(
        (template) => String(template.id) === String(retainedTemplateId),
      )
      if (retainedExists && initialDates.length) {
        setApplyAllDays(true)
        setAssignments(assignTemplateToAll(initialDates, retainedTemplateId))
        window.sessionStorage.removeItem('selected_day_schedule_template_id')
      }
      setBulkTemplateId((current) => (
        current
        || (retainedExists ? String(retainedTemplateId) : String(loaded[0]?.id || ''))
      ))
    } catch (error) {
      setTemplatesError(error.message || 'Impossible de charger les templates.')
    } finally {
      setTemplatesLoading(false)
    }
  }, [initialDates, reuse])

  useEffect(() => {
    loadTemplates()
  }, [loadTemplates])

  useEffect(() => {
    if (reuse) return undefined
    const intervalId = window.setInterval(
      () => setValidationNow(new Date()),
      60_000,
    )
    return () => window.clearInterval(intervalId)
  }, [reuse])

  useEffect(() => {
    if (didInitialPrefill.current || initialDates.length || !targetDayCount) return
    didInitialPrefill.current = true
    const generated = prefillTrainingDates({
      startDate: safeStartHint,
      weeks: Math.max(1, Math.ceil(targetDayCount / initialWeeklyCount) + 1),
      daysPerWeek: initialPreferredDays.length,
      preferredWeekdays: initialPreferredDays,
      limit: targetDayCount,
    })
    setSelectedDates(generated)
    setHelperWeeks(String(Math.max(1, Math.ceil(targetDayCount / initialWeeklyCount) + 1)))
    if (generated[0]) setMonth(initialMonth(generated[0]))
  }, [
    initialDates.length,
    initialPreferredDays,
    initialWeeklyCount,
    safeStartHint,
    targetDayCount,
  ])

  const normalizedDates = useMemo(
    () => normalizeSelectedTrainingDates(selectedDates),
    [selectedDates],
  )
  const cleanAssignments = useMemo(
    () => reconcileTemplateAssignments(assignments, normalizedDates),
    [assignments, normalizedDates],
  )
  const validation = useMemo(() => validateFormationScheduleV2({
    selectedDates: normalizedDates,
    assignments: cleanAssignments,
    templates,
    reuse,
    expectedDayCount,
    now: validationNow,
  }), [
    cleanAssignments,
    expectedDayCount,
    normalizedDates,
    reuse,
    templates,
    validationNow,
  ])
  const payload = useMemo(() => serializeFormationScheduleV2({
    selectedDates: normalizedDates,
    assignments: cleanAssignments,
    templates,
    reuse,
  }), [cleanAssignments, normalizedDates, reuse, templates])
  const calendarDays = useMemo(
    () => getCalendarMonthDays(month.year, month.month),
    [month],
  )
  const selectedSet = useMemo(() => new Set(normalizedDates), [normalizedDates])
  const selectedTemplateIds = useMemo(
    () => new Set(templates.map((template) => String(template.id))),
    [templates],
  )
  const activeDate = normalizedDates.includes(activeDateKey)
    ? activeDateKey
    : normalizedDates[0] || ''
  const activeDateIndex = activeDate ? normalizedDates.indexOf(activeDate) : -1
  const activeAssignment = activeDate ? cleanAssignments[activeDate] || '' : ''
  const displayedDate = activeDate || helperStartDate
  const displayedDateIndex = activeDateIndex >= 0 ? activeDateIndex : 0
  const displayedDayCount = normalizedDates.length || Math.max(2, targetDayCount || 2)
  const scheduleDays = useMemo(() => {
    const templatesById = new Map(templates.map(
      (template) => [String(template.id), template],
    ))
    return normalizedDates.map((date, index) => {
      const templateId = cleanAssignments[date] || ''
      return {
        date,
        dayNumber: index + 1,
        label: formatLongDate(date),
        templateId,
        blocks: templatesById.get(templateId)?.blocks || [],
        templateName: reuse
          ? 'Déroulé conservé'
          : String(templatesById.get(templateId)?.name || ''),
      }
    })
  }, [cleanAssignments, normalizedDates, reuse, templates])
  const scheduleDayByDate = useMemo(
    () => new Map(scheduleDays.map((day) => [day.date, day])),
    [scheduleDays],
  )
  const visibleWeekDates = useMemo(
    () => Array.from({ length: 7 }, (_, index) => addCalendarDays(focusedWeekStart, index)),
    [focusedWeekStart],
  )
  const visibleWeekLabel = weekLabel(visibleWeekDates[0], visibleWeekDates[6])
  const hasVisibleTemplateBlocks = visibleWeekDates.some(
    (date) => (scheduleDayByDate.get(date)?.blocks || []).length > 0,
  )

  useEffect(() => {
    onChange?.({
      payload,
      valid: validation.valid,
      validation,
      dayCount: normalizedDates.length,
      days: scheduleDays,
    })
  }, [normalizedDates.length, onChange, payload, scheduleDays, validation])

  useEffect(() => {
    if (!normalizedDates.length) {
      setActiveDateKey('')
      return
    }
    if (!normalizedDates.includes(activeDateKey)) {
      setActiveDateKey(normalizedDates[0])
    }
  }, [activeDateKey, normalizedDates])

  useEffect(() => {
    if (!applyAllDays || !bulkTemplateId || !normalizedDates.length) return
    setAssignments(assignTemplateToAll(normalizedDates, bulkTemplateId))
  }, [applyAllDays, bulkTemplateId, normalizedDates])

  const togglePreferredWeekday = (weekday) => {
    setPreferredWeekdays((current) => (
      current.includes(weekday)
        ? current.filter((day) => day !== weekday)
        : [...current, weekday].sort()
    ))
    setHelperError('')
  }

  const applyPrefill = () => {
    const weeklyCount = Number(helperDaysPerWeek)
    if (!helperStartDate) {
      setHelperError('Choisissez une date de début.')
      return
    }
    if (!isValidCalendarDate(helperStartDate)) {
      setHelperError('La date de début n’existe pas. Choisissez une date valide.')
      return
    }
    if (preferredWeekdays.length !== weeklyCount) {
      setHelperError(`Choisissez exactement ${weeklyCount} jour${weeklyCount > 1 ? 's' : ''} préféré${weeklyCount > 1 ? 's' : ''}.`)
      return
    }
    const generated = prefillTrainingDates({
      startDate: helperStartDate,
      weeks: helperWeeks,
      daysPerWeek: weeklyCount,
      preferredWeekdays,
      limit: targetDayCount || null,
    })
    if (!generated.length) {
      setHelperError('Le préremplissage n’a produit aucune date. Vérifiez les paramètres.')
      return
    }
    setSelectedDates(generated)
    setAssignments((current) => reconcileTemplateAssignments(current, generated))
    setMonth(initialMonth(generated[0]))
    setFocusedWeekStart(weekStart(generated[0]))
    setActiveDateKey(generated[0])
    setHelperError('')
  }

  const toggleDate = (date) => {
    if (date < today) return
    setFocusedWeekStart(weekStart(date))
    if (!selectedDates.includes(date)) setActiveDateKey(date)
    setSelectedDates((current) => (
      current.includes(date)
        ? current.filter((item) => item !== date)
        : [...current, date]
    ))
    setAssignments((current) => {
      if (!current[date]) return current
      const next = { ...current }
      delete next[date]
      return next
    })
  }

  const assignTemplate = (date, templateId) => {
    if (templateId === '__create__') {
      onCreateTemplate?.({
        schedule_schema_version: 2,
        selected_dates: normalizedDates,
        template_assignments: cleanAssignments,
        start_date: helperStartDate,
        days_per_week: Number(helperDaysPerWeek),
        preferred_weekdays: preferredWeekdays,
      })
      return
    }
    setAssignments((current) => ({
      ...current,
      [date]: String(templateId),
    }))
  }

  const openPrefill = () => {
    if (helperRef.current) helperRef.current.open = true
    helperRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }

  return (
    <section className="formation-schedule" aria-label="Calendrier hebdomadaire de la formation">
      <aside className="formation-schedule__sidebar" data-open={sidebarOpen}>
        <div className="formation-schedule__side-month">
          {monthLabel(month.year, month.month).replace(/\s+\d{4}$/, '')}
        </div>
        <div className="formation-schedule__mini-weekdays" aria-hidden="true">
          {TRAINING_WEEKDAYS.map((day) => <span key={day.id}>{day.short.slice(0, 1)}</span>)}
        </div>
        <div className="formation-schedule__mini-grid">
          {calendarDays.map((day) => (
            <button
              key={day.date}
              type="button"
              disabled={day.date < today}
              data-outside={!day.inMonth}
              aria-pressed={selectedSet.has(day.date)}
              aria-label={`${selectedSet.has(day.date) ? 'Retirer' : 'Ajouter'} le ${formatLongDate(day.date)}`}
              onClick={() => toggleDate(day.date)}
            >
              {String(day.day).padStart(2, '0')}
            </button>
          ))}
        </div>

        <section className="formation-schedule__organisation" aria-labelledby="formation-organisation-title">
          <header>
            <h2 id="formation-organisation-title">Organisation de la journée</h2>
            <p>{`Journée ${displayedDateIndex + 1} sur ${displayedDayCount}`}</p>
          </header>
          <div className="formation-schedule__organisation-body">
            <div className="formation-schedule__active-day-copy">
              <strong>{formatLongDate(displayedDate)}</strong>
              <span>Journée {displayedDateIndex + 1}</span>
            </div>
            {reuse ? (
              <span className="formation-schedule__locked-layout">Déroulé conservé</span>
            ) : (
              <label>
                <span>Template de la journée</span>
                <select
                  value={activeAssignment}
                  disabled={templatesLoading || applyAllDays}
                  onChange={(event) => {
                    if (!activeDate) {
                      setSelectedDates([displayedDate])
                      setActiveDateKey(displayedDate)
                    }
                    assignTemplate(displayedDate, event.target.value)
                  }}
                  aria-invalid={Boolean(activeDate && (!activeAssignment || !selectedTemplateIds.has(activeAssignment)))}
                >
                  <option value="">Choisir un template</option>
                  {templates.map((template) => <option key={template.id} value={String(template.id)}>{template.name}</option>)}
                  <option value="__create__">Créer un template</option>
                </select>
              </label>
            )}
            <nav className="formation-schedule__day-navigation" aria-label="Naviguer entre les journées">
              <button type="button" onClick={() => setActiveDateKey(normalizedDates[activeDateIndex - 1])} disabled={activeDateIndex <= 0}>Précédente</button>
              <span>{displayedDateIndex + 1} / {displayedDayCount}</span>
              <button type="button" onClick={() => setActiveDateKey(normalizedDates[activeDateIndex + 1])} disabled={activeDateIndex < 0 || activeDateIndex >= normalizedDates.length - 1}>Suivante</button>
            </nav>
          </div>
          {!reuse && normalizedDates.length > 1 && (
            <div className="formation-schedule__bulk">
              <label className="formation-schedule__bulk-toggle">
                <input type="checkbox" checked={applyAllDays} onChange={(event) => setApplyAllDays(event.target.checked)} />
                <span>Appliquer le même template à toutes les journées</span>
              </label>
              {applyAllDays && (
                <select
                  value={bulkTemplateId}
                  aria-label="Template à appliquer à toutes les journées"
                  onChange={(event) => {
                    if (event.target.value === '__create__') {
                      assignTemplate(activeDate || helperStartDate, '__create__')
                    } else {
                      setBulkTemplateId(event.target.value)
                    }
                  }}
                >
                  {templates.map((template) => <option key={template.id} value={String(template.id)}>{template.name}</option>)}
                  <option value="__create__">Créer un template</option>
                </select>
              )}
            </div>
          )}
        </section>

        <section className="formation-schedule__sequence" aria-labelledby="formation-sequence-title">
          <header>
            <div>
              <h2 id="formation-sequence-title">Séquence</h2>
              <p>À glisser dans le calendrier</p>
            </div>
            <span>0/10</span>
          </header>
          <button type="button" onClick={() => assignTemplate(activeDate || helperStartDate, '__create__')}>
            <PlusCircle size={14} aria-hidden="true" />
            Séquence pédagogique
          </button>
          <button type="button" disabled>Retirer la dernière séquence</button>
        </section>

        <details ref={helperRef} className="formation-schedule__helper">
          <summary>Préremplir les dates</summary>
          <div className="formation-schedule__helper-content">
            <label><span>Date de début</span><input type="date" min={earliestSuggestedDate} value={helperStartDate} onChange={(event) => { setHelperStartDate(event.target.value); setHelperError('') }} /></label>
            <label><span>Semaines</span><input type="number" min="1" max="104" value={helperWeeks} onChange={(event) => setHelperWeeks(event.target.value)} /></label>
            <label><span>Jours par semaine</span><input type="number" min="1" max="7" value={helperDaysPerWeek} onChange={(event) => setHelperDaysPerWeek(event.target.value)} /></label>
            <fieldset>
              <legend>Jours préférés</legend>
              <div className="formation-schedule__weekdays">
                {TRAINING_WEEKDAYS.map((day) => <button key={day.id} type="button" aria-pressed={preferredWeekdays.includes(day.id)} onClick={() => togglePreferredWeekday(day.id)}>{day.short}</button>)}
              </div>
            </fieldset>
            <button type="button" className="formation-schedule__prefill-action" onClick={applyPrefill}>Appliquer</button>
            {helperError && <p className="formation-schedule__inline-error" role="alert">{helperError}</p>}
          </div>
        </details>
      </aside>

      <div className="formation-schedule__week">
        <header className="formation-schedule__toolbar">
          <button type="button" className="formation-schedule__icon-button" onClick={() => setSidebarOpen((current) => !current)} aria-label={sidebarOpen ? 'Masquer le panneau' : 'Afficher le panneau'}>
            <Menu size={17} aria-hidden="true" />
          </button>
          <h1>{visibleWeekLabel}</h1>
          <span className="formation-schedule__view-label">Week <ChevronDown size={13} aria-hidden="true" /></span>
          <div className="formation-schedule__toolbar-actions">
            <button type="button" className="formation-schedule__search" onClick={() => activeDate && setFocusedWeekStart(weekStart(activeDate))} aria-label="Afficher la journée active"><Search size={15} aria-hidden="true" /></button>
            <button
              type="button"
              className="formation-schedule__add"
              onClick={identityComplete ? openPrefill : onRequestIdentity}
            >
              Add event <PlusCircle size={15} aria-hidden="true" />
            </button>
          </div>
        </header>

        <div className="formation-schedule__day-headings" aria-hidden="true">
          <span />
          {FIGMA_WEEKDAY_LABELS.map((label, index) => <span key={label}><img src={CALENDAR_DAY_ART[index]} alt="" />{label}</span>)}
        </div>

        <div className="formation-schedule__timeline">
          <div className="formation-schedule__time-axis" aria-hidden="true">
            {Array.from({ length: 12 }, (_, index) => <span key={index}>{String(index + 8).padStart(2, '0')}:00</span>)}
          </div>
          <div className="formation-schedule__week-grid">
            {visibleWeekDates.map((date, dayIndex) => {
              const scheduledDay = scheduleDayByDate.get(date)
              const events = hasVisibleTemplateBlocks
                ? (scheduledDay?.blocks || []).map((block, blockIndex) => ({
                  dayIndex,
                  start: Number(block.start_minute || 0) / 60,
                  duration: Math.max(5, Number(block.duration_minutes || 0)) / 60,
                  label: block.label || scheduledDay.templateName || `Journée ${scheduledDay.dayNumber}`,
                  time: `${String(Math.floor(Number(block.start_minute || 0) / 60)).padStart(2, '0')}:${String(Number(block.start_minute || 0) % 60).padStart(2, '0')}`,
                  tone: (blockIndex % 5) + 1,
                }))
                : FIGMA_DEMO_EVENTS.filter((event) => event.dayIndex === dayIndex)
              return (
                <button
                  key={date}
                  type="button"
                  className="formation-schedule__week-column"
                  data-weekend={dayIndex > 4}
                  data-active={activeDate === date}
                  aria-pressed={selectedSet.has(date)}
                  aria-label={`${selectedSet.has(date) ? 'Retirer' : 'Ajouter'} le ${formatLongDate(date)}`}
                  onClick={() => toggleDate(date)}
                >
                  {Array.from({ length: 12 }, (_, hourIndex) => <span key={hourIndex} className="formation-schedule__hour-slot" />)}
                  {events.map((event, eventIndex) => (
                    <span
                      key={`${date}:${event.start}:${eventIndex}`}
                      className="formation-schedule__week-event"
                      data-tone={event.tone}
                      data-preview={!hasVisibleTemplateBlocks || undefined}
                      style={{
                        '--event-start': event.start - 8,
                        '--event-duration': event.duration,
                      }}
                    >
                      <span className="formation-schedule__week-event-heading">
                        <span><img src={event.icon || CALENDAR_EVENT_ART} alt="" />{event.label}</span>
                        <time>{event.time}</time>
                      </span>
                      {event.description && <span className="formation-schedule__week-event-description">{event.description}</span>}
                    </span>
                  ))}
                </button>
              )
            })}
          </div>
        </div>
      </div>
    </section>
  )
}
