import React, { useState, useEffect } from 'react';
import { apiFetch } from '../api';
import PlayfulTemplate from '../components/slides/templates/PlayfulTemplate';
import ReflectionTemplate from '../components/slides/templates/ReflectionTemplate';
import CaseStudyTemplate from '../components/slides/templates/CaseStudyTemplate';
import FacilitatorTemplate from '../components/slides/templates/FacilitatorTemplate';
import ChartTemplate from '../components/slides/templates/ChartTemplate';
import StatsTemplate from '../components/slides/templates/StatsTemplate';
import StoryTemplate from '../components/slides/templates/StoryTemplate';
import RecapTemplate from '../components/slides/templates/RecapTemplate';
import AnalogyTemplate from '../components/slides/templates/AnalogyTemplate';
import WarningTemplate from '../components/slides/templates/WarningTemplate';
import TipTemplate from '../components/slides/templates/TipTemplate';
import OpinionTemplate from '../components/slides/templates/OpinionTemplate';
import TransitionTemplate from '../components/slides/templates/TransitionTemplate';
import DefinitionTemplate from '../components/slides/templates/DefinitionTemplate';
import ComparisonTemplate from '../components/slides/templates/ComparisonTemplate';
import StepsTemplate from '../components/slides/templates/StepsTemplate';
import ChecklistTemplate from '../components/slides/templates/ChecklistTemplate';
import QuotableTemplate from '../components/slides/templates/QuotableTemplate';
import PracticeExerciseTemplate from '../components/slides/templates/PracticeExerciseTemplate';
import BeforeAfterTemplate from '../components/slides/templates/BeforeAfterTemplate';
import { DeckWelcome, DeckAgenda, DeckDayProgram7Steps } from '../components/slides/templates/DeckTemplates';

const normalizeSourceText = (text = '') => String(text || '').replace(/\s+/g, ' ').trim();

function getSharedSourceKey(slide = {}) {
  const ref = slide.source_ref || {};
  return [
    ref.source_block_id ?? 'block',
    ref.word_start ?? 'start',
    ref.word_end ?? 'end',
  ].join(':');
}

function getSlideSourceHighlight(slide = {}, index = 0, slides = [], sourceText = '') {
  const sourceRef = slide.source_ref || {};
  const words = normalizeSourceText(sourceText).split(/\s+/).filter(Boolean);
  const sourceStart = Number(sourceRef.word_start || 0);
  if (!words.length) {
    return { start: 0, end: 0, sharedCount: 0, exact: false };
  }

  const highlightStart = Number(sourceRef.highlight_word_start);
  const highlightEnd = Number(sourceRef.highlight_word_end);
  if (
    Number.isFinite(highlightStart) &&
    Number.isFinite(highlightEnd) &&
    highlightEnd > highlightStart
  ) {
    const localStart = Math.max(0, Math.min(words.length, highlightStart - sourceStart));
    const localEnd = Math.max(localStart + 1, Math.min(words.length, highlightEnd - sourceStart));
    return { start: localStart, end: localEnd, sharedCount: 1, exact: true };
  }

  const key = getSharedSourceKey(slide);
  const shared = (slides || [])
    .map((candidate, candidateIndex) => ({ slide: candidate, index: candidateIndex }))
    .filter(item => getSharedSourceKey(item.slide) === key)
    .sort((a, b) => a.index - b.index);

  if (shared.length <= 1) {
    return { start: 0, end: words.length, sharedCount: 1, exact: false };
  }

  const sharedIndex = Math.max(0, shared.findIndex(item => item.index === index));
  const start = Math.round(sharedIndex * words.length / shared.length);
  const end = Math.max(start + 1, Math.round((sharedIndex + 1) * words.length / shared.length));
  return { start, end: Math.min(words.length, end), sharedCount: shared.length, exact: false };
}

function getSlideSourceExcerpt(slide = {}, index = 0, slides = []) {
  const sourceRef = slide.source_ref || {};
  const sourceText = normalizeSourceText(slide.source_text || '');
  const quote = normalizeSourceText(sourceRef.source_quote || slide.source_quote || '');
  if (quote) return quote;

  const words = sourceText.split(/\s+/).filter(Boolean);
  const highlight = getSlideSourceHighlight(slide, index, slides, sourceText);
  return words.slice(highlight.start, highlight.end).join(' ');
}

function renderHighlightedCourseSource(slide = {}, index = 0, slides = []) {
  const sourceText = normalizeSourceText(slide.source_text || '');
  if (!sourceText) return 'Texte source non disponible';

  const sourceRef = slide.source_ref || {};
  const quote = normalizeSourceText(sourceRef.source_quote || slide.source_quote || '');
  const directIndex = quote ? sourceText.indexOf(quote) : -1;
  if (directIndex >= 0 && quote.length) {
    return (
      <>
        {sourceText.slice(0, directIndex)}
        <mark>{sourceText.slice(directIndex, directIndex + quote.length)}</mark>
        {sourceText.slice(directIndex + quote.length)}
      </>
    );
  }

  const words = sourceText.split(/\s+/).filter(Boolean);
  const highlight = getSlideSourceHighlight(slide, index, slides, sourceText);
  if (!words.length || highlight.end <= highlight.start) {
    return sourceText;
  }

  return words.map((word, index) => (
    <React.Fragment key={`${word}-${index}`}>
      {index > 0 ? ' ' : ''}
      {index >= highlight.start && index < highlight.end ? <mark>{word}</mark> : word}
    </React.Fragment>
  ));
}

export default function GeneratedSlides() {
  const initialParams = new URLSearchParams(window.location.search);
  const [slides, setSlides] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [stats, setStats] = useState(null);
  const [transcription, setTranscription] = useState('');
  const [currentSlide, setCurrentSlide] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState('idle');
  const [generationMode, setGenerationMode] = useState('script');
  const [folderId, setFolderId] = useState(initialParams.get('folder_id') || '');
  const [jobId, setJobId] = useState(initialParams.get('job_id') || '');
  const [maxSlides, setMaxSlides] = useState(initialParams.get('max_slides') || '60');
  const [slidePace, setSlidePace] = useState(initialParams.get('pace') || 'normal');
  const [showTimeline, setShowTimeline] = useState(false);
  const [pipelineDebug, setPipelineDebug] = useState(null);
  const [showPipeline, setShowPipeline] = useState(false);
  const [sourceView, setSourceView] = useState('course');

  useEffect(() => {
    fetchExistingSlides();
  }, []);

  useEffect(() => {
    setSourceView('course');
  }, [currentSlide]);

  const fetchExistingSlides = async () => {
    try {
      const query = folderId ? `?folder_id=${encodeURIComponent(folderId)}` : '';
      const response = await apiFetch(`/api/slides/data${query}`);
      const data = await response.json();

      if (data.status === 'success' && data.slides) {
        setSlides(data.slides);
        setStats(data.stats || null);
        setTimeline(data.timeline || []);
        setTranscription(data.transcription || '');
        setPipelineDebug(data.pipeline_debug || null);
        setGenerationMode(data.generation_mode || data.stats?.generation_mode || 'script');
        setStatus('success');
      }
    } catch (err) {
      console.log('Pas de slides existantes');
    }
  };

  const generateSlidesFromScript = async () => {
    setLoading(true);
    setError(null);
    setStatus('generating');
    setGenerationMode('script');

    try {
      const response = await apiFetch('/api/slides/generate-from-script', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          folder_id: folderId ? Number(folderId) : null,
          job_id: jobId ? Number(jobId) : null,
          max_slides: Number(maxSlides) || 60,
          pace: slidePace
        })
      });

      const data = await response.json();

      if (data.status === 'success') {
        setSlides(data.slides);
        setStats(data.stats || null);
        setTimeline(data.timeline || []);
        setPipelineDebug(data.pipeline_debug || null);
        setGenerationMode(data.generation_mode || data.stats?.generation_mode || 'script');
        setCurrentSlide(0);
        setStatus('success');
      } else {
        setError(data.message || 'Erreur lors de la generation depuis le texte');
        setStatus('error');
      }
    } catch (err) {
      setError(`Erreur de connexion: ${err.message}`);
      setStatus('error');
    } finally {
      setLoading(false);
    }
  };

  const generateSlidesFromAudio = async () => {
    setLoading(true);
    setError(null);
    setStatus('generating');
    setGenerationMode('audio_v3');

    try {
      const response = await apiFetch('/api/slides/generate-v3', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          audio_id: 1,
          max_duration: 300
        })
      });

      const data = await response.json();

      if (data.status === 'success') {
        setSlides(data.slides);
        setStats(data.stats || null);
        setTimeline(data.timeline || []);
        setPipelineDebug(data.pipeline_debug || null);
        setGenerationMode(data.generation_mode || 'audio_v3');
        setCurrentSlide(0);
        setStatus('success');
      } else {
        setError(data.message || 'Erreur lors de la generation audio');
        setStatus('error');
      }
    } catch (err) {
      setError(`Erreur de connexion: ${err.message}`);
      setStatus('error');
    } finally {
      setLoading(false);
    }
  };

  const clearSlides = async () => {
    try {
      await apiFetch('/api/slides/clear', { method: 'POST' });
      setSlides([]);
      setTimeline([]);
      setStats(null);
      setTranscription('');
      setPipelineDebug(null);
      setGenerationMode('script');
      setCurrentSlide(0);
      setStatus('idle');
      setError(null);
    } catch (err) {
      console.error('Erreur lors du clear:', err);
    }
  };

  const renderSlide = (slide) => {
    const commonProps = {
      badge: "TP-CRCD",
      brandName: "SALES HACKING"
    };
    const isSevenStepDayProgram = Array.isArray(slide.data?.items) && slide.data.items.length === 7;

    switch (slide.template_type) {
      case 'welcome':
        return <DeckWelcome {...slide.data} {...commonProps} />;
      case 'day_program':
        return isSevenStepDayProgram
          ? <DeckDayProgram7Steps {...slide.data} {...commonProps} />
          : <DeckAgenda {...slide.data} {...commonProps} />;
      case 'day_program_7_steps':
        return <DeckDayProgram7Steps {...slide.data} {...commonProps} />;
      case 'context':
        return <ContextSlideTemplate {...slide.data} {...commonProps} />;
      case 'definition':
        return <DefinitionTemplate {...slide.data} {...commonProps} />;
      case 'comparison':
        return <ComparisonTemplate {...slide.data} {...commonProps} />;
      case 'beforeafter':
        return <BeforeAfterTemplate {...slide.data} {...commonProps} />;
      case 'steps':
        return <StepsTemplate {...slide.data} {...commonProps} />;
      case 'checklist':
        return <ChecklistTemplate {...slide.data} {...commonProps} />;
      case 'quotable':
        return <QuotableTemplate {...slide.data} {...commonProps} />;
      case 'exercise':
        return <PracticeExerciseTemplate {...slide.data} {...commonProps} />;
      case 'playful':
        return <PlayfulTemplate {...slide.data} {...commonProps} />;
      case 'reflection':
        return <ReflectionTemplate {...slide.data} {...commonProps} />;
      case 'casestudy':
        return <CaseStudyTemplate {...slide.data} {...commonProps} />;
      case 'facilitator':
        return <FacilitatorTemplate {...slide.data} {...commonProps} />;
      case 'chart':
        return <ChartTemplate {...slide.data} {...commonProps} />;
      case 'stats':
        return <StatsTemplate {...slide.data} {...commonProps} />;
      case 'story':
        return <StoryTemplate {...slide.data} {...commonProps} />;
      case 'recap':
        return <RecapTemplate {...slide.data} {...commonProps} />;
      case 'analogy':
        return <AnalogyTemplate {...slide.data} {...commonProps} />;
      case 'warning':
        return <WarningTemplate {...slide.data} {...commonProps} />;
      case 'tip':
        return <TipTemplate {...slide.data} {...commonProps} />;
      case 'opinion':
        return <OpinionTemplate {...slide.data} {...commonProps} />;
      case 'transition':
        return <TransitionTemplate {...slide.data} {...commonProps} />;
      default:
        return (
          <div style={{
            padding: '2rem',
            background: '#fff',
            borderRadius: '8px',
            textAlign: 'center'
          }}>
            <p>Template non reconnu: {slide.template_type}</p>
            <pre style={{ textAlign: 'left', fontSize: '0.8rem' }}>
              {JSON.stringify(slide.data, null, 2)}
            </pre>
          </div>
        );
    }
  };

  const ContextSlideTemplate = ({ formation_name, chapter, label, badge = "TP-CRCD", brandName = "SALES HACKING" }) => (
    <div style={{
      width: '90vw',
      maxWidth: '1200px',
      aspectRatio: '16 / 9',
      background: '#f8fafc',
      color: '#0f172a',
      fontFamily: 'Inter, Poppins, system-ui, sans-serif',
      display: 'flex',
      flexDirection: 'column',
      padding: '3rem 3.5rem',
      boxSizing: 'border-box',
      boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: '#64748b', fontSize: '1rem', fontWeight: 800 }}>
        <span>{badge}</span>
        <span>{brandName}</span>
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
        <div style={{ color: '#dc2626', fontSize: '1rem', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '1rem' }}>
          {label || 'Séquence en cours'}
        </div>
        <div style={{ fontSize: 'clamp(2rem, 4vw, 4.2rem)', lineHeight: 1.08, fontWeight: 900, maxWidth: '860px' }}>
          {formation_name || 'Formation'}
        </div>
        <div style={{ marginTop: '1.6rem', height: '3px', width: '88px', background: '#dc2626', borderRadius: '999px' }} />
        <div style={{ marginTop: '1.6rem', fontSize: 'clamp(1.4rem, 2.7vw, 2.8rem)', lineHeight: 1.25, fontWeight: 800, color: '#334155', maxWidth: '820px' }}>
          {chapter || 'Chapitre en cours'}
        </div>
      </div>
    </div>
  );

  const WelcomeSlideTemplate = ({ title = "Bienvenue", subtitle, formation_name, day_label, badge = "TP-CRCD", brandName = "SALES HACKING" }) => (
    <div style={{
      width: '90vw',
      maxWidth: '1200px',
      aspectRatio: '16 / 9',
      background: '#f8fafc',
      color: '#0f172a',
      fontFamily: 'Inter, Poppins, system-ui, sans-serif',
      display: 'flex',
      flexDirection: 'column',
      padding: '3rem 3.5rem',
      boxSizing: 'border-box',
      boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', color: '#64748b', fontSize: '1rem', fontWeight: 800 }}>
        <span>{badge}</span>
        <span>{brandName}</span>
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
        <div style={{ color: '#dc2626', fontSize: '1.05rem', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '1rem' }}>
          {day_label || subtitle || 'Journée de formation'}
        </div>
        <div style={{ fontSize: 'clamp(3rem, 6vw, 6rem)', lineHeight: 1, fontWeight: 950 }}>
          {title}
        </div>
        <div style={{ marginTop: '1.6rem', height: '3px', width: '96px', background: '#dc2626', borderRadius: '999px' }} />
        <div style={{ marginTop: '1.7rem', fontSize: 'clamp(1.5rem, 3vw, 3rem)', lineHeight: 1.18, fontWeight: 850, color: '#334155', maxWidth: '900px' }}>
          {formation_name || subtitle || 'Formation'}
        </div>
      </div>
    </div>
  );

  const DayProgramSlideTemplate = ({ title = "Programme de la journée", items = [], day_label, formation_name, badge = "TP-CRCD", brandName = "SALES HACKING" }) => {
    const safeItems = Array.isArray(items) && items.length ? items.slice(0, 7) : ['Accueil et objectifs', 'Thèmes clés', 'Synthèse et questions'];
    return (
      <div style={{
        width: '90vw',
        maxWidth: '1200px',
        aspectRatio: '16 / 9',
        background: '#f8fafc',
        color: '#0f172a',
        fontFamily: 'Inter, Poppins, system-ui, sans-serif',
        display: 'flex',
        flexDirection: 'column',
        padding: '3rem 3.5rem',
        boxSizing: 'border-box',
        boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', color: '#64748b', fontSize: '1rem', fontWeight: 800 }}>
          <span>{badge}</span>
          <span>{brandName}</span>
        </div>
        <div style={{ marginTop: '2rem', color: '#dc2626', fontSize: '1rem', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          {day_label || formation_name || 'Séquence du jour'}
        </div>
        <div style={{ marginTop: '0.75rem', fontSize: 'clamp(2.4rem, 4.4vw, 4.4rem)', lineHeight: 1.05, fontWeight: 950 }}>
          {title}
        </div>
        <div style={{ marginTop: '2rem', display: 'grid', gridTemplateColumns: '1fr', gap: '0.65rem', maxWidth: '980px' }}>
          {safeItems.map((item, index) => (
            <div key={index} style={{ display: 'grid', gridTemplateColumns: '42px 1fr', gap: '0.85rem', alignItems: 'center', padding: '0.8rem 1rem', background: '#eef2f7', borderLeft: '4px solid #dc2626', borderRadius: '8px' }}>
              <div style={{ color: '#dc2626', fontWeight: 950, fontSize: '1.15rem' }}>{String(index + 1).padStart(2, '0')}</div>
              <div style={{ fontSize: 'clamp(1rem, 1.7vw, 1.55rem)', fontWeight: 800, color: '#334155', lineHeight: 1.25 }}>{item}</div>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const formatTime = (seconds) => {
    if (seconds === undefined || seconds === null) return '--:--';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const getEventTypeColor = (type) => {
    const colors = {
      // Types pedagogiques de base
      story: '#F59E0B',
      definition: '#3B82F6',
      concept: '#8B5CF6',
      example: '#10B981',
      process: '#EC4899',
      comparison: '#6366F1',
      data: '#EF4444',
      recap: '#F97316',
      // Types narratifs/rhetoriques
      analogy: '#14B8A6',    // Teal
      warning: '#DC2626',    // Rouge vif
      tip: '#22C55E',        // Vert
      opinion: '#A855F7',    // Violet clair
      // Types structurels
      transition: '#6B7280',
      filler: '#9CA3AF'
    };
    return colors[type] || '#6B7280';
  };

  const isScriptMode = (generationMode || '').startsWith('script') || (stats?.generation_mode || '').startsWith('script');
  const statsItems = stats
    ? (isScriptMode
      ? [
          { label: 'Source', value: 'Texte DB' },
          { label: 'Mots', value: stats.source_words || 0 },
          { label: 'Sources', value: stats.source_blocks || 0 },
          { label: 'Rythme', value: stats.pace || slidePace },
          ...(stats.slide_anchors_found ? [{ label: 'Anchors', value: stats.slide_anchors_found }] : []),
          { label: 'Slides max/jour', value: stats.max_slides || maxSlides },
          { label: 'Slides', value: stats.slides_generated || slides.length },
          ...(stats.audio_sync?.enabled ? [{ label: 'Sync audio', value: stats.audio_sync.mode || 'active' }] : [])
        ]
      : [
          { label: 'Duree audio', value: formatTime(stats.audio_duration) },
          { label: 'Chunks', value: stats.chunks_processed },
          { label: 'Evenements', value: stats.events_detected },
          { label: 'Apres fusion', value: stats.events_after_fusion },
          { label: 'Slides', value: stats.slides_generated }
        ])
    : [];
  const sourceDebugItems = isScriptMode
    ? (pipelineDebug?.source_blocks || [])
    : (pipelineDebug?.raw_events || []);

  return (
    <div style={{
      margin: 0,
      padding: '2rem',
      backgroundColor: '#1a1a2e',
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center'
    }}>
      {/* Header */}
      <div style={{
        width: '100%',
        maxWidth: '1200px',
        marginBottom: '2rem',
        textAlign: 'center'
      }}>
        <h1 style={{
          fontFamily: 'Fredoka, sans-serif',
          fontSize: '2.5rem',
          color: '#fff',
          marginBottom: '0.5rem'
        }}>
          Slides depuis texte
        </h1>
        <p style={{
          fontFamily: 'Poppins, sans-serif',
          color: '#aaa',
          fontSize: '1rem'
        }}>
          Pipeline texte final DB vers thèmes, points clés et templates React
        </p>
      </div>

      {/* Stats */}
      {stats && (
        <div style={{
          display: 'flex',
          gap: '1rem',
          marginBottom: '1.5rem',
          flexWrap: 'wrap',
          justifyContent: 'center'
        }}>
          {statsItems.map((stat, i) => (
            <div key={i} style={{
              backgroundColor: '#374151',
              borderRadius: '8px',
              padding: '0.5rem 1rem',
              textAlign: 'center'
            }}>
              <div style={{ color: '#81D4FA', fontSize: '0.75rem', fontFamily: 'Poppins, sans-serif' }}>
                {stat.label}
              </div>
              <div style={{ color: '#fff', fontSize: '1.2rem', fontWeight: 600, fontFamily: 'Poppins, sans-serif' }}>
                {stat.value}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Boutons de controle */}
      <div style={{
        display: 'flex',
        gap: '1rem',
        marginBottom: '2rem',
        flexWrap: 'wrap',
        justifyContent: 'center'
      }}>
        <div style={{
          display: 'flex',
          gap: '0.75rem',
          alignItems: 'center',
          flexWrap: 'wrap',
          justifyContent: 'center',
          width: '100%',
          maxWidth: '980px'
        }}>
          {[
            { label: 'Job ID', value: jobId, setter: setJobId, placeholder: 'optionnel' },
            { label: 'Folder ID', value: folderId, setter: setFolderId, placeholder: 'requis' },
            { label: 'Slides max/jour', value: maxSlides, setter: setMaxSlides, placeholder: '60' }
          ].map((field) => (
            <label key={field.label} style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '0.3rem',
              fontFamily: 'Poppins, sans-serif',
              color: '#CBD5E1',
              fontSize: '0.75rem',
              textAlign: 'left'
            }}>
              {field.label}
              <input
                value={field.value}
                onChange={(event) => field.setter(event.target.value)}
                placeholder={field.placeholder}
                inputMode="numeric"
                style={{
                  width: '130px',
                  padding: '0.65rem 0.75rem',
                  borderRadius: '8px',
                  border: '1px solid #475569',
                  backgroundColor: '#0F172A',
                  color: '#F8FAFC',
                  fontFamily: 'Poppins, sans-serif',
                  fontSize: '0.9rem'
                }}
              />
            </label>
          ))}
          <label style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '0.3rem',
            fontFamily: 'Poppins, sans-serif',
            color: '#CBD5E1',
            fontSize: '0.75rem',
            textAlign: 'left'
          }}>
            Rythme
            <select
              value={slidePace}
              onChange={(event) => setSlidePace(event.target.value)}
              style={{
                width: '150px',
                padding: '0.65rem 0.75rem',
                borderRadius: '8px',
                border: '1px solid #475569',
                backgroundColor: '#0F172A',
                color: '#F8FAFC',
                fontFamily: 'Poppins, sans-serif',
                fontSize: '0.9rem'
              }}
            >
              <option value="dense">Soutenu</option>
              <option value="normal">Normal</option>
              <option value="synthesis">Synthèse</option>
            </select>
          </label>
        </div>

        <button
          onClick={generateSlidesFromScript}
          disabled={loading || !folderId}
          style={{
            padding: '1rem 2rem',
            backgroundColor: loading || !folderId ? '#666' : '#DC2626',
            color: 'white',
            border: 'none',
            borderRadius: '8px',
            cursor: loading || !folderId ? 'not-allowed' : 'pointer',
            fontFamily: 'Poppins, sans-serif',
            fontWeight: 600,
            fontSize: '1rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem'
          }}
        >
          {loading ? (
            <>
              <span style={{
                display: 'inline-block',
                width: '20px',
                height: '20px',
                border: '2px solid #fff',
                borderTopColor: 'transparent',
                borderRadius: '50%',
                animation: 'spin 1s linear infinite'
              }} />
              Generation en cours...
            </>
          ) : (
            'Generer depuis le texte'
          )}
        </button>

        <button
          onClick={generateSlidesFromAudio}
          disabled={loading}
          style={{
            padding: '1rem 1.5rem',
            backgroundColor: '#374151',
            color: 'white',
            border: 'none',
            borderRadius: '8px',
            cursor: loading ? 'not-allowed' : 'pointer',
            fontFamily: 'Poppins, sans-serif',
            fontWeight: 600,
            fontSize: '1rem'
          }}
        >
          Legacy audio v3
        </button>

        {timeline.length > 0 && (
          <button
            onClick={() => setShowTimeline(!showTimeline)}
            style={{
              padding: '1rem 2rem',
              backgroundColor: showTimeline ? '#4F46E5' : '#374151',
              color: 'white',
              border: 'none',
              borderRadius: '8px',
              cursor: 'pointer',
              fontFamily: 'Poppins, sans-serif',
              fontWeight: 600,
              fontSize: '1rem'
            }}
          >
            {showTimeline ? 'Masquer timeline' : 'Voir timeline'}
          </button>
        )}

        {pipelineDebug && (
          <button
            onClick={() => setShowPipeline(!showPipeline)}
            style={{
              padding: '1rem 2rem',
              backgroundColor: showPipeline ? '#059669' : '#374151',
              color: 'white',
              border: 'none',
              borderRadius: '8px',
              cursor: 'pointer',
              fontFamily: 'Poppins, sans-serif',
              fontWeight: 600,
              fontSize: '1rem'
            }}
          >
            {showPipeline ? 'Masquer pipeline' : 'Voir pipeline'}
          </button>
        )}

        {slides.length > 0 && (
          <button
            onClick={clearSlides}
            style={{
              padding: '1rem 2rem',
              backgroundColor: '#374151',
              color: 'white',
              border: 'none',
              borderRadius: '8px',
              cursor: 'pointer',
              fontFamily: 'Poppins, sans-serif',
              fontWeight: 600,
              fontSize: '1rem'
            }}
          >
            Effacer
          </button>
        )}
      </div>

      {/* Timeline */}
      {showTimeline && timeline.length > 0 && (
        <div style={{
          width: '100%',
          maxWidth: '900px',
          backgroundColor: '#2d2d44',
          borderRadius: '12px',
          padding: '1.5rem',
          marginBottom: '2rem'
        }}>
          <h3 style={{
            fontFamily: 'Poppins, sans-serif',
            color: '#fff',
            marginBottom: '1rem',
            fontSize: '1.1rem'
          }}>
            Timeline des evenements ({timeline.length})
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {timeline.map((event, i) => (
              <div key={i} style={{
                display: 'flex',
                alignItems: 'center',
                gap: '1rem',
                padding: '0.5rem',
                backgroundColor: '#1a1a2e',
                borderRadius: '6px',
                borderLeft: `4px solid ${getEventTypeColor(event.type)}`
              }}>
                <span style={{
                  fontFamily: 'monospace',
                  color: '#81D4FA',
                  fontSize: '0.85rem',
                  minWidth: isScriptMode && event.audio_filename ? '180px' : '100px'
                }}>
                  {isScriptMode && event.start_time !== null && event.start_time !== undefined
                    ? `${event.audio_filename || 'audio'} ${formatTime(event.start_time)} - ${formatTime(event.end_time)}`
                    : isScriptMode
                      ? `mots ${event.word_start ?? '--'}-${event.word_end ?? '--'}`
                      : `${formatTime(event.start_time)} - ${formatTime(event.end_time)}`}
                </span>
                <span style={{
                  backgroundColor: getEventTypeColor(event.type),
                  color: '#fff',
                  padding: '0.2rem 0.5rem',
                  borderRadius: '4px',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  minWidth: '80px',
                  textAlign: 'center',
                  fontFamily: 'Poppins, sans-serif'
                }}>
                  {event.type}
                </span>
                <span style={{
                  fontFamily: 'Poppins, sans-serif',
                  color: '#ccc',
                  fontSize: '0.85rem',
                  flex: 1
                }}>
                  {event.summary}
                </span>
                {event.fused && (
                  <span style={{
                    backgroundColor: '#F59E0B',
                    color: '#000',
                    padding: '0.1rem 0.4rem',
                    borderRadius: '4px',
                    fontSize: '0.65rem',
                    fontWeight: 700
                  }}>
                    FUSED
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Pipeline Debug - Affichage des phases */}
      {showPipeline && pipelineDebug && (
        <div style={{
          width: '100%',
          maxWidth: '1100px',
          marginBottom: '2rem'
        }}>
          {/* Phase 1: Source blocks */}
          <div style={{
            backgroundColor: '#1E3A5F',
            borderRadius: '12px',
            padding: '1.5rem',
            marginBottom: '1rem'
          }}>
            <h3 style={{
              fontFamily: 'Fredoka, sans-serif',
              color: '#10B981',
              marginBottom: '1rem',
              fontSize: '1.2rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem'
            }}>
              <span style={{
                backgroundColor: '#10B981',
                color: '#fff',
                width: '28px',
                height: '28px',
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '0.9rem',
                fontWeight: 700
              }}>1</span>
              {isScriptMode ? 'Sources contexte' : 'Event Mapping (GPT-4)'}
              <span style={{ color: '#6B7280', fontSize: '0.9rem', fontWeight: 400 }}>
                - {sourceDebugItems.length || 0} {isScriptMode ? 'fenetres' : 'evenements detectes'}
              </span>
            </h3>
            <p style={{
              fontFamily: 'Poppins, sans-serif',
              color: '#9CA3AF',
              fontSize: '0.85rem',
              marginBottom: '1rem'
            }}>
              {isScriptMode
                ? 'Fenêtres de contexte construites depuis le texte final. Le LLM sélectionne ensuite les thèmes et idées fortes.'
                : 'Analyse de la transcription pour identifier les evenements pedagogiques (story, definition, concept, example, etc.)'}
            </p>
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '0.4rem',
              maxHeight: '300px',
              overflowY: 'auto'
            }}>
              {sourceDebugItems.map((event, i) => (
                <div key={i} style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '0.75rem',
                  padding: '0.5rem',
                  backgroundColor: '#0F172A',
                  borderRadius: '6px',
                  borderLeft: `3px solid ${getEventTypeColor(isScriptMode ? 'concept' : event.type)}`
                }}>
                  <span style={{
                    fontFamily: 'monospace',
                    color: '#60A5FA',
                    fontSize: '0.75rem',
                    minWidth: isScriptMode ? '130px' : '90px'
                  }}>
                    {isScriptMode
                      ? `mots ${event.word_start}-${event.word_end}`
                      : `${formatTime(event.start_time)}-${formatTime(event.end_time)}`}
                  </span>
                  <span style={{
                    backgroundColor: getEventTypeColor(isScriptMode ? 'concept' : event.type),
                    color: '#fff',
                    padding: '0.15rem 0.4rem',
                    borderRadius: '4px',
                    fontSize: '0.7rem',
                    fontWeight: 600,
                    minWidth: '70px',
                    textAlign: 'center'
                  }}>
                    {isScriptMode ? `source ${event.source_block_id + 1}` : event.type}
                  </span>
                  <span style={{
                    fontFamily: 'Poppins, sans-serif',
                    color: '#D1D5DB',
                    fontSize: '0.8rem',
                    flex: 1
                  }}>
                    {isScriptMode ? event.excerpt : event.summary}
                  </span>
                  {event.continues_next && (
                    <span style={{
                      backgroundColor: '#F59E0B',
                      color: '#000',
                      padding: '0.1rem 0.3rem',
                      borderRadius: '3px',
                      fontSize: '0.6rem',
                      fontWeight: 700
                    }}>→ SUITE</span>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Phase 2: Slideshow Planner */}
          <div style={{
            backgroundColor: '#1E3A5F',
            borderRadius: '12px',
            padding: '1.5rem',
            marginBottom: '1rem'
          }}>
            <h3 style={{
              fontFamily: 'Fredoka, sans-serif',
              color: '#F59E0B',
              marginBottom: '1rem',
              fontSize: '1.2rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem'
            }}>
              <span style={{
                backgroundColor: '#F59E0B',
                color: '#000',
                width: '28px',
                height: '28px',
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '0.9rem',
                fontWeight: 700
              }}>2</span>
              Slideshow Planner (GPT-4)
              <span style={{ color: '#6B7280', fontSize: '0.9rem', fontWeight: 400 }}>
                - {pipelineDebug.slide_plan?.length || 0} slides planifiees
              </span>
            </h3>
            <p style={{
              fontFamily: 'Poppins, sans-serif',
              color: '#9CA3AF',
              fontSize: '0.85rem',
              marginBottom: '1rem'
            }}>
              Decision: quels evenements meritent une slide ? Quel template utiliser ?
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {pipelineDebug.slide_plan?.map((plan, i) => (
                <div key={i} style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '1rem',
                  padding: '0.6rem',
                  backgroundColor: '#0F172A',
                  borderRadius: '6px'
                }}>
                  <span style={{
                    backgroundColor: '#374151',
                    color: '#fff',
                    padding: '0.2rem 0.5rem',
                    borderRadius: '4px',
                    fontSize: '0.75rem',
                    fontWeight: 600
                  }}>
                    Slide {i + 1}
                  </span>
                  <span style={{
                    fontFamily: 'monospace',
                    color: '#60A5FA',
                    fontSize: '0.8rem'
                  }}>
                    {isScriptMode ? `source ${plan.source_block_id + 1}` : `@${formatTime(plan.trigger_time)}`}
                  </span>
                  <span style={{
                    backgroundColor: '#8B5CF6',
                    color: '#fff',
                    padding: '0.2rem 0.5rem',
                    borderRadius: '4px',
                    fontSize: '0.75rem',
                    fontWeight: 600
                  }}>
                    {plan.template}
                  </span>
                  <span style={{
                    fontFamily: 'Poppins, sans-serif',
                    color: '#10B981',
                    fontSize: '0.85rem',
                    fontWeight: 500
                  }}>
                    "{plan.title_hint}"
                  </span>
                  <span style={{
                    fontFamily: 'Poppins, sans-serif',
                    color: '#9CA3AF',
                    fontSize: '0.8rem',
                    flex: 1
                  }}>
                    {plan.content_hint}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Phase 3: Content Generation */}
          <div style={{
            backgroundColor: '#1E3A5F',
            borderRadius: '12px',
            padding: '1.5rem'
          }}>
            <h3 style={{
              fontFamily: 'Fredoka, sans-serif',
              color: '#DC2626',
              marginBottom: '1rem',
              fontSize: '1.2rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem'
            }}>
              <span style={{
                backgroundColor: '#DC2626',
                color: '#fff',
                width: '28px',
                height: '28px',
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '0.9rem',
                fontWeight: 700
              }}>3</span>
              Content Generation (GPT-4)
              <span style={{ color: '#6B7280', fontSize: '0.9rem', fontWeight: 400 }}>
                - {slides.length} slides generees
              </span>
            </h3>
            <p style={{
              fontFamily: 'Poppins, sans-serif',
              color: '#9CA3AF',
              fontSize: '0.85rem',
              marginBottom: '1rem'
            }}>
              Generation du contenu minimal pour chaque slide selon son template
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {slides.map((slide, i) => (
                <div key={i} style={{
                  padding: '0.6rem',
                  backgroundColor: '#0F172A',
                  borderRadius: '6px'
                }}>
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.75rem',
                    marginBottom: '0.5rem'
                  }}>
                    <span style={{
                      backgroundColor: '#DC2626',
                      color: '#fff',
                      padding: '0.2rem 0.5rem',
                      borderRadius: '4px',
                      fontSize: '0.75rem',
                      fontWeight: 600
                    }}>
                      Slide {i + 1}
                    </span>
                    <span style={{
                      backgroundColor: '#8B5CF6',
                      color: '#fff',
                      padding: '0.2rem 0.5rem',
                      borderRadius: '4px',
                      fontSize: '0.75rem'
                    }}>
                      {slide.template_type}
                    </span>
                    <span style={{
                      fontFamily: 'Poppins, sans-serif',
                      color: '#10B981',
                      fontSize: '0.9rem',
                      fontWeight: 600
                    }}>
                      {slide.data?.title}
                    </span>
                  </div>
                  <pre style={{
                    fontFamily: 'monospace',
                    fontSize: '0.7rem',
                    color: '#9CA3AF',
                    backgroundColor: '#1E293B',
                    padding: '0.5rem',
                    borderRadius: '4px',
                    margin: 0,
                    overflow: 'auto',
                    maxHeight: '100px'
                  }}>
                    {JSON.stringify(slide.data, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Message d'erreur */}
      {error && (
        <div style={{
          backgroundColor: '#FEE2E2',
          border: '1px solid #DC2626',
          borderRadius: '8px',
          padding: '1rem 2rem',
          marginBottom: '2rem',
          maxWidth: '600px'
        }}>
          <p style={{
            fontFamily: 'Poppins, sans-serif',
            color: '#DC2626',
            margin: 0
          }}>
            {error}
          </p>
        </div>
      )}

      {/* Etat idle */}
      {status === 'idle' && !loading && (
        <div style={{
          backgroundColor: '#1E3A5F',
          borderRadius: '12px',
          padding: '3rem',
          textAlign: 'center',
          maxWidth: '600px'
        }}>
          <p style={{
            fontFamily: 'Poppins, sans-serif',
            color: '#fff',
            fontSize: '1.2rem',
            marginBottom: '1rem'
          }}>
            Pipeline texte pret.
          </p>
          <p style={{
            fontFamily: 'Poppins, sans-serif',
            color: '#aaa',
            fontSize: '0.9rem'
          }}>
            Renseigne le folder_id de la journee generee, puis lance la generation depuis le texte final.
            <br />Le mode audio v3 reste disponible uniquement pour comparaison legacy.
          </p>
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div style={{
          backgroundColor: '#1E3A5F',
          borderRadius: '12px',
          padding: '3rem',
          textAlign: 'center',
          maxWidth: '600px'
        }}>
          <div style={{
            width: '60px',
            height: '60px',
            border: '4px solid #333',
            borderTopColor: '#DC2626',
            borderRadius: '50%',
            margin: '0 auto 1.5rem',
            animation: 'spin 1s linear infinite'
          }} />
          <p style={{
            fontFamily: 'Poppins, sans-serif',
            color: '#fff',
            fontSize: '1.1rem',
            marginBottom: '0.5rem'
          }}>
            {isScriptMode ? 'Generation depuis texte en cours...' : 'Pipeline audio v3 en cours...'}
          </p>
          <p style={{
            fontFamily: 'Poppins, sans-serif',
            color: '#aaa',
            fontSize: '0.85rem'
          }}>
            {isScriptMode ? (
              <>
                1. Lecture des segments DB
                <br />2. Préparation des fenêtres de contexte
                <br />3. Sélection des thèmes par batch
                <br />4. Rendu templates React
                <br /><br />Cela peut prendre quelques minutes selon le nombre de slides.
              </>
            ) : (
              <>
                1. Telechargement audio
                <br />2. Transcription Whisper
                <br />3. Event mapping GPT-4
                <br />4. Fusion timeline
                <br />5. Plan + generation slides
                <br /><br />Cela peut prendre 1-2 minutes.
              </>
            )}
          </p>
        </div>
      )}

      {/* Affichage des slides */}
      {slides.length > 0 && !loading && (
        <>
          {/* Info de la slide */}
          <div style={{
            backgroundColor: '#374151',
            borderRadius: '8px',
            padding: '0.75rem 1.5rem',
            marginBottom: '1rem',
            display: 'flex',
            gap: '2rem',
            alignItems: 'center',
            flexWrap: 'wrap'
          }}>
            <span style={{
              fontFamily: 'Poppins, sans-serif',
              color: '#fff',
              fontSize: '0.9rem'
            }}>
              Slide {currentSlide + 1}/{slides.length}
            </span>
            <span style={{
              fontFamily: 'Poppins, sans-serif',
              color: '#aaa',
              fontSize: '0.85rem'
            }}>
              {isScriptMode
                ? `Mots: ${slides[currentSlide].source_ref?.word_start ?? '--'}-${slides[currentSlide].source_ref?.word_end ?? '--'}`
                : `Trigger: ${formatTime(slides[currentSlide].trigger_time)}`}
            </span>
            <span style={{
              backgroundColor: getEventTypeColor(slides[currentSlide].event_type),
              color: '#fff',
              padding: '0.2rem 0.6rem',
              borderRadius: '4px',
              fontSize: '0.8rem',
              fontWeight: 600,
              fontFamily: 'Poppins, sans-serif'
            }}>
              {slides[currentSlide].event_type}
            </span>
            <span style={{
              fontFamily: 'Poppins, sans-serif',
              color: '#81D4FA',
              fontSize: '0.85rem',
              textTransform: 'capitalize'
            }}>
              Template: {slides[currentSlide].template_type}
            </span>
          </div>

          {/* La slide */}
          <div style={{ marginBottom: '1.5rem' }}>
            <div
              key={slides[currentSlide].slide_id || currentSlide}
              className={`slide-transition-preview ${slides[currentSlide].transition_effect === 'fade' ? 'slide-transition-fade' : 'slide-transition-swipe'}`}
            >
              {renderSlide(slides[currentSlide])}
            </div>
          </div>

          {/* Navigation */}
          <div style={{
            display: 'flex',
            gap: '1rem',
            alignItems: 'center'
          }}>
            <button
              onClick={() => setCurrentSlide(Math.max(0, currentSlide - 1))}
              disabled={currentSlide === 0}
              style={{
                padding: '0.75rem 1.5rem',
                backgroundColor: currentSlide === 0 ? '#555' : '#DC2626',
                color: 'white',
                border: 'none',
                borderRadius: '8px',
                cursor: currentSlide === 0 ? 'not-allowed' : 'pointer',
                fontFamily: 'Poppins, sans-serif',
                fontWeight: 600
              }}
            >
              Precedent
            </button>

            <span style={{
              fontFamily: 'Poppins, sans-serif',
              fontSize: '1rem',
              color: '#fff',
              minWidth: '100px',
              textAlign: 'center'
            }}>
              {currentSlide + 1} / {slides.length}
            </span>

            <button
              onClick={() => setCurrentSlide(Math.min(slides.length - 1, currentSlide + 1))}
              disabled={currentSlide === slides.length - 1}
              style={{
                padding: '0.75rem 1.5rem',
                backgroundColor: currentSlide === slides.length - 1 ? '#555' : '#DC2626',
                color: 'white',
                border: 'none',
                borderRadius: '8px',
                cursor: currentSlide === slides.length - 1 ? 'not-allowed' : 'pointer',
                fontFamily: 'Poppins, sans-serif',
                fontWeight: 600
              }}
            >
              Suivant
            </button>
          </div>

          {/* Apercu du texte source */}
          <details style={{
            marginTop: '2rem',
            maxWidth: '800px',
            width: '100%'
          }}>
            <summary style={{
              fontFamily: 'Poppins, sans-serif',
              color: '#aaa',
              cursor: 'pointer',
              padding: '0.5rem'
            }}>
              {isScriptMode ? 'Voir le cours source' : "Voir le texte source (transcription de l'evenement)"}
            </summary>
            <div style={{
              backgroundColor: '#2d2d44',
              borderRadius: '8px',
              padding: '1rem',
              marginTop: '0.5rem'
            }}>
              <p style={{
                fontFamily: 'Poppins, sans-serif',
                color: '#81D4FA',
                fontSize: '0.85rem',
                marginBottom: '0.5rem'
              }}>
                {slides[currentSlide].event_summary}
              </p>
              {isScriptMode && (
                <div style={{
                  display: 'flex',
                  justifyContent: 'flex-end',
                  marginBottom: '0.75rem'
                }}>
                  <button
                    onClick={() => setSourceView(sourceView === 'course' ? 'slide' : 'course')}
                    style={{
                      border: '1px solid rgba(129,212,250,0.35)',
                      backgroundColor: sourceView === 'course' ? 'rgba(129,212,250,0.16)' : 'transparent',
                      color: '#81D4FA',
                      borderRadius: '6px',
                      padding: '0.35rem 0.65rem',
                      cursor: 'pointer',
                      fontFamily: 'Poppins, sans-serif',
                      fontSize: '0.78rem',
                      fontWeight: 700
                    }}
                  >
                    {sourceView === 'course' ? 'Voir seulement la slide' : 'Voir tout le cours'}
                  </button>
                </div>
              )}
              <p style={{
                fontFamily: 'Poppins, sans-serif',
                color: '#ccc',
                fontSize: '0.85rem',
                lineHeight: 1.6,
                margin: 0
              }}>
                {isScriptMode && sourceView === 'slide'
                  ? getSlideSourceExcerpt(slides[currentSlide], currentSlide, slides) || 'Texte source non disponible'
                  : isScriptMode
                    ? renderHighlightedCourseSource(slides[currentSlide], currentSlide, slides)
                    : slides[currentSlide].source_text || 'Texte source non disponible'}
              </p>
            </div>
          </details>
        </>
      )}

      {/* CSS pour l'animation de spin */}
      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
        @keyframes slideSwipeIn {
          from { opacity: 0; transform: translateX(-42px); }
          to { opacity: 1; transform: translateX(0); }
        }
        @keyframes slideFadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        .slide-transition-preview {
          will-change: opacity, transform;
        }
        mark {
          background: rgba(250, 204, 21, 0.22);
          color: #fef3c7;
          border-radius: 3px;
          padding: 0 2px;
        }
        .slide-transition-swipe {
          animation: slideSwipeIn 420ms cubic-bezier(0.2, 0.8, 0.2, 1);
        }
        .slide-transition-fade {
          animation: slideFadeIn 360ms ease-out;
        }
      `}</style>
    </div>
  );
}
