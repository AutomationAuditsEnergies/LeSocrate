import { useState, useEffect, useRef, useCallback } from 'react'

// Composant partagé entre HRDashboard et CoursFoldersModal.
// Action signature pour les transitions irréversibles (lock/unlock + backup).
// Esthétique : track compact et calme, thumb clair, cadenas qui alterne
// ouvert/fermé selon l'état `locked`. Cohérent DESIGN.md "Slide to Confirm =
// signature interaction" avec une sortie franche, sans rebond décoratif.

const Icon = ({ name, className = '' }) => (
  <span className={`material-icons ${className}`}>{name}</span>
)

export default function SlideToConfirm({ locked, onConfirm, disabled, compact = false, onDark = false }) {
  const [dragX, setDragX] = useState(0)
  const [isDragging, setIsDragging] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [maxDrag, setMaxDrag] = useState(200)
  const containerRef = useRef(null)
  const isDraggingRef = useRef(false)
  const startXRef = useRef(0)
  const dragXRef = useRef(0)
  const onConfirmRef = useRef(onConfirm)

  useEffect(() => { onConfirmRef.current = onConfirm }, [onConfirm])

  const THUMB_SIZE = compact ? 30 : 36
  const THRESHOLD = 0.85

  const getMax = useCallback(() => {
    if (!containerRef.current) return 200
    return containerRef.current.offsetWidth - THUMB_SIZE - 8
  }, [THUMB_SIZE])

  useEffect(() => {
    const updateMax = () => setMaxDrag(getMax())
    updateMax()
    window.addEventListener('resize', updateMax)
    return () => window.removeEventListener('resize', updateMax)
  }, [getMax])

  useEffect(() => {
    const onMouseMove = (e) => {
      if (!isDraggingRef.current) return
      const newX = Math.max(0, Math.min(e.clientX - startXRef.current, getMax()))
      dragXRef.current = newX
      setDragX(newX)
    }
    const onMouseUp = () => {
      if (!isDraggingRef.current) return
      isDraggingRef.current = false
      setIsDragging(false)
      const max = getMax()
      if (dragXRef.current / max >= THRESHOLD) {
        dragXRef.current = max
        setDragX(max)
        setConfirmed(true)
        onConfirmRef.current()
        setTimeout(() => {
          setConfirmed(false)
          dragXRef.current = 0
          setDragX(0)
        }, 1200)
      } else {
        dragXRef.current = 0
        setDragX(0)
      }
    }
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }
  }, [getMax])

  const handleMouseDown = (e) => {
    e.preventDefault()
    if (disabled || confirmed) return
    isDraggingRef.current = true
    setIsDragging(true)
    startXRef.current = e.clientX - dragXRef.current
  }

  const handleTouchStart = (e) => {
    if (disabled || confirmed) return
    isDraggingRef.current = true
    setIsDragging(true)
    startXRef.current = e.touches[0].clientX - dragXRef.current
  }

  const handleTouchMove = (e) => {
    if (!isDraggingRef.current) return
    e.preventDefault()
    const newX = Math.max(0, Math.min(e.touches[0].clientX - startXRef.current, getMax()))
    dragXRef.current = newX
    setDragX(newX)
  }

  const handleTouchEnd = () => {
    if (!isDraggingRef.current) return
    isDraggingRef.current = false
    setIsDragging(false)
    const max = getMax()
    if (dragXRef.current / max >= THRESHOLD) {
      dragXRef.current = max
      setDragX(max)
      setConfirmed(true)
      onConfirmRef.current()
      setTimeout(() => {
        setConfirmed(false)
        dragXRef.current = 0
        setDragX(0)
      }, 1200)
    } else {
      dragXRef.current = 0
      setDragX(0)
    }
  }

  const progress = dragX / Math.max(1, maxDrag)

  const trackColor = onDark
    ? (compact ? 'rgba(255,255,255,0.2)' : 'rgba(255,255,255,0.15)')
    : '#0f172a'
  const trackBorder = onDark
    ? 'none'
    : compact
      ? '1px solid oklch(89.8% 0.014 260)'
      : 'none'
  const fillColor = onDark ? 'rgba(255,255,255,0.3)' : '#8B5CF6'
  const thumbIconColor = confirmed ? '#10b981' : '#1e293b'
  const labelColor = confirmed
    ? (onDark ? '#ffffff' : '#10b981')
    : (onDark ? 'white' : '#e2e8f0')

  return (
    <div
      ref={containerRef}
      className={`relative overflow-hidden select-none ${compact ? 'rounded-lg' : 'rounded-full'}`}
      style={{
        height: compact ? 36 : 44,
        backgroundColor: trackColor,
        border: trackBorder,
        boxSizing: 'border-box',
        opacity: disabled ? 0.5 : 1,
        cursor: disabled ? 'not-allowed' : 'default',
      }}
    >
      <div
        className={`absolute inset-y-0 left-0 ${compact ? 'rounded-lg' : 'rounded-full'}`}
        style={{
          width: dragX + THUMB_SIZE + 4,
          backgroundColor: fillColor,
          opacity: confirmed ? 0.5 : (compact ? 0.1 + progress * 0.35 : 0.18 + progress * 0.32),
          transition: isDragging ? 'none' : 'width 0.35s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.2s',
        }}
      />

      <div
        className="absolute inset-0 flex items-center justify-center pointer-events-none"
        style={{ paddingLeft: THUMB_SIZE + 16, paddingRight: 16 }}
      >
        <span
          className={`${compact ? 'text-sm' : 'text-[13px]'} font-medium whitespace-nowrap tracking-tight`}
          style={{
            fontFamily: 'Inter, sans-serif',
            color: labelColor,
            opacity: confirmed ? 1 : Math.max(0, 1 - progress * 2.2),
            transition: isDragging ? 'none' : 'opacity 0.22s',
          }}
        >
          {confirmed
            ? '✓ Confirmé'
            : compact
              ? (locked ? 'Déverrouiller' : 'Verrouiller')
              : locked
                ? "Glisser pour déverrouiller l'accès aux audios"
                : "Glisser pour verrouiller l'accès aux audios"}
        </span>
      </div>

      <div
        className={`absolute flex items-center justify-center ${compact ? 'rounded-md' : 'rounded-full'}`}
        style={{
          top: compact ? 3 : 4,
          left: 4 + dragX,
          width: THUMB_SIZE,
          height: THUMB_SIZE,
          backgroundColor: '#ffffff',
          cursor: disabled ? 'not-allowed' : isDragging ? 'grabbing' : 'grab',
          transition: isDragging ? 'none' : 'left 0.35s cubic-bezier(0.34, 1.56, 0.64, 1)',
          boxShadow: isDragging
            ? '0 6px 16px rgba(0, 0, 0, 0.25)'
            : compact
              ? '0 1px 2px rgba(15, 23, 42, 0.14)'
              : '0 2px 6px rgba(0, 0, 0, 0.18)',
          transform: isDragging ? 'scale(1.08)' : 'scale(1)',
        }}
        onMouseDown={handleMouseDown}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
        <Icon
          name={confirmed ? 'check' : locked ? 'lock' : 'lock_open'}
          className={compact ? 'text-base' : 'text-lg'}
          style={{ color: thumbIconColor }}
        />
      </div>
    </div>
  )
}

// Pipeline visuel des 3 étapes du backup audio (sauvegarde, suppression,
// audios ré-ouverts). Affiché juste en dessous de SlideToConfirm pendant
// que le job tourne (et un instant après pour montrer le done).
export function BackupPipeline({ job, colors, darkMode }) {
  const steps = [
    { label: 'Sauvegarde de tous les fichiers', step: 1 },
    { label: 'Suppression des audios actuels', step: 2 },
    { label: 'Les intervenants peuvent déposer des audios', step: 3 },
  ]

  const getStepState = (stepNum) => {
    if (job.step_status === 'error' && job.step === stepNum) return 'error'
    if (job.step > stepNum) return 'done'
    if (job.step === stepNum && job.step_status === 'running') return 'running'
    if (job.step === stepNum && job.step_status === 'done') return 'done'
    return 'pending'
  }

  return (
    <div
      className="rounded-xl p-4"
      style={{
        backgroundColor: colors.innerBg,
        border: `1px solid ${colors.border}`,
      }}
    >
      <div className="flex items-start gap-0">
        {steps.map((s, i) => {
          const state = getStepState(s.step)
          return (
            <div key={s.step} className="flex flex-1 flex-col items-center">
              <div className="flex w-full items-center">
                {i > 0 && (
                  <div
                    className="h-px flex-1 transition-colors duration-500"
                    style={{ backgroundColor: getStepState(steps[i - 1].step) === 'done' ? (darkMode ? '#8B5CF6' : '#10b981') : colors.border }}
                  />
                )}
                <div
                  className="relative flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full border-2 transition-all duration-500"
                  style={{
                    borderColor:
                      state === 'done' ? (darkMode ? '#8B5CF6' : '#10b981') :
                      state === 'running' ? '#8B5CF6' :
                      state === 'error' ? '#dc2626' :
                      (darkMode ? '#475569' : '#cbd5e1'),
                    backgroundColor:
                      state === 'done' ? (darkMode ? '#8B5CF6' : '#10b981') :
                      state === 'running' ? colors.innerBg :
                      state === 'error' ? (darkMode ? '#450a0a' : '#fee2e2') :
                      colors.cardBg,
                  }}
                >
                  {state === 'done' && (
                    <Icon name="check" className="text-sm" style={{ color: 'white' }} />
                  )}
                  {state === 'running' && (
                    <div
                      className="h-2.5 w-2.5 animate-spin rounded-full border-2 border-t-transparent"
                      style={{ borderColor: darkMode ? '#a855f7' : '#10b981', borderTopColor: 'transparent' }}
                    />
                  )}
                  {state === 'error' && (
                    <Icon name="close" className="text-sm" style={{ color: '#f87171' }} />
                  )}
                  {state === 'pending' && (
                    <div className="h-2 w-2 rounded-full" style={{ backgroundColor: darkMode ? '#475569' : '#cbd5e1' }} />
                  )}
                </div>
                {i < steps.length - 1 && (
                  <div
                    className="h-px flex-1 transition-colors duration-500"
                    style={{ backgroundColor: state === 'done' ? (darkMode ? '#8B5CF6' : '#10b981') : colors.border }}
                  />
                )}
              </div>
              <p
                className="mt-2 text-center text-[10px] leading-tight transition-colors duration-300"
                style={{
                  color:
                    state === 'done' ? (darkMode ? '#c084fc' : '#0f172a') :
                    state === 'running' ? colors.text :
                    state === 'error' ? (darkMode ? '#fca5a5' : '#dc2626') :
                    colors.textMuted,
                }}
              >
                {s.label}
                {state === 'running' && s.step === 1 && job.total > 0 && (
                  <span className="block" style={{ color: colors.textMuted }}>
                    {job.progress}/{job.total}
                  </span>
                )}
              </p>
            </div>
          )
        })}
      </div>

      {job.error && (
        <p className="mt-3 text-xs" style={{ color: darkMode ? '#fca5a5' : '#dc2626' }}>{job.error}</p>
      )}
    </div>
  )
}
