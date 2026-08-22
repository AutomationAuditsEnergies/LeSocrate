import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  BookmarkPlus,
  Coffee,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  GripHorizontal,
  Menu,
  Minus,
  PlusCircle,
  Utensils,
  X,
} from 'lucide-react'

import {
  DAY_SCHEDULE_RULES,
  addScheduleSequence,
  formatScheduleMinute,
  getScheduleBlockDurationBounds,
  getScheduleSequenceDropMinute,
  getScheduleStats,
  normalizeScheduleTemplate,
  reflowScheduleBlocks,
  removeLastScheduleSequence,
  setSchedulePauseKind,
  updateScheduleBlockDuration,
  validateScheduleTemplate,
} from '../dayScheduleTemplates.js'
import {
  createDayScheduleTemplate,
  listDayScheduleTemplates,
} from '../dayScheduleTemplateApi.js'
import {
  TRAINING_WEEKDAYS,
  addCalendarDays,
  assignTemplateToAll,
  getCalendarMonthDays,
  isValidCalendarDate,
  normalizeSelectedTrainingDates,
  prefillTrainingDates,
  reconcileCustomDays,
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

const WEEKDAY_LABELS = Object.freeze([
  'Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche',
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

function normalizeInitialCustomDays(schedule) {
  return Object.fromEntries(
    Object.entries(schedule?.custom_days || {}).map(([date, definition]) => [
      date,
      normalizeScheduleTemplate({
        name: date,
        blocks: Array.isArray(definition) ? definition : definition?.blocks,
      }).blocks,
    ]),
  )
}

function addSequenceWithDefaultLunch(blocks) {
  const next = addScheduleSequence(blocks)
  const stats = getScheduleStats(next)
  if (stats.courseCount < DAY_SCHEDULE_RULES.minCourses || stats.lunchCount) return next
  const pauseIndexes = next.flatMap((block, index) => (
    block.block_type === 'pause' ? [index] : []
  ))
  const lunchIndex = pauseIndexes[Math.floor((pauseIndexes.length - 1) / 2)]
  return Number.isInteger(lunchIndex)
    ? setSchedulePauseKind(next, lunchIndex, 'lunch')
    : next
}

export default function FormationSchedulePlanner({
  reuse = false,
  expectedDayCount = null,
  initialSchedule = null,
  startDateHint = '',
  approximateDayCount = null,
  daysPerWeekHint = 2,
  preferredWeekdaysHint = [],
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
  const [customDays, setCustomDays] = useState(
    () => normalizeInitialCustomDays(initialSchedule),
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
  const [prefillOpen, setPrefillOpen] = useState(false)
  const [calendarFillCycle, setCalendarFillCycle] = useState(0)
  const [dropPreview, setDropPreview] = useState(null)
  const didInitialPrefill = useRef(false)
  const timelineRef = useRef(null)
  const prefillDialogRef = useRef(null)
  const templateSaveDialogRef = useRef(null)
  const eventResizeRef = useRef(null)
  const weekSwipeRef = useRef(null)
  const weekWheelRef = useRef(0)
  const pauseClickRef = useRef({ key: '', at: 0 })
  const [resizingEventKey, setResizingEventKey] = useState('')
  const [templateQuickSave, setTemplateQuickSave] = useState(null)

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
        || (retainedExists ? String(retainedTemplateId) : '')
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
    const dialog = prefillDialogRef.current
    if (!dialog) return
    if (prefillOpen && !dialog.open) dialog.showModal()
    if (!prefillOpen && dialog.open) dialog.close()
  }, [prefillOpen])

  useEffect(() => {
    const dialog = templateSaveDialogRef.current
    if (!dialog) return
    if (templateQuickSave && !dialog.open) dialog.showModal()
    if (!templateQuickSave && dialog.open) dialog.close()
  }, [templateQuickSave])

  useEffect(() => {
    if (reuse) return undefined
    const intervalId = window.setInterval(
      () => setValidationNow(new Date()),
      60_000,
    )
    return () => window.clearInterval(intervalId)
  }, [reuse])

  useEffect(() => {
    const frameId = window.requestAnimationFrame(() => {
      const timeline = timelineRef.current
      const firstHour = timeline?.querySelector('.formation-schedule__hour-slot')
      if (timeline && firstHour) {
        timeline.scrollTop = firstHour.getBoundingClientRect().height * 8
      }
    })
    return () => window.cancelAnimationFrame(frameId)
  }, [])

  useEffect(() => () => {
    const resize = eventResizeRef.current
    if (!resize) return
    window.removeEventListener('pointermove', resize.onMove)
    window.removeEventListener('pointerup', resize.onEnd)
    window.removeEventListener('pointercancel', resize.onEnd)
  }, [])

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
  const cleanCustomDays = useMemo(
    () => reconcileCustomDays(customDays, normalizedDates),
    [customDays, normalizedDates],
  )
  const validation = useMemo(() => validateFormationScheduleV2({
    selectedDates: normalizedDates,
    assignments: cleanAssignments,
    templates,
    reuse,
    expectedDayCount,
    now: validationNow,
    customDays: cleanCustomDays,
  }), [
    cleanAssignments,
    cleanCustomDays,
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
    customDays: cleanCustomDays,
  }), [cleanAssignments, cleanCustomDays, normalizedDates, reuse, templates])
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
  const activeCustomBlocks = activeDate ? cleanCustomDays[activeDate] || null : null
  const displayedDate = activeDate || helperStartDate
  const displayedDateIndex = activeDateIndex >= 0 ? activeDateIndex : 0
  const displayedDayCount = normalizedDates.length || Math.max(2, targetDayCount || 2)
  const scheduleDays = useMemo(() => {
    const templatesById = new Map(templates.map(
      (template) => [String(template.id), template],
    ))
    return normalizedDates.map((date, index) => {
      const templateId = cleanAssignments[date] || ''
      const customBlocks = cleanCustomDays[date]
      return {
        date,
        dayNumber: index + 1,
        label: formatLongDate(date),
        templateId,
        blocks: customBlocks || templatesById.get(templateId)?.blocks || [],
        templateName: customBlocks
          ? 'Journée personnalisée'
          : (reuse
            ? 'Déroulé conservé'
            : String(templatesById.get(templateId)?.name || '')),
      }
    })
  }, [cleanAssignments, cleanCustomDays, normalizedDates, reuse, templates])
  const scheduleDayByDate = useMemo(
    () => new Map(scheduleDays.map((day) => [day.date, day])),
    [scheduleDays],
  )
  const visibleWeekDates = useMemo(
    () => Array.from({ length: 7 }, (_, index) => addCalendarDays(focusedWeekStart, index)),
    [focusedWeekStart],
  )
  const visibleWeekLabel = weekLabel(visibleWeekDates[0], visibleWeekDates[6])

  const navigateWeek = (offset) => {
    const nextWeekStart = addCalendarDays(focusedWeekStart, offset * 7)
    setFocusedWeekStart(nextWeekStart)
    setMonth(initialMonth(addCalendarDays(nextWeekStart, 3)))
    setDropPreview(null)
    setTemplateQuickSave(null)
  }

  const beginWeekSwipe = (event) => {
    if (event.pointerType === 'mouse' || event.button !== 0) return
    if (event.target.closest('button, input, select, textarea, [draggable="true"], .formation-schedule__week-event')) return
    weekSwipeRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
    }
  }

  const finishWeekSwipe = (event) => {
    const swipe = weekSwipeRef.current
    weekSwipeRef.current = null
    if (!swipe || swipe.pointerId !== event.pointerId) return
    const deltaX = event.clientX - swipe.startX
    const deltaY = event.clientY - swipe.startY
    if (Math.abs(deltaX) < 60 || Math.abs(deltaX) <= Math.abs(deltaY) * 1.25) return
    navigateWeek(deltaX < 0 ? 1 : -1)
  }

  const handleWeekWheel = (event) => {
    if (Math.abs(event.deltaX) < 40 || Math.abs(event.deltaX) <= Math.abs(event.deltaY)) return
    const now = Date.now()
    if (now - weekWheelRef.current < 450) return
    event.preventDefault()
    weekWheelRef.current = now
    navigateWeek(event.deltaX > 0 ? 1 : -1)
  }
  const activeBlocks = scheduleDayByDate.get(activeDate)?.blocks || []
  const activeSequenceCount = getScheduleStats(activeBlocks).courseCount

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
    setCustomDays({})
  }, [applyAllDays, bulkTemplateId, normalizedDates])

  const togglePreferredWeekday = (weekday) => {
    setPreferredWeekdays((current) => (
      current.includes(weekday)
        ? current.filter((day) => day !== weekday)
        : [...current, weekday].sort()
    ))
    setHelperError('')
  }

  const applyPrefill = (event) => {
    event?.preventDefault()
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
    setCustomDays((current) => reconcileCustomDays(current, generated))
    setMonth(initialMonth(generated[0]))
    setFocusedWeekStart(weekStart(generated[0]))
    setActiveDateKey(generated[0])
    setHelperError('')
    setPrefillOpen(false)
    setCalendarFillCycle((current) => current + 1)
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
    setCustomDays((current) => {
      if (!current[date]) return current
      const next = { ...current }
      delete next[date]
      return next
    })
  }

  const activateDate = (date) => {
    if (date < today || !selectedDates.includes(date)) return
    setFocusedWeekStart(weekStart(date))
    setActiveDateKey(date)
  }

  const assignTemplate = (date, templateId) => {
    if (templateId === '__create__') {
      onCreateTemplate?.({
        ...payload,
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
    setCustomDays((current) => {
      if (!current[date]) return current
      const next = { ...current }
      delete next[date]
      return next
    })
  }

  const updateCustomDay = (date, update) => {
    if (reuse || !date || date < today) return
    const existing = scheduleDayByDate.get(date)?.blocks || []
    const nextBlocks = update(existing)
    setSelectedDates((current) => (
      current.includes(date) ? current : [...current, date]
    ))
    setActiveDateKey(date)
    setApplyAllDays(false)
    setAssignments((current) => {
      if (!current[date]) return current
      const next = { ...current }
      delete next[date]
      return next
    })
    setCustomDays((current) => ({ ...current, [date]: nextBlocks }))
  }

  const addSequenceToDay = (date, requestedStartMinute = null) => {
    const blocks = scheduleDayByDate.get(date)?.blocks || []
    if (getScheduleStats(blocks).courseCount >= DAY_SCHEDULE_RULES.maxCourses) return
    updateCustomDay(date, (existing) => {
      const next = addSequenceWithDefaultLunch(existing)
      if (existing.length || requestedStartMinute === null) return next
      return reflowScheduleBlocks(
        next,
        getScheduleSequenceDropMinute(requestedStartMinute),
      )
    })
  }

  const removeSequenceFromDay = (date) => {
    const blocks = scheduleDayByDate.get(date)?.blocks || []
    if (!getScheduleStats(blocks).courseCount) return
    updateCustomDay(date, removeLastScheduleSequence)
  }

  const openTemplateQuickSave = (date) => {
    const blocks = scheduleDayByDate.get(date)?.blocks || []
    if (!blocks.length) return
    setActiveDateKey(date)
    setTemplateQuickSave({
      date,
      name: `Journée ${formatLongDate(date)}`,
      error: '',
      saving: false,
      saved: false,
    })
  }

  const saveDayAsTemplate = async (event) => {
    event.preventDefault()
    if (!templateQuickSave || templateQuickSave.saving) return
    const blocks = scheduleDayByDate.get(templateQuickSave.date)?.blocks || []
    const result = validateScheduleTemplate({
      name: templateQuickSave.name,
      blocks,
    })
    if (!result.valid) {
      setTemplateQuickSave((current) => ({
        ...current,
        error: result.errors[0] || 'Cette journée ne peut pas encore être enregistrée.',
      }))
      return
    }

    setTemplateQuickSave((current) => ({ ...current, saving: true, error: '' }))
    try {
      const saved = await createDayScheduleTemplate(result.template)
      setTemplates((current) => [
        saved,
        ...current.filter((template) => String(template.id) !== String(saved.id)),
      ])
      setTemplateQuickSave((current) => ({
        ...current,
        name: saved.name,
        saving: false,
        saved: true,
      }))
    } catch (error) {
      setTemplateQuickSave((current) => ({
        ...current,
        saving: false,
        error: error.message || 'Impossible d’enregistrer ce template.',
      }))
    }
  }

  const toggleLunchForDay = (event, date, blocks, blockIndex) => {
    event.preventDefault()
    event.stopPropagation()
    const block = blocks[blockIndex]
    if (reuse || date < today || block?.block_type !== 'pause') return
    updateCustomDay(date, () => setSchedulePauseKind(
      blocks,
      blockIndex,
      block.pause_kind === 'lunch' ? 'short' : 'lunch',
    ))
  }

  const handleLunchPointerDown = (event, date, blocks, blockIndex) => {
    const block = blocks[blockIndex]
    const key = `${date}:${block?.block_key || blockIndex}`
    const now = event.timeStamp
    const previous = pauseClickRef.current

    if (previous.key === key && now - previous.at <= 500) {
      pauseClickRef.current = { key: '', at: 0 }
      toggleLunchForDay(event, date, blocks, blockIndex)
      return
    }

    pauseClickRef.current = { key, at: now }
  }

  const updateEventDuration = (date, blocks, blockIndex, duration) => {
    const block = blocks[blockIndex]
    if (reuse || date < today || !block) return
    const bounds = getScheduleBlockDurationBounds(block)
    const snapped = Math.round(Number(duration) / 5) * 5
    const constrained = Math.min(bounds.max, Math.max(bounds.min, snapped))
    updateCustomDay(date, () => updateScheduleBlockDuration(
      blocks,
      blockIndex,
      constrained,
    ))
  }

  const beginEventResize = (event, date, blocks, blockIndex) => {
    event.preventDefault()
    event.stopPropagation()
    if (reuse || date < today || !blocks[blockIndex]) return

    const hourSlot = event.currentTarget
      .closest('.formation-schedule__week-column')
      ?.querySelector('.formation-schedule__hour-slot')
    const pixelsPerMinute = Math.max(0.25, (hourSlot?.getBoundingClientRect().height || 60) / 60)
    const startY = event.clientY
    const original = blocks.map((block) => ({ ...block }))
    const initialDuration = original[blockIndex].duration_minutes
    const bounds = getScheduleBlockDurationBounds(original[blockIndex])
    const eventKey = `${date}:${original[blockIndex].block_key || blockIndex}`
    setResizingEventKey(eventKey)

    const onMove = (pointerEvent) => {
      const deltaSteps = Math.round(
        (pointerEvent.clientY - startY) / (pixelsPerMinute * 5),
      )
      const requestedDuration = initialDuration + (deltaSteps * 5)
      const nextDuration = Math.min(bounds.max, Math.max(bounds.min, requestedDuration))
      updateCustomDay(date, () => updateScheduleBlockDuration(
        original,
        blockIndex,
        nextDuration,
      ))
    }
    const onEnd = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onEnd)
      window.removeEventListener('pointercancel', onEnd)
      eventResizeRef.current = null
      setResizingEventKey('')
    }
    eventResizeRef.current = { onMove, onEnd }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onEnd, { once: true })
    window.addEventListener('pointercancel', onEnd, { once: true })
  }

  const shiftMonth = (offset) => {
    setMonth((current) => {
      const shifted = new Date(Date.UTC(current.year, current.month + offset, 1))
      return {
        year: shifted.getUTCFullYear(),
        month: shifted.getUTCMonth(),
      }
    })
  }

  return (
    <section className="formation-schedule" aria-label="Calendrier hebdomadaire de la formation">
      <aside className="formation-schedule__sidebar" data-open={sidebarOpen}>
        <div className="formation-schedule__side-header">
          <div className="formation-schedule__month-navigation" aria-label="Changer de mois">
            <button type="button" aria-label="Mois précédent" onClick={() => shiftMonth(-1)}>
              <ChevronLeft size={18} strokeWidth={1.75} aria-hidden="true" />
            </button>
            <div className="formation-schedule__side-month" aria-live="polite">
              {monthLabel(month.year, month.month)}
            </div>
            <button type="button" aria-label="Mois suivant" onClick={() => shiftMonth(1)}>
              <ChevronRight size={18} strokeWidth={1.75} aria-hidden="true" />
            </button>
          </div>
        </div>

        <div className="formation-schedule__mini-stage">
          <div className="formation-schedule__sidebar-calendar" key={`calendar-${calendarFillCycle}`}>
            <div className="formation-schedule__mini-calendar">
              <div className="formation-schedule__mini-weekdays" aria-hidden="true">
                {TRAINING_WEEKDAYS.map((day) => <span key={day.id}>{day.short.slice(0, 1)}</span>)}
            </div>
            <div className="formation-schedule__mini-grid" data-animate={calendarFillCycle > 0 || undefined}>
              {calendarDays.map((day, dayIndex) => (
                <button
                  key={day.date}
                  type="button"
                  disabled={day.date < today}
                  data-outside={!day.inMonth}
                  aria-pressed={selectedSet.has(day.date)}
                  aria-label={`${selectedSet.has(day.date) ? 'Retirer' : 'Ajouter'} le ${formatLongDate(day.date)}`}
                  style={{ '--calendar-day-index': dayIndex }}
                  onClick={() => toggleDate(day.date)}
                >
                  {String(day.day).padStart(2, '0')}
                </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        <section className="formation-schedule__organisation" aria-label="Organisation des journées">
          <nav className="formation-schedule__day-navigation" aria-label="Naviguer entre les journées">
            <button
              type="button"
              aria-label="Journée précédente"
              onClick={() => setActiveDateKey(normalizedDates[activeDateIndex - 1])}
              disabled={activeDateIndex <= 0}
            >
              <ChevronLeft size={17} strokeWidth={1.8} aria-hidden="true" />
            </button>
            <div className="formation-schedule__active-day-copy" aria-live="polite">
              <strong>{formatLongDate(displayedDate)}</strong>
              <span>Journée {displayedDateIndex + 1} sur {displayedDayCount}</span>
            </div>
            <button
              type="button"
              aria-label="Journée suivante"
              onClick={() => setActiveDateKey(normalizedDates[activeDateIndex + 1])}
              disabled={activeDateIndex < 0 || activeDateIndex >= normalizedDates.length - 1}
            >
              <ChevronRight size={17} strokeWidth={1.8} aria-hidden="true" />
            </button>
          </nav>
          <div className="formation-schedule__organisation-body">
            {reuse ? (
              <span className="formation-schedule__locked-layout">Déroulé conservé</span>
            ) : (
              <label className="formation-schedule__template-field">
                <span>Template</span>
                <span className="formation-schedule__template-select">
                  <select
                    value={applyAllDays
                      ? bulkTemplateId
                      : (activeCustomBlocks ? '__custom__' : activeAssignment)}
                    disabled={templatesLoading}
                    onChange={(event) => {
                      if (applyAllDays) {
                        if (event.target.value === '__create__') {
                          assignTemplate(activeDate || helperStartDate, '__create__')
                        } else {
                          setBulkTemplateId(event.target.value)
                        }
                        return
                      }
                      if (!activeDate) {
                        setSelectedDates([displayedDate])
                        setActiveDateKey(displayedDate)
                      }
                      assignTemplate(displayedDate, event.target.value)
                    }}
                    aria-invalid={Boolean(
                      activeDate
                      && !activeCustomBlocks
                      && (!activeAssignment || !selectedTemplateIds.has(activeAssignment)),
                    )}
                  >
                    <option value="">Choisir un template</option>
                    {activeCustomBlocks && <option value="__custom__">Journée personnalisée</option>}
                    {templates.map((template) => <option key={template.id} value={String(template.id)}>{template.name}</option>)}
                    <option value="__create__">Créer un template</option>
                  </select>
                  <ChevronDown size={16} strokeWidth={1.8} aria-hidden="true" />
                </span>
              </label>
            )}
            {!reuse && normalizedDates.length > 1 && (
              <label className="formation-schedule__bulk-toggle">
                <input
                  type="checkbox"
                  checked={applyAllDays}
                  onChange={(event) => {
                    const checked = event.target.checked
                    setApplyAllDays(checked)
                    if (checked) setBulkTemplateId(activeAssignment)
                  }}
                />
                <span>Appliquer ce template à toutes les journées</span>
              </label>
            )}
          </div>
        </section>

        <section className="formation-schedule__sequence" aria-labelledby="formation-sequence-title">
          <header>
            <div>
              <h2 id="formation-sequence-title">Séquence</h2>
              <p>À glisser dans le calendrier</p>
            </div>
            <span>{activeSequenceCount}/{DAY_SCHEDULE_RULES.maxCourses}</span>
          </header>
          <button
            type="button"
            className="formation-schedule__sequence-source"
            draggable={!reuse}
            disabled={reuse}
            onDragStart={(event) => {
              event.dataTransfer.effectAllowed = 'copy'
              event.dataTransfer.setData('application/x-day-sequence', 'course-qa-pause')
            }}
            onDragEnd={() => setDropPreview(null)}
            onClick={() => addSequenceToDay(activeDate || displayedDate)}
          >
            <PlusCircle size={14} aria-hidden="true" />
            Séquence pédagogique
          </button>
          <button
            type="button"
            disabled={reuse || activeSequenceCount === 0}
            onClick={() => removeSequenceFromDay(activeDate)}
          >
            <Minus size={13} aria-hidden="true" />
            Retirer la dernière séquence
          </button>
        </section>
      </aside>

      <div
        className="formation-schedule__week"
        onPointerDown={beginWeekSwipe}
        onPointerUp={finishWeekSwipe}
        onPointerCancel={() => { weekSwipeRef.current = null }}
        onWheel={handleWeekWheel}
      >
        <header className="formation-schedule__toolbar">
          <button type="button" className="formation-schedule__icon-button" onClick={() => setSidebarOpen((current) => !current)} aria-label={sidebarOpen ? 'Masquer le panneau' : 'Afficher le panneau'}>
            <Menu size={17} aria-hidden="true" />
          </button>
          <div className="formation-schedule__week-navigation">
            <button type="button" onClick={() => navigateWeek(-1)} aria-label="Semaine précédente" title="Semaine précédente">
              <ChevronLeft size={16} aria-hidden="true" />
            </button>
            <h1>{visibleWeekLabel}</h1>
            <button type="button" onClick={() => navigateWeek(1)} aria-label="Semaine suivante" title="Semaine suivante">
              <ChevronRight size={16} aria-hidden="true" />
            </button>
          </div>
          <div className="formation-schedule__toolbar-actions">
            <button
              type="button"
              className="formation-schedule__prefill-toolbar"
              aria-expanded={prefillOpen}
              aria-label="Remplir automatiquement les dates"
              title="Remplir automatiquement les dates"
              onClick={() => {
                setHelperError('')
                setPrefillOpen(true)
              }}
            >
              Remplir automatiquement
            </button>
          </div>
        </header>

        <div className="formation-schedule__day-headings">
          <span aria-hidden="true" />
          {visibleWeekDates.map((date, dayIndex) => {
            const blocks = scheduleDayByDate.get(date)?.blocks || []
            return (
              <div
                key={date}
                className="formation-schedule__day-heading"
                data-active={activeDate === date || undefined}
              >
                <span>{WEEKDAY_LABELS[dayIndex]}</span>
                {!reuse && blocks.length > 0 && (
                  <button
                    type="button"
                    className="formation-schedule__template-save-trigger"
                    aria-expanded={templateQuickSave?.date === date}
                    aria-label={`Enregistrer le ${formatLongDate(date)} comme template`}
                    onClick={() => openTemplateQuickSave(date)}
                  >
                    <BookmarkPlus size={12} aria-hidden="true" />
                  </button>
                )}
              </div>
            )
          })}
        </div>

        <div ref={timelineRef} className="formation-schedule__timeline">
          <div className="formation-schedule__time-axis" aria-hidden="true">
            {Array.from({ length: 25 }, (_, index) => (
              <span
                key={index}
                data-first={index === 0 || undefined}
                data-last={index === 24 || undefined}
                style={{ '--hour-index': index }}
              >
                {index === 24 ? '24:00' : `${String(index).padStart(2, '0')}:00`}
              </span>
            ))}
          </div>
          <div className="formation-schedule__week-grid" key={`week-${calendarFillCycle}`} data-animate={calendarFillCycle > 0 || undefined}>
            {visibleWeekDates.map((date, dayIndex) => {
              const scheduledDay = scheduleDayByDate.get(date)
              const blocks = scheduledDay?.blocks || []
              const isSelectedDay = selectedSet.has(date)
              const canDropSequence = (
                !reuse
                && date >= today
                && isSelectedDay
                && getScheduleStats(blocks).courseCount < DAY_SCHEDULE_RULES.maxCourses
              )
              const events = blocks.map((block, blockIndex) => ({
                block,
                blockIndex,
                dayIndex,
                start: Number(block.start_minute || 0) / 60,
                duration: Math.max(5, Number(block.duration_minutes || 0)) / 60,
                label: block.label || scheduledDay.templateName || `Journée ${scheduledDay.dayNumber}`,
                time: `${formatScheduleMinute(block.start_minute)}–${formatScheduleMinute(block.end_minute)}`,
                kind: block.block_type === 'pause'
                  ? (block.pause_kind === 'lunch' ? 'lunch' : 'pause')
                  : block.block_type,
                tone: (blockIndex % 5) + 1,
              }))
              const canEditDay = !reuse && date >= today && isSelectedDay
              const updateDropPreview = (event) => {
                const column = event.currentTarget
                const firstHour = column.querySelector('.formation-schedule__hour-slot')
                const hourHeight = firstHour?.getBoundingClientRect().height || 60
                const columnTop = column.getBoundingClientRect().top
                const pointerMinute = ((event.clientY - columnTop) / hourHeight) * 60
                const minute = getScheduleSequenceDropMinute(pointerMinute, blocks)
                setDropPreview((current) => (
                  current?.date === date && current.minute === minute
                    ? current
                    : { date, minute, mode: blocks.length ? 'append' : 'start' }
                ))
                return minute
              }
              return (
                <div
                  key={date}
                  className="formation-schedule__week-column"
                  role="button"
                  tabIndex={isSelectedDay ? 0 : -1}
                  data-weekend={dayIndex > 4}
                  data-active={activeDate === date}
                  data-drop-active={dropPreview?.date === date || undefined}
                  aria-pressed={isSelectedDay}
                  aria-disabled={!isSelectedDay}
                  aria-label={isSelectedDay
                    ? `Afficher le ${formatLongDate(date)}`
                    : `${formatLongDate(date)} non sélectionné. Sélectionnez cette journée dans le calendrier à gauche.`}
                  onClick={() => {
                    if (isSelectedDay) activateDate(date)
                  }}
                  onKeyDown={(event) => {
                    if (!isSelectedDay) return
                    if (event.target !== event.currentTarget) return
                    if (!['Enter', ' '].includes(event.key)) return
                    event.preventDefault()
                    activateDate(date)
                  }}
                  onDragEnter={(event) => {
                    if (!canDropSequence) return
                    if (!Array.from(event.dataTransfer.types).includes('application/x-day-sequence')) return
                    event.preventDefault()
                    updateDropPreview(event)
                  }}
                  onDragOver={(event) => {
                    if (!canDropSequence) return
                    if (!Array.from(event.dataTransfer.types).includes('application/x-day-sequence')) return
                    event.preventDefault()
                    event.dataTransfer.dropEffect = 'copy'
                    updateDropPreview(event)
                  }}
                  onDragLeave={(event) => {
                    if (!event.currentTarget.contains(event.relatedTarget)) setDropPreview(null)
                  }}
                  onDrop={(event) => {
                    if (!canDropSequence) return
                    if (event.dataTransfer.getData('application/x-day-sequence') !== 'course-qa-pause') return
                    event.preventDefault()
                    event.stopPropagation()
                    const startMinute = updateDropPreview(event)
                    setDropPreview(null)
                    addSequenceToDay(date, startMinute)
                  }}
                >
                  {Array.from({ length: 24 }, (_, hourIndex) => <span key={hourIndex} className="formation-schedule__hour-slot" />)}
                  {dropPreview?.date === date && (
                    <div
                      className="formation-schedule__drop-time-preview"
                      style={{ '--drop-preview-start': dropPreview.minute / 60 }}
                      role="status"
                      aria-live="polite"
                    >
                      <div className="formation-schedule__drop-time-preview-body">
                        <strong>
                          {dropPreview.mode === 'start' ? 'Début' : 'Ajout'} {formatScheduleMinute(dropPreview.minute)}
                        </strong>
                        <span>Relâchez pour placer la séquence</span>
                      </div>
                    </div>
                  )}
                  {events.map((event, eventIndex) => (
                    <article
                      key={`${date}:${event.block.block_key || eventIndex}`}
                      className="formation-schedule__week-event"
                      data-kind={event.kind}
                      data-tone={event.tone}
                      data-resizing={resizingEventKey === `${date}:${event.block.block_key || event.blockIndex}` || undefined}
                      style={{
                        '--event-start': event.start,
                        '--event-duration': event.duration,
                      }}
                    >
                      {canEditDay && event.block.block_type === 'pause' && (
                        <button
                          type="button"
                          className="formation-schedule__pause-toggle"
                          aria-pressed={event.block.pause_kind === 'lunch'}
                          aria-label={event.block.pause_kind === 'lunch'
                            ? 'Repasser cette pause en pause courte'
                            : 'Transformer cette pause en pause déjeuner'}
                          data-hint={event.block.pause_kind === 'lunch'
                            ? 'Double-cliquer pour repasser en pause courte'
                            : 'Double-cliquer pour transformer en pause déjeuner'}
                          title={event.block.pause_kind === 'lunch'
                            ? 'Double-cliquer pour repasser en pause courte'
                            : 'Double-cliquer pour transformer en pause déjeuner'}
                          onPointerDown={(pointerEvent) => {
                            handleLunchPointerDown(
                              pointerEvent,
                              date,
                              blocks,
                              event.blockIndex,
                            )
                          }}
                          onKeyDown={(keyEvent) => {
                            if (!['Enter', ' '].includes(keyEvent.key)) return
                            toggleLunchForDay(
                              keyEvent,
                              date,
                              blocks,
                              event.blockIndex,
                            )
                          }}
                        />
                      )}
                      <span className="formation-schedule__week-event-heading">
                        <span>
                          {event.block.block_type === 'pause'
                            ? (event.block.pause_kind === 'lunch'
                              ? <Utensils size={10} aria-hidden="true" />
                              : <Coffee size={10} aria-hidden="true" />)
                            : null}
                          {event.label}
                        </span>
                        <time>{event.time}</time>
                      </span>
                      {canEditDay && event.block.block_type === 'pause' && (
                        <span className="formation-schedule__week-event-description">
                          {event.block.pause_kind === 'lunch'
                            ? 'Pause déjeuner sélectionnée'
                            : 'Cliquer pour définir le déjeuner'}
                        </span>
                      )}
                      {canEditDay && (
                        <button
                          type="button"
                          className="formation-schedule__event-resize"
                          aria-label={`Modifier la durée de ${event.label}, ${getScheduleBlockDurationBounds(event.block).min} à ${getScheduleBlockDurationBounds(event.block).max} minutes`}
                          title={`Étirez pour régler la durée, ${getScheduleBlockDurationBounds(event.block).min} à ${getScheduleBlockDurationBounds(event.block).max} min`}
                          onClick={(clickEvent) => {
                            clickEvent.preventDefault()
                            clickEvent.stopPropagation()
                          }}
                          onPointerDown={(pointerEvent) => beginEventResize(
                            pointerEvent,
                            date,
                            blocks,
                            event.blockIndex,
                          )}
                          onKeyDown={(keyEvent) => {
                            if (!['ArrowUp', 'ArrowDown'].includes(keyEvent.key)) return
                            keyEvent.preventDefault()
                            keyEvent.stopPropagation()
                            updateEventDuration(
                              date,
                              blocks,
                              event.blockIndex,
                              event.block.duration_minutes + (keyEvent.key === 'ArrowDown' ? 5 : -5),
                            )
                          }}
                        >
                          <GripHorizontal size={14} aria-hidden="true" />
                        </button>
                      )}
                    </article>
                  ))}
                </div>
              )
            })}
          </div>
        </div>
      </div>

      <dialog
        ref={templateSaveDialogRef}
        className="formation-schedule__prefill-dialog formation-schedule__template-save-dialog"
        aria-labelledby="formation-template-save-title"
        onCancel={(event) => {
          event.preventDefault()
          setTemplateQuickSave(null)
        }}
        onClose={() => setTemplateQuickSave(null)}
      >
        {templateQuickSave && (
          <form
            className="formation-schedule__prefill-form formation-schedule__template-save-form"
            onSubmit={saveDayAsTemplate}
          >
            <header>
              <div>
                <p className="formation-schedule__prefill-eyebrow">Organisation</p>
                <h2 id="formation-template-save-title">Enregistrer comme template</h2>
                <p>Donnez un nom à cette journée pour pouvoir la réutiliser.</p>
              </div>
              <button type="button" onClick={() => setTemplateQuickSave(null)} aria-label="Fermer">
                <X size={16} aria-hidden="true" />
              </button>
            </header>
            <div className="formation-schedule__helper-content">
              {templateQuickSave.saved ? (
                <>
                  <p className="formation-schedule__template-save-success" role="status">
                    Template enregistré et prêt à être réutilisé.
                  </p>
                  <footer>
                    <span aria-hidden="true" />
                    <button
                      type="button"
                      className="formation-schedule__prefill-action"
                      onClick={() => setTemplateQuickSave(null)}
                    >
                      Fermer
                    </button>
                  </footer>
                </>
              ) : (
                <>
                  <label htmlFor="formation-template-save-name">
                    <span>Nom du template</span>
                    <input
                      id="formation-template-save-name"
                      value={templateQuickSave.name}
                      autoFocus
                      onChange={(event) => setTemplateQuickSave((current) => ({
                        ...current,
                        name: event.target.value,
                        error: '',
                      }))}
                    />
                  </label>
                  {templateQuickSave.error && (
                    <p className="formation-schedule__template-save-error" role="alert">
                      {templateQuickSave.error}
                    </p>
                  )}
                  <footer>
                    <button
                      type="button"
                      className="formation-schedule__prefill-cancel"
                      onClick={() => setTemplateQuickSave(null)}
                    >
                      Annuler
                    </button>
                    <button
                      type="submit"
                      className="formation-schedule__prefill-action"
                      disabled={templateQuickSave.saving || !templateQuickSave.name.trim()}
                    >
                      {templateQuickSave.saving ? 'Enregistrement…' : 'Enregistrer le template'}
                    </button>
                  </footer>
                </>
              )}
            </div>
          </form>
        )}
      </dialog>

      <dialog
        ref={prefillDialogRef}
        className="formation-schedule__prefill-dialog"
        aria-labelledby="formation-prefill-title"
        onCancel={(event) => {
          event.preventDefault()
          setPrefillOpen(false)
        }}
        onClose={() => setPrefillOpen(false)}
      >
        <form className="formation-schedule__prefill-form" onSubmit={applyPrefill}>
          <header>
            <div>
              <p className="formation-schedule__prefill-eyebrow">Planification</p>
              <h2 id="formation-prefill-title">Remplir automatiquement</h2>
              <p>Choisissez le rythme des journées à ajouter au calendrier.</p>
            </div>
            <button type="button" onClick={() => setPrefillOpen(false)} aria-label="Fermer">
              <X size={16} aria-hidden="true" />
            </button>
          </header>
          <div className="formation-schedule__helper-content">
            <label><span>Date de début</span><input type="date" min={earliestSuggestedDate} value={helperStartDate} onChange={(event) => { setHelperStartDate(event.target.value); setHelperError('') }} /></label>
            <div className="formation-schedule__helper-numbers">
              <label><span>Semaines</span><input type="number" min="1" max="104" value={helperWeeks} onChange={(event) => setHelperWeeks(event.target.value)} /></label>
              <label><span>Jours / semaine</span><input type="number" min="1" max="7" value={helperDaysPerWeek} onChange={(event) => setHelperDaysPerWeek(event.target.value)} /></label>
            </div>
            <fieldset>
              <legend>Jours préférés</legend>
              <div className="formation-schedule__weekdays">
                {TRAINING_WEEKDAYS.map((day) => <button key={day.id} type="button" aria-pressed={preferredWeekdays.includes(day.id)} onClick={() => togglePreferredWeekday(day.id)}>{day.short}</button>)}
              </div>
            </fieldset>
            {helperError && <p className="formation-schedule__inline-error" role="alert">{helperError}</p>}
            <footer>
              <button type="button" className="formation-schedule__prefill-cancel" onClick={() => setPrefillOpen(false)}>Annuler</button>
              <button type="submit" className="formation-schedule__prefill-action">Remplir les dates</button>
            </footer>
          </div>
        </form>
      </dialog>
    </section>
  )
}
