import { useState, useEffect } from 'react'
import { apiUrl } from '../api'

const Icon = ({ name, className = '' }) => (
  <span className={`material-icons ${className}`}>{name}</span>
)

export default function ScheduleConfig() {
  const [platforms, setPlatforms] = useState([])
  const [mode, setMode] = useState('hiver')
  const [selectedIds, setSelectedIds] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  // Éditeur prompt TTS
  const [promptContent, setPromptContent] = useState('')
  const [promptLoading, setPromptLoading] = useState(true)
  const [promptSaving, setPromptSaving] = useState(false)
  const [promptSaved, setPromptSaved] = useState(false)
  const [promptOpen, setPromptOpen] = useState(false)

  useEffect(() => {
    fetchConfig()
    fetchPrompt()
  }, [])

  const fetchPrompt = async () => {
    try {
      const resp = await fetch(apiUrl('/api/hr/tts-prompt'), { credentials: 'include' })
      const data = await resp.json()
      if (data.success) setPromptContent(data.content || '')
    } catch (e) {
      console.error('Erreur chargement prompt:', e)
    } finally {
      setPromptLoading(false)
    }
  }

  const handleSavePrompt = async () => {
    setPromptSaving(true)
    setPromptSaved(false)
    try {
      const resp = await fetch(apiUrl('/api/hr/tts-prompt'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ content: promptContent }),
      })
      const data = await resp.json()
      if (data.success) {
        setPromptSaved(true)
        setTimeout(() => setPromptSaved(false), 3000)
      }
    } catch (e) {
      console.error('Erreur sauvegarde prompt:', e)
    } finally {
      setPromptSaving(false)
    }
  }

  const fetchConfig = async () => {
    try {
      const resp = await fetch(apiUrl('/api/hr/schedule-config'), { credentials: 'include' })
      const data = await resp.json()
      if (data.success) {
        setPlatforms(data.platforms)
        const affected = data.platforms.filter(p => p.playlist_mode !== null)
        if (affected.length > 0) {
          setMode(affected[0].playlist_mode)
          setSelectedIds(affected.map(p => p.id))
        }
      }
    } catch (e) {
      console.error('Erreur chargement config:', e)
    } finally {
      setLoading(false)
    }
  }

  const togglePlatform = (id) => {
    setSelectedIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    )
    setSaved(false)
  }

  const handleSave = async () => {
    setSaving(true)
    setSaved(false)
    try {
      const resp = await fetch(apiUrl('/api/hr/schedule-config'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ mode, platform_ids: selectedIds }),
      })
      const data = await resp.json()
      if (data.success) {
        setSaved(true)
        setTimeout(() => setSaved(false), 3000)
      }
    } catch (e) {
      console.error('Erreur sauvegarde:', e)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div style={{
        minHeight: '100vh',
        backgroundColor: '#0f172a',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        <div style={{
          width: 32, height: 32,
          border: '3px solid #334155',
          borderTopColor: '#8B5CF6',
          borderRadius: '50%',
          animation: 'spin 0.8s linear infinite',
        }} />
      </div>
    )
  }

  return (
    <div style={{
      minHeight: '100vh',
      backgroundColor: '#0f172a',
      color: '#f1f5f9',
      padding: '40px 20px',
      fontFamily: "'Poppins', sans-serif",
    }}>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg) } }
      `}</style>

      <div style={{ maxWidth: 600, margin: '0 auto' }}>
        {/* Header */}
        <a
          href="/dashboard-centre"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            color: '#94a3b8',
            textDecoration: 'none',
            fontSize: 14,
            marginBottom: 32,
          }}
        >
          <Icon name="arrow_back" /> Retour au dashboard
        </a>

        <h1 style={{
          fontSize: 24,
          fontWeight: 700,
          marginBottom: 8,
        }}>
          <Icon name="schedule" style={{ verticalAlign: 'middle', marginRight: 12, color: '#8B5CF6' }} />
          Planning saisonnier
        </h1>
        <p style={{ color: '#64748b', fontSize: 14, marginBottom: 40 }}>
          Configure l'ordre du bloc 4 (pause midi / cours / Q&R) selon la saison.
          Ce réglage s'applique une fois par changement d'heure.
        </p>

        {/* Mode toggle */}
        <div style={{
          backgroundColor: '#1e293b',
          borderRadius: 16,
          padding: 24,
          marginBottom: 24,
          border: '1px solid #334155',
        }}>
          <p style={{ fontSize: 13, fontWeight: 600, color: '#94a3b8', marginBottom: 16, textTransform: 'uppercase', letterSpacing: 1 }}>
            Mode actuel
          </p>

          <div style={{ display: 'flex', gap: 12 }}>
            {[
              { value: 'hiver', label: 'Heure d\'hiver', icon: 'ac_unit', desc: 'Pause → Cours → Q&R' },
              { value: 'ete', label: 'Heure d\'été', icon: 'wb_sunny', desc: 'Cours → Q&R → Pause' },
            ].map(opt => (
              <button
                key={opt.value}
                onClick={() => { setMode(opt.value); setSaved(false) }}
                style={{
                  flex: 1,
                  padding: '20px 16px',
                  borderRadius: 12,
                  border: `2px solid ${mode === opt.value ? '#8B5CF6' : '#334155'}`,
                  backgroundColor: mode === opt.value ? '#312e81' : '#0f172a',
                  color: mode === opt.value ? '#c4b5fd' : '#64748b',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                  textAlign: 'center',
                }}
              >
                <Icon name={opt.icon} style={{ fontSize: 32, display: 'block', margin: '0 auto 8px', color: mode === opt.value ? '#8B5CF6' : '#475569' }} />
                <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>{opt.label}</div>
                <div style={{ fontSize: 12, color: mode === opt.value ? '#a78bfa' : '#475569' }}>{opt.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Détail de l'ordre */}
        <div style={{
          backgroundColor: '#1e293b',
          borderRadius: 16,
          padding: 24,
          marginBottom: 24,
          border: '1px solid #334155',
        }}>
          <p style={{ fontSize: 13, fontWeight: 600, color: '#94a3b8', marginBottom: 16, textTransform: 'uppercase', letterSpacing: 1 }}>
            Ordre du bloc 4 en mode {mode === 'ete' ? 'été' : 'hiver'}
          </p>

          {(mode === 'ete' ? [
            { icon: 'menu_book', label: 'Cours Bloc 4', time: '12h20 – 13h05', color: '#3b82f6' },
            { icon: 'question_answer', label: 'Questions-Réponses IA', time: '13h05 – 13h15', color: '#f59e0b' },
            { icon: 'restaurant', label: 'Pause déjeuner', time: '13h15 – 14h45', color: '#22c55e' },
          ] : [
            { icon: 'restaurant', label: 'Pause déjeuner', time: '12h20 – 13h50', color: '#22c55e' },
            { icon: 'menu_book', label: 'Cours Bloc 4', time: '13h50 – 14h35', color: '#3b82f6' },
            { icon: 'question_answer', label: 'Questions-Réponses IA', time: '14h35 – 14h45', color: '#f59e0b' },
          ]).map((item, i) => (
            <div key={i} style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '12px 16px',
              borderRadius: 10,
              backgroundColor: '#0f172a',
              marginBottom: i < 2 ? 8 : 0,
            }}>
              <span style={{
                width: 28, height: 28, borderRadius: '50%',
                backgroundColor: item.color + '22',
                color: item.color,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 12, fontWeight: 700,
              }}>{i + 1}</span>
              <Icon name={item.icon} style={{ color: item.color, fontSize: 20 }} />
              <span style={{ flex: 1, fontSize: 14 }}>{item.label}</span>
              <span style={{ fontSize: 13, color: '#64748b', fontFamily: 'monospace' }}>{item.time}</span>
            </div>
          ))}
        </div>

        {/* Formations concernées */}
        <div style={{
          backgroundColor: '#1e293b',
          borderRadius: 16,
          padding: 24,
          marginBottom: 32,
          border: '1px solid #334155',
        }}>
          <p style={{ fontSize: 13, fontWeight: 600, color: '#94a3b8', marginBottom: 16, textTransform: 'uppercase', letterSpacing: 1 }}>
            Formations concernées
          </p>

          {platforms.map(p => (
            <label
              key={p.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: '14px 16px',
                borderRadius: 10,
                backgroundColor: selectedIds.includes(p.id) ? '#312e81' : '#0f172a',
                border: `1px solid ${selectedIds.includes(p.id) ? '#8B5CF6' : '#334155'}`,
                marginBottom: 8,
                cursor: 'pointer',
                transition: 'all 0.2s',
              }}
            >
              <input
                type="checkbox"
                checked={selectedIds.includes(p.id)}
                onChange={() => togglePlatform(p.id)}
                style={{ accentColor: '#8B5CF6', width: 18, height: 18 }}
              />
              <Icon name="school" style={{ color: selectedIds.includes(p.id) ? '#8B5CF6' : '#475569' }} />
              <span style={{ fontSize: 14, color: selectedIds.includes(p.id) ? '#e2e8f0' : '#94a3b8' }}>
                {p.name}
              </span>
            </label>
          ))}
        </div>

        {/* Éditeur prompt TTS */}
        <div style={{
          backgroundColor: '#1e293b',
          borderRadius: 16,
          padding: 24,
          marginBottom: 32,
          border: '1px solid #334155',
        }}>
          <button
            onClick={() => setPromptOpen(o => !o)}
            style={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              background: 'none',
              border: 'none',
              color: '#94a3b8',
              cursor: 'pointer',
              padding: 0,
              marginBottom: promptOpen ? 16 : 0,
            }}
          >
            <span style={{ fontSize: 13, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1, display: 'flex', alignItems: 'center', gap: 10 }}>
              <Icon name="auto_awesome" style={{ color: '#8B5CF6', fontSize: 18 }} />
              Prompt TTS (génération de contenu)
            </span>
            <Icon name={promptOpen ? 'expand_less' : 'expand_more'} />
          </button>

          {promptOpen && (
            <>
              <p style={{ fontSize: 12, color: '#64748b', marginBottom: 12, lineHeight: 1.5 }}>
                Ce prompt est utilisé pour générer le texte des cours en 3 passes.
                Les variables <code style={{ backgroundColor: '#0f172a', padding: '2px 6px', borderRadius: 4, color: '#c4b5fd' }}>{'{NOM_DU_TITRE_PROFESSIONNEL}'}</code>, <code style={{ backgroundColor: '#0f172a', padding: '2px 6px', borderRadius: 4, color: '#c4b5fd' }}>{'{NOM_DE_LA_SOUS_PARTIE}'}</code> et <code style={{ backgroundColor: '#0f172a', padding: '2px 6px', borderRadius: 4, color: '#c4b5fd' }}>{'{COLLER_LE_PROGRAMME_ICI}'}</code> sont remplacées automatiquement.
              </p>

              {promptLoading ? (
                <div style={{ padding: 40, textAlign: 'center', color: '#64748b', fontSize: 13 }}>
                  Chargement du prompt...
                </div>
              ) : (
                <>
                  <textarea
                    value={promptContent}
                    onChange={(e) => { setPromptContent(e.target.value); setPromptSaved(false) }}
                    spellCheck={false}
                    style={{
                      width: '100%',
                      minHeight: 360,
                      padding: 14,
                      borderRadius: 10,
                      border: '1px solid #334155',
                      backgroundColor: '#0f172a',
                      color: '#e2e8f0',
                      fontSize: 12,
                      fontFamily: "'Fira Code', 'Courier New', monospace",
                      lineHeight: 1.6,
                      resize: 'vertical',
                      outline: 'none',
                    }}
                  />

                  <button
                    onClick={handleSavePrompt}
                    disabled={promptSaving}
                    style={{
                      width: '100%',
                      padding: '12px',
                      marginTop: 12,
                      borderRadius: 10,
                      border: 'none',
                      backgroundColor: promptSaved ? '#16a34a' : '#8B5CF6',
                      color: 'white',
                      fontSize: 14,
                      fontWeight: 600,
                      cursor: promptSaving ? 'not-allowed' : 'pointer',
                      opacity: promptSaving ? 0.6 : 1,
                      transition: 'all 0.3s',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 8,
                    }}
                  >
                    <Icon name={promptSaved ? 'check_circle' : 'save'} />
                    {promptSaving ? 'Enregistrement...' : promptSaved ? 'Prompt enregistré !' : 'Enregistrer le prompt'}
                  </button>
                </>
              )}
            </>
          )}
        </div>

        {/* Save button */}
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            width: '100%',
            padding: '16px',
            borderRadius: 12,
            border: 'none',
            backgroundColor: saved ? '#16a34a' : '#8B5CF6',
            color: 'white',
            fontSize: 15,
            fontWeight: 600,
            cursor: saving ? 'not-allowed' : 'pointer',
            opacity: saving ? 0.6 : 1,
            transition: 'all 0.3s',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
          }}
        >
          <Icon name={saved ? 'check_circle' : 'save'} />
          {saving ? 'Enregistrement...' : saved ? 'Enregistré !' : 'Enregistrer la configuration'}
        </button>
      </div>
    </div>
  )
}
