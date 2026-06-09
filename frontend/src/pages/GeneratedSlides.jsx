import React, { useState, useEffect } from 'react';
import { Info } from 'lucide-react';
import { apiFetch } from '../api';
import { renderSlideTemplate } from '../components/slides/slideTemplateRegistry';

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

function getPlanDebugForSlide(pipelineDebug = {}, slide = {}, index = 0) {
  const slidePlan = Array.isArray(pipelineDebug?.slide_plan) ? pipelineDebug.slide_plan : [];
  const anchorId = slide.slide_anchor_id || '';
  const sourceBlockId = slide.source_ref?.source_block_id;

  if (anchorId) {
    const byAnchor = slidePlan.find(item => item?.slide_anchor_id === anchorId);
    if (byAnchor) return byAnchor;
  }

  if (sourceBlockId !== undefined && sourceBlockId !== null) {
    const bySource = slidePlan.find(item => item?.source_block_id === sourceBlockId && item?.template === slide.template_type);
    if (bySource) return bySource;
  }

  return slidePlan[index] || {};
}

function getAnchorDebugForSlide(slide = {}) {
  const anchors = slide.source_ref?.slide_anchors;
  if (!Array.isArray(anchors) || !anchors.length) return {};
  const anchorId = slide.slide_anchor_id || '';
  if (anchorId) {
    return anchors.find(anchor => anchor?.anchor_id === anchorId) || {};
  }
  return anchors.length === 1 ? anchors[0] : {};
}

function normalizeRejectedTemplates(value) {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (!item) return null;
      if (typeof item === 'string') return { template: item, why: '' };
      return {
        template: item.template || item.template_type || item.name || '',
        why: item.why || item.reason || item.rationale || ''
      };
    })
    .filter(item => item?.template);
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
  const [currentSlide, setCurrentSlide] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState('idle');
  const [generationMode, setGenerationMode] = useState('script');
  const [folderId, setFolderId] = useState(initialParams.get('folder_id') || '');
  const [jobId, setJobId] = useState(initialParams.get('job_id') || '');
  const [platformId] = useState(initialParams.get('platform_id') || '');
  const [maxSlides, setMaxSlides] = useState(initialParams.get('max_slides') || '60');
  const [slidePace, setSlidePace] = useState(initialParams.get('pace') || 'normal');
  const [showTimeline, setShowTimeline] = useState(false);
  const [pipelineDebug, setPipelineDebug] = useState(null);
  const [showPipeline, setShowPipeline] = useState(false);
  const [showSlideDecision, setShowSlideDecision] = useState(false);
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
        setPipelineDebug(data.pipeline_debug || null);
        setGenerationMode(data.generation_mode || data.stats?.generation_mode || 'script');
        setStatus('success');
      }
    } catch (err) {
      console.log('Pas de slides existantes', err);
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
          platform_id: platformId ? Number(platformId) : null,
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
      setPipelineDebug(null);
      setGenerationMode('script');
      setCurrentSlide(0);
      setStatus('idle');
      setError(null);
    } catch (err) {
      console.error('Erreur lors du clear:', err);
    }
  };

  const renderSlide = (slide) => renderSlideTemplate(slide);

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
  const templateBacklog = Array.isArray(pipelineDebug?.template_backlog)
    ? pipelineDebug.template_backlog
    : [];
  const currentTemplateGap = slides[currentSlide]?.ideal_template_gap || null;
  const statsItems = stats
    ? (isScriptMode
      ? [
          { label: 'Source', value: 'Texte DB' },
          { label: 'Mots', value: stats.source_words || 0 },
          { label: 'Sources', value: stats.source_blocks || 0 },
          { label: 'Rythme', value: stats.pace || slidePace },
          ...(stats.slide_anchors_found ? [{ label: 'Anchors', value: stats.slide_anchors_found }] : []),
          ...(stats.template_backlog_count ? [{ label: 'Templates à créer', value: stats.template_backlog_count }] : []),
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
  const currentSlideData = slides[currentSlide] || {};
  const currentPlanDebug = getPlanDebugForSlide(pipelineDebug, currentSlideData, currentSlide);
  const currentAnchorDebug = getAnchorDebugForSlide(currentSlideData);
  const currentRejectedTemplates = normalizeRejectedTemplates(
    currentSlideData.rejected_templates || currentPlanDebug.rejected_templates
  );
  const currentSourceQuote = normalizeSourceText(
    currentSlideData.source_ref?.source_quote ||
    currentSlideData.source_quote ||
    getSlideSourceExcerpt(currentSlideData, currentSlide, slides)
  );
  const currentDecisionDebug = {
    template: currentSlideData.template_type || currentPlanDebug.template || '',
    eventType: currentSlideData.event_type || currentPlanDebug.event_type || '',
    pedagogicalShape: currentSlideData.pedagogical_shape || currentPlanDebug.pedagogical_shape || '',
    plannedTemplate: currentAnchorDebug.template_type || '',
    plannedShape: currentAnchorDebug.pedagogical_shape || '',
    shapeEvidence: currentSlideData.shape_evidence || currentPlanDebug.shape_evidence || '',
    reason: currentSlideData.template_decision_reason || currentPlanDebug.template_decision_reason || '',
    curationReason: currentSlideData.curation_reason || currentPlanDebug.curation_reason || '',
    sourceQuote: currentSourceQuote,
    rejectedTemplates: currentRejectedTemplates
  };

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
                ? 'Fenêtres construites depuis le texte final. Les anchors du plan restent visibles comme intentions, mais ne forcent pas la slide.'
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

          {/* Phase 2: Curation */}
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
              {isScriptMode ? 'Curation IA texte + anchors' : 'Slideshow Planner (GPT-4)'}
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
              {isScriptMode
                ? 'Décision: quels passages du texte final méritent un visuel, quel template existant utiliser, et quel template manque éventuellement.'
                : 'Decision: quels evenements meritent une slide ? Quel template utiliser ?'}
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
                    {plan.curation_reason || plan.content_hint}
                  </span>
                  {plan.ideal_template_gap?.needed && (
                    <span style={{
                      border: '1px solid rgba(245,158,11,0.45)',
                      color: '#FBBF24',
                      padding: '0.2rem 0.5rem',
                      borderRadius: '4px',
                      fontSize: '0.72rem',
                      fontWeight: 700,
                      whiteSpace: 'nowrap'
                    }}>
                      template idéal
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>

          {templateBacklog.length > 0 && (
            <div style={{
              backgroundColor: '#1E3A5F',
              borderRadius: '12px',
              padding: '1.5rem',
              marginBottom: '1rem'
            }}>
              <h3 style={{
                fontFamily: 'Fredoka, sans-serif',
                color: '#FBBF24',
                marginBottom: '1rem',
                fontSize: '1.2rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem'
              }}>
                <span style={{
                  backgroundColor: '#FBBF24',
                  color: '#111827',
                  width: '28px',
                  height: '28px',
                  borderRadius: '50%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '0.9rem',
                  fontWeight: 700
                }}>+</span>
                Backlog templates
                <span style={{ color: '#9CA3AF', fontSize: '0.9rem', fontWeight: 400 }}>
                  - {templateBacklog.length} recommandations
                </span>
              </h3>
              <p style={{
                fontFamily: 'Poppins, sans-serif',
                color: '#CBD5E1',
                fontSize: '0.85rem',
                marginBottom: '1rem'
              }}>
                Ces templates ne sont pas utilisés pendant la génération. La pipeline choisit un template existant, puis garde ici les manques à créer plus tard.
              </p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                {templateBacklog.map((item, i) => (
                  <div key={`${item.suggested_template_name}-${i}`} style={{
                    backgroundColor: '#0F172A',
                    border: '1px solid rgba(251,191,36,0.24)',
                    borderRadius: '8px',
                    padding: '0.85rem'
                  }}>
                    <div style={{
                      display: 'flex',
                      gap: '0.75rem',
                      alignItems: 'center',
                      flexWrap: 'wrap',
                      marginBottom: '0.45rem'
                    }}>
                      <span style={{
                        fontFamily: 'Poppins, sans-serif',
                        color: '#F8FAFC',
                        fontWeight: 700,
                        fontSize: '0.95rem'
                      }}>
                        {item.suggested_template_name}
                      </span>
                      <span style={{
                        backgroundColor: '#374151',
                        color: '#CBD5E1',
                        padding: '0.18rem 0.45rem',
                        borderRadius: '4px',
                        fontSize: '0.72rem',
                        fontWeight: 700
                      }}>
                        utilisé: {item.best_current_template}
                      </span>
                    </div>
                    <p style={{
                      fontFamily: 'Poppins, sans-serif',
                      color: '#CBD5E1',
                      fontSize: '0.82rem',
                      lineHeight: 1.55,
                      margin: '0 0 0.55rem'
                    }}>
                      {item.reason}
                    </p>
                    {item.design_prompt && (
                      <pre style={{
                        fontFamily: 'monospace',
                        fontSize: '0.72rem',
                        color: '#FDE68A',
                        backgroundColor: '#111827',
                        padding: '0.6rem',
                        borderRadius: '6px',
                        whiteSpace: 'pre-wrap',
                        margin: 0
                      }}>
                        {item.design_prompt}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

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
                <br />3. Curation IA texte + anchors
                <br />4. Rendu avec templates existants
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
            {currentTemplateGap?.needed && (
              <span style={{
                fontFamily: 'Poppins, sans-serif',
                color: '#FBBF24',
                fontSize: '0.82rem',
                border: '1px solid rgba(251,191,36,0.35)',
                borderRadius: '4px',
                padding: '0.2rem 0.5rem'
              }}>
                Idéal: {currentTemplateGap.suggested_template_name}
              </span>
            )}
            <button
              type="button"
              onClick={() => setShowSlideDecision(!showSlideDecision)}
              aria-expanded={showSlideDecision}
              aria-label={showSlideDecision ? 'Masquer le debug template' : 'Afficher le debug template'}
              title={showSlideDecision ? 'Masquer le debug template' : 'Afficher le debug template'}
              style={{
                marginLeft: 'auto',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.4rem',
                border: `1px solid ${showSlideDecision ? 'rgba(129,212,250,0.55)' : 'rgba(148,163,184,0.35)'}`,
                backgroundColor: showSlideDecision ? 'rgba(129,212,250,0.14)' : 'rgba(15,23,42,0.42)',
                color: showSlideDecision ? '#BAE6FD' : '#CBD5E1',
                borderRadius: '8px',
                padding: '0.38rem 0.65rem',
                cursor: 'pointer',
                fontFamily: 'Poppins, sans-serif',
                fontSize: '0.78rem',
                fontWeight: 700
              }}
            >
              <Info size={15} strokeWidth={2.2} />
              Debug template
            </button>
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

          {showSlideDecision && (
            <div style={{
              width: '100%',
              maxWidth: '920px',
              backgroundColor: '#0F172A',
              border: '1px solid rgba(148,163,184,0.24)',
              borderRadius: '12px',
              padding: '1rem',
              margin: '0 0 1.5rem',
              fontFamily: 'Poppins, sans-serif'
            }}>
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                gap: '1rem',
                flexWrap: 'wrap',
                alignItems: 'flex-start',
                marginBottom: '0.85rem'
              }}>
                <div>
                  <div style={{
                    color: '#E2E8F0',
                    fontSize: '0.95rem',
                    fontWeight: 700,
                    marginBottom: '0.25rem'
                  }}>
                    Décision template
                  </div>
                  <div style={{
                    color: '#94A3B8',
                    fontSize: '0.78rem',
                    lineHeight: 1.45
                  }}>
                    Lecture interne de la slide courante. Invisible côté apprenant.
                  </div>
                </div>
                <div style={{
                  display: 'flex',
                  gap: '0.45rem',
                  flexWrap: 'wrap',
                  justifyContent: 'flex-end'
                }}>
                  <span style={{
                    backgroundColor: '#8B5CF6',
                    color: '#fff',
                    borderRadius: '6px',
                    padding: '0.24rem 0.5rem',
                    fontSize: '0.74rem',
                    fontWeight: 700
                  }}>
                    {currentDecisionDebug.template || 'template inconnu'}
                  </span>
                  {currentDecisionDebug.pedagogicalShape && (
                    <span style={{
                      backgroundColor: 'rgba(129,212,250,0.12)',
                      color: '#BAE6FD',
                      border: '1px solid rgba(129,212,250,0.28)',
                      borderRadius: '6px',
                      padding: '0.24rem 0.5rem',
                      fontSize: '0.74rem',
                      fontWeight: 700
                    }}>
                      {currentDecisionDebug.pedagogicalShape}
                    </span>
                  )}
                  {currentDecisionDebug.eventType && (
                    <span style={{
                      backgroundColor: 'rgba(148,163,184,0.12)',
                      color: '#CBD5E1',
                      borderRadius: '6px',
                      padding: '0.24rem 0.5rem',
                      fontSize: '0.74rem',
                      fontWeight: 700
                    }}>
                      {currentDecisionDebug.eventType}
                    </span>
                  )}
                </div>
              </div>

              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
                gap: '0.75rem',
                marginBottom: '0.85rem'
              }}>
                <div style={{
                  backgroundColor: '#111827',
                  borderRadius: '8px',
                  padding: '0.75rem',
                  border: '1px solid rgba(148,163,184,0.16)'
                }}>
                  <div style={{ color: '#94A3B8', fontSize: '0.72rem', marginBottom: '0.3rem', fontWeight: 700 }}>
                    Forme prévue
                  </div>
                  <div style={{ color: '#E5E7EB', fontSize: '0.82rem', lineHeight: 1.45 }}>
                    {currentDecisionDebug.plannedShape || 'Non renseignée'}
                    {currentDecisionDebug.plannedTemplate ? ` · ${currentDecisionDebug.plannedTemplate}` : ''}
                  </div>
                </div>
                <div style={{
                  backgroundColor: '#111827',
                  borderRadius: '8px',
                  padding: '0.75rem',
                  border: '1px solid rgba(148,163,184,0.16)'
                }}>
                  <div style={{ color: '#94A3B8', fontSize: '0.72rem', marginBottom: '0.3rem', fontWeight: 700 }}>
                    Preuve de forme
                  </div>
                  <div style={{ color: '#E5E7EB', fontSize: '0.82rem', lineHeight: 1.45 }}>
                    {currentDecisionDebug.shapeEvidence || 'Non renseignée'}
                  </div>
                </div>
              </div>

              {(currentDecisionDebug.reason || currentDecisionDebug.curationReason) && (
                <div style={{
                  backgroundColor: 'rgba(15,23,42,0.68)',
                  borderRadius: '8px',
                  padding: '0.75rem',
                  border: '1px solid rgba(139,92,246,0.22)',
                  marginBottom: '0.85rem'
                }}>
                  <div style={{ color: '#C4B5FD', fontSize: '0.72rem', marginBottom: '0.35rem', fontWeight: 700 }}>
                    Raison du choix
                  </div>
                  <div style={{ color: '#E5E7EB', fontSize: '0.84rem', lineHeight: 1.55 }}>
                    {currentDecisionDebug.reason || currentDecisionDebug.curationReason}
                  </div>
                </div>
              )}

              {currentDecisionDebug.rejectedTemplates.length > 0 && (
                <div style={{ marginBottom: '0.85rem' }}>
                  <div style={{ color: '#94A3B8', fontSize: '0.72rem', marginBottom: '0.45rem', fontWeight: 700 }}>
                    Templates écartés
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
                    {currentDecisionDebug.rejectedTemplates.map((item, index) => (
                      <div key={`${item.template}-${index}`} style={{
                        display: 'flex',
                        gap: '0.6rem',
                        alignItems: 'flex-start',
                        backgroundColor: '#111827',
                        border: '1px solid rgba(148,163,184,0.16)',
                        borderRadius: '8px',
                        padding: '0.55rem 0.65rem'
                      }}>
                        <span style={{
                          color: '#FCA5A5',
                          backgroundColor: 'rgba(220,38,38,0.12)',
                          borderRadius: '6px',
                          padding: '0.16rem 0.42rem',
                          fontSize: '0.72rem',
                          fontWeight: 700,
                          whiteSpace: 'nowrap'
                        }}>
                          {item.template}
                        </span>
                        <span style={{
                          color: '#CBD5E1',
                          fontSize: '0.8rem',
                          lineHeight: 1.45
                        }}>
                          {item.why || 'Raison non renseignée'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div style={{
                backgroundColor: '#111827',
                borderRadius: '8px',
                padding: '0.75rem',
                border: '1px solid rgba(148,163,184,0.16)'
              }}>
                <div style={{ color: '#94A3B8', fontSize: '0.72rem', marginBottom: '0.35rem', fontWeight: 700 }}>
                  Citation source
                </div>
                <div style={{
                  color: '#CBD5E1',
                  fontSize: '0.82rem',
                  lineHeight: 1.55,
                  maxHeight: '7.5rem',
                  overflow: 'auto'
                }}>
                  {currentDecisionDebug.sourceQuote || 'Citation source non disponible'}
                </div>
              </div>
            </div>
          )}

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
              {slides[currentSlide].curation_reason && (
                <p style={{
                  fontFamily: 'Poppins, sans-serif',
                  color: '#FBBF24',
                  fontSize: '0.8rem',
                  lineHeight: 1.5,
                  margin: '0 0 0.75rem'
                }}>
                  {slides[currentSlide].curation_reason}
                </p>
              )}
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
