import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  WandSparkles,
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
  const [templatesError, setTemplatesError] = useState('')
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
  const didInitialPrefill = useRef(false)

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
      setBulkTemplateId((current) => (
        current
        || (retainedExists ? String(retainedTemplateId) : String(loaded[0]?.id || ''))
      ))
    } catch (error) {
      setTemplatesError(error.message || 'Impossible de charger les templates.')
    } finally {
      setTemplatesLoading(false)
    }
  }, [reuse])

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
        templateName: reuse
          ? 'Déroulé conservé'
          : String(templatesById.get(templateId)?.name || ''),
      }
    })
  }, [cleanAssignments, normalizedDates, reuse, templates])

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

  const moveMonth = (amount) => {
    setMonth((current) => {
      const date = new Date(Date.UTC(current.year, current.month + amount, 1))
      return { year: date.getUTCFullYear(), month: date.getUTCMonth() }
    })
  }

  const assignTemplate = (date, templateId) => {
    setAssignments((current) => ({
      ...current,
      [date]: String(templateId),
    }))
  }

  return (
    <section className="formation-schedule" aria-labelledby="formation-schedule-title">
      <div className="formation-schedule__heading">
        <div>
          <h2 id="formation-schedule-title">Calendrier et déroulé de la formation</h2>
        </div>
        <span className="formation-schedule__count">
          {normalizedDates.length} journée{normalizedDates.length > 1 ? 's' : ''}
          {reuse && expectedDayCount ? ` sur ${expectedDayCount}` : ''}
        </span>
      </div>

      <details className="formation-schedule__helper">
        <summary>
          <span>
            <WandSparkles size={16} aria-hidden="true" />
            Préremplir rapidement
          </span>
          <ChevronDown
            className="formation-schedule__helper-chevron"
            size={16}
            aria-hidden="true"
          />
        </summary>
        <div className="formation-schedule__helper-content" aria-label="Préremplissage du calendrier">
          <p className="formation-schedule__helper-intro">
            Le préremplissage vous fait gagner du temps. Seules les dates cochées dans le calendrier seront retenues.
          </p>
          <div className="formation-schedule__helper-fields">
          <label>
            <span>Date de début</span>
            <input
              type="date"
              min={earliestSuggestedDate}
              value={helperStartDate}
              aria-invalid={Boolean(helperError) && !isValidCalendarDate(helperStartDate)}
              onChange={(event) => {
                setHelperStartDate(event.target.value)
                setHelperError('')
              }}
            />
          </label>
          <label>
            <span>Nombre de semaines</span>
            <input
              type="number"
              min="1"
              max="104"
              value={helperWeeks}
              onChange={(event) => {
                setHelperWeeks(event.target.value)
                setHelperError('')
              }}
            />
          </label>
          <label>
            <span>Journées par semaine</span>
            <input
              type="number"
              min="1"
              max="7"
              value={helperDaysPerWeek}
              onChange={(event) => {
                setHelperDaysPerWeek(event.target.value)
                setHelperError('')
              }}
            />
          </label>
          </div>

          <fieldset>
          <legend>Jours généralement préférés</legend>
          <div className="formation-schedule__weekdays">
            {TRAINING_WEEKDAYS.map((day) => {
              const selected = preferredWeekdays.includes(day.id)
              return (
                <button
                  key={day.id}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => togglePreferredWeekday(day.id)}
                >
                  {day.short}
                </button>
              )
            })}
          </div>
          </fieldset>

          <div className="formation-schedule__helper-action">
          <button type="button" onClick={applyPrefill}>
            <WandSparkles size={16} aria-hidden="true" />
            {normalizedDates.length ? 'Recalculer le préremplissage' : 'Préremplir le calendrier'}
          </button>
          <p>Vous pourrez ensuite cocher ou décocher chaque date, y compris le week-end.</p>
          </div>
          {helperError && <p className="formation-schedule__inline-error" role="alert">{helperError}</p>}
        </div>
      </details>

      <div className="formation-schedule__workspace">
        <div className="formation-schedule__calendar">
          <header>
            <h3>{monthLabel(month.year, month.month)}</h3>
            <button type="button" onClick={() => moveMonth(-1)} aria-label="Mois précédent">
              <ChevronLeft size={18} aria-hidden="true" />
            </button>
            <button type="button" onClick={() => moveMonth(1)} aria-label="Mois suivant">
              <ChevronRight size={18} aria-hidden="true" />
            </button>
          </header>
          <div className="formation-schedule__weekday-labels" aria-hidden="true">
            {TRAINING_WEEKDAYS.map((day) => (
              <span key={day.id}>{day.short.slice(0, 2).toLocaleLowerCase('fr-FR')}</span>
            ))}
          </div>
          <div className="formation-schedule__month-grid">
            {calendarDays.map((day) => {
              const selected = selectedSet.has(day.date)
              const disabled = day.date < today
              const focused = day.date >= focusedWeekStart
                && day.date <= addCalendarDays(focusedWeekStart, 6)
              return (
                <button
                  key={day.date}
                  type="button"
                  disabled={disabled}
                  data-outside={!day.inMonth}
                  data-focused-week={focused}
                  data-week-start={focused && day.isoWeekday === 1}
                  data-week-end={focused && day.isoWeekday === 7}
                  aria-pressed={selected}
                  aria-label={`${selected ? 'Retirer' : 'Ajouter'} le ${formatLongDate(day.date)}`}
                  onClick={() => toggleDate(day.date)}
                >
                  <span>{day.day}</span>
                </button>
              )
            })}
          </div>
        </div>

        <div className="formation-schedule__dates">
          <div className="formation-schedule__dates-header">
            <div>
              <h3>Organisation de la journée</h3>
              <p>
                {activeDateIndex >= 0
                  ? `Journée ${activeDateIndex + 1} sur ${normalizedDates.length}`
                  : 'Sélectionnez une date dans le calendrier.'}
              </p>
            </div>
          </div>

          {!reuse && templatesLoading && (
            <div className="formation-schedule__empty">Chargement des templates…</div>
          )}
          {!reuse && templatesError && (
            <div className="formation-schedule__empty" role="alert">
              <p>{templatesError}</p>
              <button type="button" onClick={loadTemplates}>Réessayer</button>
            </div>
          )}
          {normalizedDates.length === 0 && (
            <div className="formation-schedule__empty">
              <p>Aucune date cochée.</p>
              <span>Utilisez le préremplissage ou cochez directement une date dans le calendrier.</span>
            </div>
          )}
          {activeDate && (
            <div
              className="formation-schedule__active-day"
              data-invalid={!reuse && (
                !activeAssignment || !selectedTemplateIds.has(activeAssignment)
              )}
            >
              <div className="formation-schedule__active-day-copy">
                <strong>{formatLongDate(activeDate)}</strong>
                <span>Journée {activeDateIndex + 1}</span>
              </div>
              {reuse ? (
                <span className="formation-schedule__locked-layout">Déroulé conservé</span>
              ) : (
                <label>
                  <span>Template de la journée</span>
                  <select
                    value={activeAssignment}
                    disabled={templatesLoading || templates.length === 0 || applyAllDays}
                    onChange={(event) => assignTemplate(activeDate, event.target.value)}
                    aria-invalid={!activeAssignment || !selectedTemplateIds.has(activeAssignment)}
                  >
                    <option value="">Choisir un template</option>
                    {templates.map((template) => (
                      <option key={template.id} value={String(template.id)}>{template.name}</option>
                    ))}
                  </select>
                </label>
              )}
              {!reuse && !templatesLoading && !templatesError && templates.length === 0 && (
                <p className="formation-schedule__template-hint">
                  Créez d’abord un template dans « Organisation des cours ».
                </p>
              )}
              <nav className="formation-schedule__day-navigation" aria-label="Naviguer entre les journées">
                <button
                  type="button"
                  onClick={() => setActiveDateKey(normalizedDates[activeDateIndex - 1])}
                  disabled={activeDateIndex <= 0}
                  aria-label="Journée précédente"
                >
                  <ChevronLeft size={19} aria-hidden="true" />
                  <span>Précédente</span>
                </button>
                <span aria-hidden="true">{activeDateIndex + 1} / {normalizedDates.length}</span>
                <button
                  type="button"
                  onClick={() => setActiveDateKey(normalizedDates[activeDateIndex + 1])}
                  disabled={activeDateIndex < 0 || activeDateIndex >= normalizedDates.length - 1}
                  aria-label="Journée suivante"
                >
                  <span>Suivante</span>
                  <ChevronRight size={19} aria-hidden="true" />
                </button>
              </nav>
            </div>
          )}
          {!reuse && templates.length > 0 && normalizedDates.length > 1 && (
            <div className="formation-schedule__bulk">
              <label className="formation-schedule__bulk-toggle">
                <input
                  type="checkbox"
                  checked={applyAllDays}
                  onChange={(event) => {
                    const checked = event.target.checked
                    setApplyAllDays(checked)
                  }}
                />
                <span>Appliquer le même template à toutes les journées</span>
              </label>
              {applyAllDays && (
                <select
                  id="formation-template-bulk"
                  value={bulkTemplateId}
                  aria-label="Template à appliquer à toutes les journées"
                  onChange={(event) => {
                    setBulkTemplateId(event.target.value)
                  }}
                >
                  {templates.map((template) => (
                    <option key={template.id} value={String(template.id)}>{template.name}</option>
                  ))}
                </select>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
