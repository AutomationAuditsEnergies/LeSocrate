import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Check,
  Download,
  Mic,
  Pause,
  PenLine,
  Play,
  Plus,
  ShieldCheck,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import { apiFetch } from '../api'


const CONSENT_COPY = 'Je confirme être propriétaire de cette voix ou disposer de son autorisation expresse pour créer et utiliser cette voix IA.'
const PREVIEW_TEXT = 'Bonjour, voici un aperçu de ma voix pour vos prochains cours.'


async function responsePayload(response) {
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload.error || `Une erreur est survenue (${response.status}).`)
  return payload
}


function durationLabel(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return ''
  const minutes = Math.floor(seconds / 60)
  const remaining = Math.round(seconds % 60)
  return minutes ? `${minutes} min ${String(remaining).padStart(2, '0')} s` : `${remaining} s`
}


function AudioInput({ label, hint, value, onChange, accept = 'audio/*', maxSeconds = 600 }) {
  const [recording, setRecording] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState('')
  const recorderRef = useRef(null)
  const streamRef = useRef(null)
  const chunksRef = useRef([])
  const elapsedRef = useRef(0)

  useEffect(() => () => streamRef.current?.getTracks().forEach((track) => track.stop()), [])

  useEffect(() => {
    if (!recording) return undefined
    const startedAt = Date.now() - elapsed * 1000
    const timer = window.setInterval(() => {
      const next = Math.floor((Date.now() - startedAt) / 1000)
      elapsedRef.current = next
      setElapsed(next)
      if (next >= maxSeconds) recorderRef.current?.stop()
    }, 250)
    return () => window.clearInterval(timer)
  }, [elapsed, maxSeconds, recording])

  const finishStream = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    setRecording(false)
  }

  const startRecording = async () => {
    setError('')
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setError('L’enregistrement direct n’est pas disponible dans ce navigateur.')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const preferredType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
        .find((type) => MediaRecorder.isTypeSupported(type))
      const recorder = new MediaRecorder(stream, preferredType ? { mimeType: preferredType } : undefined)
      streamRef.current = stream
      recorderRef.current = recorder
      chunksRef.current = []
      setElapsed(0)
      elapsedRef.current = 0
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunksRef.current.push(event.data)
      }
      recorder.onstop = () => {
        const mimeType = recorder.mimeType || preferredType || 'audio/webm'
        const extension = mimeType.includes('mp4') ? 'm4a' : 'webm'
        const blob = new Blob(chunksRef.current, { type: mimeType })
        onChange(new File([blob], `enregistrement-${Date.now()}.${extension}`, { type: mimeType }), elapsedRef.current)
        finishStream()
      }
      recorder.start(250)
      setRecording(true)
    } catch {
      finishStream()
      setError('Autorisez l’accès au microphone, puis réessayez.')
    }
  }

  const handleFile = (file) => {
    if (!file) return
    const audio = document.createElement('audio')
    const url = URL.createObjectURL(file)
    audio.preload = 'metadata'
    audio.onloadedmetadata = () => {
      onChange(file, Number.isFinite(audio.duration) ? audio.duration : 0)
      URL.revokeObjectURL(url)
    }
    audio.onerror = () => {
      onChange(file, 0)
      URL.revokeObjectURL(url)
    }
    audio.src = url
  }

  return (
    <div className="rounded-xl border border-[#D9D9DE] bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-[#18181B]">{label}</p>
          <p className="mt-1 text-xs leading-5 text-[#6B6B72]">{hint}</p>
        </div>
        {value?.file && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-[#F1F1F0] px-2.5 py-1 text-xs font-medium text-[#3F3F46]">
            <Check size={13} /> {durationLabel(value.duration) || 'Audio prêt'}
          </span>
        )}
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <label className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-lg border border-[#D4D4D8] bg-white px-3.5 py-2 text-sm font-semibold text-[#27272A] transition-colors hover:bg-[#F4F4F5] focus-within:ring-2 focus-within:ring-[#18181B]/40">
          <Upload size={16} /> Télécharger un audio
          <input type="file" accept={accept} className="sr-only" onChange={(event) => handleFile(event.target.files?.[0])} />
        </label>
        <button
          type="button"
          onClick={recording ? () => recorderRef.current?.stop() : startRecording}
          className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3.5 py-2 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/40 ${recording ? 'border-[#18181B] bg-[#18181B] text-white' : 'border-[#D4D4D8] bg-white text-[#27272A] hover:bg-[#F4F4F5]'}`}
        >
          {recording ? <Pause size={16} /> : <Mic size={16} />}
          {recording ? `Arrêter · ${durationLabel(elapsed)}` : 'Enregistrer'}
        </button>
      </div>
      {value?.file && <p className="mt-3 truncate text-xs text-[#71717A]">{value.file.name}</p>}
      {error && <p className="mt-3 text-xs font-medium text-[#B42318]" role="alert">{error}</p>}
    </div>
  )
}


function ProgressSteps({ step, mode }) {
  const labels = mode === 'clone'
    ? ['Consentement', 'Échantillon vocal', 'Calibrage']
    : ['Consentement', 'Identifiant Fish Audio', 'Calibrage']
  return (
    <ol className="grid grid-cols-3 gap-2" aria-label="Progression">
      {labels.map((label, index) => (
        <li key={label} className="min-w-0">
          <div className={`h-1 rounded-full ${index <= step ? 'bg-[#18181B]' : 'bg-[#E4E4E7]'}`} />
          <p className={`mt-2 truncate text-xs font-medium ${index <= step ? 'text-[#18181B]' : 'text-[#8A8A92]'}`}>{index + 1}. {label}</p>
        </li>
      ))}
    </ol>
  )
}


function VoiceWizard({ mode, onClose, onCreated }) {
  const [step, setStep] = useState(0)
  const [name, setName] = useState('')
  const [referenceId, setReferenceId] = useState('')
  const [transcript, setTranscript] = useState('')
  const [consentConfirmed, setConsentConfirmed] = useState(false)
  const [consentAudio, setConsentAudio] = useState(null)
  const [voiceAudio, setVoiceAudio] = useState(null)
  const [calibrationAudio, setCalibrationAudio] = useState(null)
  const [createdVoice, setCreatedVoice] = useState(null)
  const [analysis, setAnalysis] = useState(null)
  const [speed, setSpeed] = useState(1)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [previewUrl, setPreviewUrl] = useState('')

  useEffect(() => () => previewUrl && URL.revokeObjectURL(previewUrl), [previewUrl])

  const advanceConsent = () => {
    setError('')
    if (!name.trim() || !consentConfirmed || !consentAudio?.file) {
      setError('Renseignez le nom, confirmez le consentement et ajoutez sa preuve vocale.')
      return
    }
    setStep(1)
  }

  const createVoice = async () => {
    setError('')
    if (mode === 'clone' && !voiceAudio?.file) {
      setError('Ajoutez un échantillon vocal de 10 à 90 secondes.')
      return
    }
    if (mode === 'import' && !referenceId.trim()) {
      setError('Renseignez l’identifiant Fish Audio de la voix.')
      return
    }
    setBusy(true)
    try {
      const form = new FormData()
      form.append('name', name.trim())
      form.append('consent_confirmed', 'true')
      form.append('consent_sample', consentAudio.file)
      form.append('consent_sample_duration_sec', String(consentAudio.duration || ''))
      if (mode === 'clone') {
        form.append('voice_sample', voiceAudio.file)
        form.append('voice_sample_duration_sec', String(voiceAudio.duration || ''))
        if (transcript.trim()) form.append('transcript', transcript.trim())
      } else {
        form.append('fish_reference_id', referenceId.trim())
      }
      const response = await apiFetch(`/api/hr/ai-voices/${mode}`, { method: 'POST', body: form, timeoutMs: 240000 })
      const payload = await responsePayload(response)
      setCreatedVoice(payload.voice)
      setStep(2)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy(false)
    }
  }

  const calibrate = async () => {
    if (!calibrationAudio?.file) {
      setError('Ajoutez un enregistrement continu d’au moins une minute.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const form = new FormData()
      form.append('calibration_sample', calibrationAudio.file)
      form.append('calibration_sample_duration_sec', String(calibrationAudio.duration || ''))
      form.append('playback_speed', String(speed))
      const response = await apiFetch(`/api/hr/ai-voices/${createdVoice.id}/calibrate`, { method: 'POST', body: form, timeoutMs: 360000 })
      const payload = await responsePayload(response)
      setCreatedVoice(payload.voice)
      setAnalysis(payload.analysis)
      onCreated(payload.voice)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy(false)
    }
  }

  const preview = async () => {
    setBusy(true)
    setError('')
    try {
      const response = await apiFetch(`/api/hr/ai-voices/${createdVoice.id}/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: PREVIEW_TEXT, playback_speed: speed }),
        timeoutMs: 180000,
      })
      if (!response.ok) await responsePayload(response)
      if (previewUrl) URL.revokeObjectURL(previewUrl)
      setPreviewUrl(URL.createObjectURL(await response.blob()))
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-end justify-center bg-black/35 p-0 sm:items-center sm:p-6" role="dialog" aria-modal="true" aria-labelledby="voice-wizard-title">
      <div className="max-h-[96dvh] w-full overflow-y-auto rounded-t-2xl bg-white shadow-2xl sm:max-w-2xl sm:rounded-2xl">
        <header className="sticky top-0 z-10 flex items-start justify-between border-b border-[#E9E9EC] bg-white px-5 py-4 sm:px-7">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#71717A]">Parcours guidé</p>
            <h2 id="voice-wizard-title" className="mt-1 text-xl font-bold text-[#18181B]">{mode === 'clone' ? 'Créer une voix' : 'Importer une voix'}</h2>
          </div>
          <button type="button" onClick={onClose} className="flex h-11 w-11 items-center justify-center rounded-lg text-[#52525B] hover:bg-[#F4F4F5]" aria-label="Fermer"><X size={20} /></button>
        </header>

        <div className="px-5 py-6 sm:px-7">
          <ProgressSteps step={step} mode={mode} />

          {step === 0 && (
            <div className="mt-7 space-y-5">
              <div>
                <label htmlFor="voice-name" className="mb-2 block text-sm font-semibold text-[#27272A]">Nom de la voix</label>
                <input id="voice-name" value={name} onChange={(event) => setName(event.target.value)} maxLength={80} placeholder="Ex. Voix de Sophie" className="min-h-11 w-full rounded-lg border border-[#D4D4D8] px-3.5 text-sm outline-none focus:border-[#18181B] focus:ring-2 focus:ring-[#18181B]/10" />
              </div>
              <div className="rounded-xl bg-[#F7F7F6] p-4">
                <div className="flex gap-3"><ShieldCheck className="mt-0.5 shrink-0" size={20} /><div><p className="text-sm font-semibold text-[#18181B]">Phrase de consentement</p><p className="mt-2 text-sm leading-6 text-[#52525B]">« {CONSENT_COPY} »</p></div></div>
              </div>
              <AudioInput label="Preuve vocale du consentement" hint="Lisez clairement la phrase ci-dessus. Entre 2 et 30 secondes." value={consentAudio} onChange={(file, duration) => setConsentAudio({ file, duration })} maxSeconds={30} />
              <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-[#D9D9DE] p-4 text-sm leading-6 text-[#3F3F46]">
                <input type="checkbox" checked={consentConfirmed} onChange={(event) => setConsentConfirmed(event.target.checked)} className="mt-1 h-4 w-4 accent-[#18181B]" />
                <span>Je confirme que ce consentement est authentique et couvre la création ainsi que l’utilisation pédagogique de cette voix.</span>
              </label>
            </div>
          )}

          {step === 1 && mode === 'clone' && (
            <div className="mt-7 space-y-5">
              <div><h3 className="text-lg font-bold text-[#18181B]">Enregistrez la voix à cloner</h3><p className="mt-1 text-sm leading-6 text-[#6B6B72]">10 secondes minimum, 90 secondes maximum. Pour un résultat naturel, visez 30 à 60 secondes dans une pièce calme.</p></div>
              <AudioInput label="Échantillon vocal" hint="Une seule personne, sans musique ni écho, avec un débit naturel." value={voiceAudio} onChange={(file, duration) => setVoiceAudio({ file, duration })} maxSeconds={90} />
              <div><label htmlFor="voice-transcript" className="mb-2 block text-sm font-semibold text-[#27272A]">Transcription exacte <span className="font-normal text-[#71717A]">(facultatif)</span></label><textarea id="voice-transcript" value={transcript} onChange={(event) => setTranscript(event.target.value)} rows={4} placeholder="Collez ici ce qui est prononcé dans l’échantillon…" className="w-full rounded-lg border border-[#D4D4D8] px-3.5 py-3 text-sm outline-none focus:border-[#18181B] focus:ring-2 focus:ring-[#18181B]/10" /></div>
            </div>
          )}

          {step === 1 && mode === 'import' && (
            <div className="mt-7 space-y-5">
              <div><h3 className="text-lg font-bold text-[#18181B]">Identifiant Fish Audio</h3><p className="mt-1 text-sm leading-6 text-[#6B6B72]">Il s’agit du `reference_id` de la voix déjà créée chez Fish Audio, pas d’un fichier audio.</p></div>
              <div><label htmlFor="fish-reference-id" className="mb-2 block text-sm font-semibold text-[#27272A]">Reference ID</label><input id="fish-reference-id" value={referenceId} onChange={(event) => setReferenceId(event.target.value)} placeholder="802e3bc2b27e49c2995d23ef70e6ac89" className="min-h-11 w-full rounded-lg border border-[#D4D4D8] px-3.5 font-mono text-sm outline-none focus:border-[#18181B] focus:ring-2 focus:ring-[#18181B]/10" /></div>
              <a href="https://fish.audio/app" target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-[#D4D4D8] px-3.5 py-2 text-sm font-semibold text-[#27272A] hover:bg-[#F4F4F5]">Ouvrir Fish Audio <Download size={16} /></a>
            </div>
          )}

          {step === 2 && (
            <div className="mt-7 space-y-5">
              <div><h3 className="text-lg font-bold text-[#18181B]">Mesurez le débit naturel</h3><p className="mt-1 text-sm leading-6 text-[#6B6B72]">Enregistrez un extrait continu de 2 à 10 minutes. Fish Audio le transcrit pour calculer les mots par minute.</p></div>
              <AudioInput label="Échantillon de calibrage" hint="Au moins 1 minute, idéalement 2 à 5 minutes de parole naturelle." value={calibrationAudio} onChange={(file, duration) => setCalibrationAudio({ file, duration })} maxSeconds={600} />
              <div className="rounded-xl border border-[#D9D9DE] p-4">
                <div className="flex items-center justify-between gap-3"><label htmlFor="voice-speed" className="text-sm font-semibold text-[#18181B]">Vitesse finale</label><span className="rounded-full bg-[#F1F1F0] px-2.5 py-1 text-sm font-bold text-[#18181B]">{speed.toFixed(2)}×</span></div>
                <input id="voice-speed" type="range" min="0.75" max="1.35" step="0.05" value={speed} onChange={(event) => setSpeed(Number(event.target.value))} className="mt-4 w-full accent-[#18181B]" />
                <div className="mt-1 flex justify-between text-xs text-[#8A8A92]"><span>Plus posé</span><span>Naturel</span><span>Plus dynamique</span></div>
              </div>
              {analysis && <div className="grid grid-cols-2 gap-3"><div className="rounded-xl bg-[#F7F7F6] p-4"><p className="text-xs font-medium text-[#71717A]">Débit mesuré</p><p className="mt-1 text-2xl font-bold text-[#18181B]">{analysis.words_per_minute} <span className="text-sm font-medium">mots/min</span></p></div><div className="rounded-xl bg-[#F7F7F6] p-4"><p className="text-xs font-medium text-[#71717A]">Mots analysés</p><p className="mt-1 text-2xl font-bold text-[#18181B]">{analysis.word_count}</p></div></div>}
              {previewUrl && <audio controls autoPlay src={previewUrl} className="w-full" />}
            </div>
          )}

          {error && <p className="mt-5 rounded-lg bg-[#FEF2F2] px-3.5 py-3 text-sm font-medium text-[#B42318]" role="alert">{error}</p>}

          <footer className="mt-7 flex flex-wrap items-center justify-between gap-3 border-t border-[#E9E9EC] pt-5">
            <button type="button" onClick={step === 0 ? onClose : () => setStep((current) => Math.max(0, current - 1))} disabled={busy || (step === 2 && Boolean(analysis))} className="min-h-11 rounded-lg border border-[#D4D4D8] px-4 py-2 text-sm font-semibold text-[#3F3F46] hover:bg-[#F4F4F5] disabled:opacity-40">{step === 0 ? 'Annuler' : 'Retour'}</button>
            <div className="flex flex-wrap gap-2">
              {step === 2 && createdVoice && <button type="button" onClick={preview} disabled={busy} className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-[#18181B] px-4 py-2 text-sm font-semibold text-[#18181B] hover:bg-[#F4F4F5] disabled:opacity-50"><Play size={16} /> Tester la voix</button>}
              {step === 0 && <button type="button" onClick={advanceConsent} className="min-h-11 rounded-lg bg-[#18181B] px-5 py-2 text-sm font-semibold text-white hover:bg-[#27272A]">Continuer</button>}
              {step === 1 && <button type="button" onClick={createVoice} disabled={busy} className="min-h-11 rounded-lg bg-[#18181B] px-5 py-2 text-sm font-semibold text-white hover:bg-[#27272A] disabled:cursor-wait disabled:bg-[#A1A1AA]">{busy ? 'Création en cours…' : mode === 'clone' ? 'Cloner la voix' : 'Importer la voix'}</button>}
              {step === 2 && !analysis && <button type="button" onClick={calibrate} disabled={busy} className="min-h-11 rounded-lg bg-[#18181B] px-5 py-2 text-sm font-semibold text-white hover:bg-[#27272A] disabled:cursor-wait disabled:bg-[#A1A1AA]">{busy ? 'Analyse en cours…' : 'Analyser le débit'}</button>}
              {step === 2 && analysis && <button type="button" onClick={onClose} className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-[#18181B] px-5 py-2 text-sm font-semibold text-white hover:bg-[#27272A]"><Check size={16} /> Terminer</button>}
            </div>
          </footer>
        </div>
      </div>
    </div>
  )
}


function VoiceCard({ voice, onUpdated, onDeleted }) {
  const [speed, setSpeed] = useState(Number(voice.playback_speed || 1))
  const [saving, setSaving] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [audioUrl, setAudioUrl] = useState('')
  const [error, setError] = useState('')

  useEffect(() => () => audioUrl && URL.revokeObjectURL(audioUrl), [audioUrl])

  const saveSpeed = async () => {
    setSaving(true)
    setError('')
    try {
      const response = await apiFetch(`/api/hr/ai-voices/${voice.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ playback_speed: speed }) })
      const payload = await responsePayload(response)
      onUpdated(payload.voice)
    } catch (requestError) { setError(requestError.message) } finally { setSaving(false) }
  }

  const preview = async () => {
    setPreviewing(true)
    setError('')
    try {
      const response = await apiFetch(`/api/hr/ai-voices/${voice.id}/preview`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: PREVIEW_TEXT, playback_speed: speed }), timeoutMs: 180000 })
      if (!response.ok) await responsePayload(response)
      if (audioUrl) URL.revokeObjectURL(audioUrl)
      setAudioUrl(URL.createObjectURL(await response.blob()))
    } catch (requestError) { setError(requestError.message) } finally { setPreviewing(false) }
  }

  return (
    <article className="rounded-xl border border-[#D9D9DE] bg-white p-5">
      <div className="flex items-start gap-4">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-[#F1F1F0]"><Mic size={21} /></div>
        <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h3 className="truncate text-base font-bold text-[#18181B]">{voice.name}</h3><span className="rounded-full bg-[#F1F1F0] px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-[#52525B]">{voice.source === 'clone' ? 'Clonée' : 'Importée'}</span></div><p className="mt-1 truncate font-mono text-xs text-[#71717A]">{voice.fish_reference_id}</p></div>
        <button type="button" onClick={() => onDeleted(voice)} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-[#71717A] hover:bg-[#FEF2F2] hover:text-[#B42318]" aria-label={`Supprimer ${voice.name}`}><Trash2 size={17} /></button>
      </div>
      <div className="mt-5 grid gap-3 sm:grid-cols-2"><div className="rounded-lg bg-[#F7F7F6] p-3"><p className="text-xs text-[#71717A]">Débit naturel</p><p className="mt-1 text-sm font-bold text-[#18181B]">{voice.measured_wpm ? `${Math.round(voice.measured_wpm)} mots/min` : 'Non mesuré'}</p></div><div className="rounded-lg bg-[#F7F7F6] p-3"><p className="text-xs text-[#71717A]">Vitesse appliquée</p><p className="mt-1 text-sm font-bold text-[#18181B]">{speed.toFixed(2)}×</p></div></div>
      <div className="mt-4"><input type="range" min="0.75" max="1.35" step="0.05" value={speed} onChange={(event) => setSpeed(Number(event.target.value))} onMouseUp={saveSpeed} onTouchEnd={saveSpeed} className="w-full accent-[#18181B]" /></div>
      <div className="mt-4 flex flex-wrap gap-2"><button type="button" onClick={preview} disabled={previewing} className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-[#18181B] px-3.5 py-2 text-sm font-semibold text-[#18181B] hover:bg-[#F4F4F5] disabled:opacity-50"><Play size={16} /> {previewing ? 'Génération…' : 'Écouter'}</button>{saving && <span className="self-center text-xs text-[#71717A]">Enregistrement…</span>}</div>
      {audioUrl && <audio controls autoPlay src={audioUrl} className="mt-4 w-full" />}
      {error && <p className="mt-3 text-xs font-medium text-[#B42318]" role="alert">{error}</p>}
    </article>
  )
}


export default function AIVoicesView({ onVoicesChange }) {
  const [voices, setVoices] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [wizardMode, setWizardMode] = useState(null)

  const loadVoices = async () => {
    setError('')
    try {
      const payload = await responsePayload(await apiFetch('/api/hr/ai-voices'))
      setVoices(payload.voices || [])
    } catch (requestError) { setError(requestError.message) } finally { setLoading(false) }
  }

  useEffect(() => { loadVoices() }, [])
  useEffect(() => { onVoicesChange?.(voices) }, [onVoicesChange, voices])

  const updateVoice = (updated) => {
    setVoices((current) => current.map((voice) => voice.id === updated.id ? updated : voice))
  }

  const deleteVoice = async (voice) => {
    if (!window.confirm(`Supprimer la voix « ${voice.name} » de votre espace ?`)) return
    try {
      await responsePayload(await apiFetch(`/api/hr/ai-voices/${voice.id}`, { method: 'DELETE' }))
      setVoices((current) => current.filter((item) => item.id !== voice.id))
    } catch (requestError) { setError(requestError.message) }
  }

  const hasVoices = voices.length > 0
  const subtitle = useMemo(() => 'Créez, calibrez et mesurez les voix utilisées par vos professeurs.', [])

  return (
    <section className="h-full overflow-y-auto pb-14" aria-labelledby="ai-voices-title">
      <div className="mx-auto w-full max-w-5xl px-2 pt-6 sm:px-6 sm:pt-10">
        <header className="text-center"><h1 id="ai-voices-title" className="text-3xl font-bold tracking-[-0.035em] text-[#18181B] sm:text-4xl">Mes voix IA</h1><p className="mt-2 text-sm text-[#6B6B72] sm:text-base">{subtitle}</p></header>
        <div className="my-9 flex items-center gap-5" aria-hidden="true"><span className="h-px flex-1 bg-[#D9D9DE]" /><span className="text-xs font-semibold uppercase tracking-[0.3em] text-[#71717A]">Mes voix</span><span className="h-px flex-1 bg-[#D9D9DE]" /></div>

        {error && <p className="mb-5 rounded-lg bg-[#FEF2F2] px-4 py-3 text-sm font-medium text-[#B42318]" role="alert">{error}</p>}
        {loading ? <div className="py-20 text-center text-sm text-[#71717A]">Chargement des voix…</div> : !hasVoices ? (
          <div className="flex flex-col items-center py-8 text-center sm:py-12">
            <img src="/microphone-cartoon.svg" alt="" className="h-24 w-20 object-contain" />
            <h2 className="mt-3 text-xl font-bold text-[#18181B]">Aucune voix enregistrée</h2>
            <p className="mt-2 max-w-xl text-sm leading-6 text-[#6B6B72]">Clonez une voix à partir d’un échantillon vocal avec consentement, ou importez un identifiant Fish Audio existant.</p>
            <div className="mt-6 flex flex-wrap justify-center gap-3"><button type="button" onClick={() => setWizardMode('clone')} className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-[#18181B] bg-white px-4 py-2 text-sm font-semibold text-[#18181B] hover:bg-[#F4F4F5]"><PenLine size={16} /> Créer une voix</button><button type="button" onClick={() => setWizardMode('import')} className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-[#18181B] bg-white px-4 py-2 text-sm font-semibold text-[#18181B] hover:bg-[#F4F4F5]"><Download size={16} /> Importer une voix</button></div>
          </div>
        ) : (
          <div><div className="mb-5 flex flex-wrap items-center justify-between gap-3"><p className="text-sm text-[#6B6B72]">{voices.length} voix disponible{voices.length > 1 ? 's' : ''}</p><div className="flex gap-2"><button type="button" onClick={() => setWizardMode('import')} className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-[#D4D4D8] px-3.5 py-2 text-sm font-semibold text-[#27272A] hover:bg-[#F4F4F5]"><Download size={16} /> Importer</button><button type="button" onClick={() => setWizardMode('clone')} className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-[#18181B] px-3.5 py-2 text-sm font-semibold text-white hover:bg-[#27272A]"><Plus size={16} /> Créer une voix</button></div></div><div className="grid gap-4 lg:grid-cols-2">{voices.map((voice) => <VoiceCard key={voice.id} voice={voice} onUpdated={updateVoice} onDeleted={deleteVoice} />)}</div></div>
        )}
      </div>
      {wizardMode && <VoiceWizard mode={wizardMode} onClose={() => { setWizardMode(null); loadVoices() }} onCreated={updateVoice} />}
    </section>
  )
}
