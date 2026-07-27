import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  CircleCheck,
  WandSparkles,
} from 'lucide-react'

import { listDayScheduleTemplates } from '../dayScheduleTemplateApi.js'
import {
  TRAINING_WEEKDAYS,
  addCalendarDays,
  fillUnassignedTemplate,
  getCalendarMonthDays,
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
  const safeStartHint = startDateHint && startDateHint >= earliestSuggestedDate
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
  const [helperStartDate, setHelperStartDate] = useState(
    initialDates[0] || safeStartHint,
  )
  const [helperWeeks, setHelperWeeks] = useState(() => String(
    Math.max(1, Math.ceil((targetDayCount || 8) / initialWeeklyCount) + (targetDayCount ? 1 : 0)),
  ))
  const [helperDaysPerWeek, setHelperDaysPerWeek] = useState(String(initialWeeklyCount))
  const [preferredWeekdays, setPreferredWeekdays] = useState(initialPreferredDays)
  const [helperError, setHelperError] = useState('')
  const [lockedConfirmed, setLockedConfirmed] = useState(false)
  const [validationNow, setValidationNow] = useState(() => new Date())
  const [month, setMonth] = useState(() => initialMonth(initialDates[0] || safeStartHint))
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
  const unassignedCount = reuse
    ? 0
    : normalizedDates.filter((date) => !cleanAssignments[date]).length

  useEffect(() => {
    onChange?.({
      payload,
      valid: validation.valid && lockedConfirmed,
      validation,
      lockedConfirmed,
      dayCount: normalizedDates.length,
    })
  }, [lockedConfirmed, normalizedDates.length, onChange, payload, validation])

  const invalidateConfirmation = () => setLockedConfirmed(false)

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
    setHelperError('')
    invalidateConfirmation()
  }

  const toggleDate = (date) => {
    if (date < today) return
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
    invalidateConfirmation()
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
    invalidateConfirmation()
  }

  const applyTemplateToUnassigned = () => {
    setAssignments((current) => fillUnassignedTemplate(
      current,
      normalizedDates,
      bulkTemplateId,
    ))
    invalidateConfirmation()
  }

  return (
    <section className="formation-schedule" aria-labelledby="formation-schedule-title">
      <div className="formation-schedule__heading">
        <div>
          <h2 id="formation-schedule-title">Calendrier et déroulé</h2>
          <p>
            Le préremplissage vous fait gagner du temps. Seules les dates cochées ci-dessous seront retenues.
          </p>
        </div>
        <span className="formation-schedule__count">
          {normalizedDates.length} journée{normalizedDates.length > 1 ? 's' : ''}
          {reuse && expectedDayCount ? ` sur ${expectedDayCount}` : ''}
        </span>
      </div>

      <div className="formation-schedule__helper" aria-label="Préremplissage du calendrier">
        <div className="formation-schedule__helper-fields">
          <label>
            <span>Date de début</span>
            <input
              type="date"
              min={today}
              value={helperStartDate}
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

      <div className="formation-schedule__workspace">
        <div className="formation-schedule__calendar">
          <header>
            <button type="button" onClick={() => moveMonth(-1)} aria-label="Mois précédent">
              <ChevronLeft size={18} aria-hidden="true" />
            </button>
            <h3>{monthLabel(month.year, month.month)}</h3>
            <button type="button" onClick={() => moveMonth(1)} aria-label="Mois suivant">
              <ChevronRight size={18} aria-hidden="true" />
            </button>
          </header>
          <div className="formation-schedule__weekday-labels" aria-hidden="true">
            {TRAINING_WEEKDAYS.map((day) => <span key={day.id}>{day.short.slice(0, 1)}</span>)}
          </div>
          <div className="formation-schedule__month-grid">
            {calendarDays.map((day) => {
              const selected = selectedSet.has(day.date)
              const disabled = day.date < today
              return (
                <button
                  key={day.date}
                  type="button"
                  disabled={disabled}
                  data-outside={!day.inMonth}
                  aria-pressed={selected}
                  aria-label={`${selected ? 'Retirer' : 'Ajouter'} le ${formatLongDate(day.date)}`}
                  onClick={() => toggleDate(day.date)}
                >
                  <span>{day.day}</span>
                </button>
              )
            })}
          </div>
          <p className="formation-schedule__calendar-help">
            <CalendarDays size={15} aria-hidden="true" />
            Les dates finales sont triées chronologiquement pour former Journée 1, Journée 2, etc.
          </p>
        </div>

        <div className="formation-schedule__dates">
          <div className="formation-schedule__dates-header">
            <div>
              <h3>Dates retenues</h3>
              <p>{reuse ? 'Le déroulé du module reste inchangé.' : 'Une organisation est obligatoire pour chaque date.'}</p>
            </div>
            {!reuse && templates.length > 0 && (
              <div className="formation-schedule__bulk">
                <label htmlFor="formation-template-bulk">Template par défaut</label>
                <div>
                  <select
                    id="formation-template-bulk"
                    value={bulkTemplateId}
                    onChange={(event) => setBulkTemplateId(event.target.value)}
                  >
                    {templates.map((template) => (
                      <option key={template.id} value={String(template.id)}>{template.name}</option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={applyTemplateToUnassigned}
                    disabled={!bulkTemplateId || unassignedCount === 0}
                  >
                    Affecter aux non remplies ({unassignedCount})
                  </button>
                </div>
              </div>
            )}
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
          {!reuse && !templatesLoading && !templatesError && templates.length === 0 && (
            <div className="formation-schedule__empty">
              <p>La bibliothèque ne contient encore aucun template.</p>
              <span>Créez-en un depuis « Organisation des cours », puis revenez ici.</span>
            </div>
          )}
          {normalizedDates.length === 0 && (
            <div className="formation-schedule__empty">
              <p>Aucune date cochée.</p>
              <span>Utilisez le préremplissage ou cochez directement une date dans le calendrier.</span>
            </div>
          )}
          {normalizedDates.length > 0 && (
            <ol className="formation-schedule__date-list">
              {normalizedDates.map((date, index) => {
                const assignment = cleanAssignments[date] || ''
                const assignmentMissing = !reuse && !assignment
                const assignmentUnknown = assignment && !selectedTemplateIds.has(assignment)
                return (
                  <li key={date} data-invalid={assignmentMissing || assignmentUnknown}>
                    <span className="formation-schedule__day-index">{index + 1}</span>
                    <div>
                      <strong>{formatLongDate(date)}</strong>
                      <span>Journée {index + 1}</span>
                    </div>
                    {reuse ? (
                      <span className="formation-schedule__locked-layout">Déroulé conservé</span>
                    ) : (
                      <label>
                        <span className="sr-only">Template pour le {formatLongDate(date)}</span>
                        <select
                          value={assignment}
                          onChange={(event) => assignTemplate(date, event.target.value)}
                          aria-invalid={assignmentMissing || assignmentUnknown}
                        >
                          <option value="">Choisir un template</option>
                          {templates.map((template) => (
                            <option key={template.id} value={String(template.id)}>{template.name}</option>
                          ))}
                        </select>
                      </label>
                    )}
                  </li>
                )
              })}
            </ol>
          )}
        </div>
      </div>

      <div className="formation-schedule__review">
        <div className="formation-schedule__review-copy">
          <AlertTriangle size={19} aria-hidden="true" />
          <div>
            <h3>Validation définitive du planning</h3>
            <p>
              {reuse
                ? `Ce module contient ${expectedDayCount || 0} journées. Vous devez sélectionner exactement ${expectedDayCount || 0} nouvelles dates, sans modifier son déroulé.`
                : 'Après validation, les dates et l’organisation pédagogique seront verrouillées. La première journée doit commencer au moins 48 h plus tard.'}
            </p>
          </div>
        </div>

        {validation.errors.length > 0 && (
          <ul className="formation-schedule__errors" aria-label="Points à corriger">
            {validation.errors.map((error) => <li key={error}>{error}</li>)}
          </ul>
        )}

        <label className="formation-schedule__confirmation">
          <input
            type="checkbox"
            checked={lockedConfirmed && validation.valid}
            disabled={!validation.valid}
            onChange={(event) => setLockedConfirmed(event.target.checked)}
          />
          <span>
            <CircleCheck size={17} aria-hidden="true" />
            Je confirme ce calendrier et comprends qu’il ne pourra plus être modifié après validation.
          </span>
        </label>
      </div>
    </section>
  )
}
