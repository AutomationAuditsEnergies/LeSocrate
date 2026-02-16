import React, { useState, useEffect } from 'react';
import { apiUrl } from '../api';
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

export default function GeneratedSlides() {
  const [slides, setSlides] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [stats, setStats] = useState(null);
  const [transcription, setTranscription] = useState('');
  const [currentSlide, setCurrentSlide] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState('idle');
  const [showTimeline, setShowTimeline] = useState(false);
  const [pipelineDebug, setPipelineDebug] = useState(null);
  const [showPipeline, setShowPipeline] = useState(false);

  useEffect(() => {
    fetchExistingSlides();
  }, []);

  const fetchExistingSlides = async () => {
    try {
      const response = await fetch(apiUrl('/api/slides/data'), {
        credentials: 'include'
      });
      const data = await response.json();

      if (data.status === 'success' && data.slides) {
        setSlides(data.slides);
        setStats(data.stats || null);
        setTimeline(data.timeline || []);
        setTranscription(data.transcription || '');
        setPipelineDebug(data.pipeline_debug || null);
        setStatus('success');
      }
    } catch (err) {
      console.log('Pas de slides existantes');
    }
  };

  const generateSlides = async () => {
    setLoading(true);
    setError(null);
    setStatus('generating');

    try {
      // Utilise le nouveau endpoint v3
      const response = await fetch(apiUrl('/api/slides/generate-v3'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        credentials: 'include',
        body: JSON.stringify({
          audio_id: 1,
          max_duration: 300  // 5 minutes pour le test
        })
      });

      const data = await response.json();

      if (data.status === 'success') {
        setSlides(data.slides);
        setStats(data.stats || null);
        setTimeline(data.timeline || []);
        setPipelineDebug(data.pipeline_debug || null);
        setCurrentSlide(0);
        setStatus('success');
      } else {
        setError(data.message || 'Erreur lors de la generation');
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
      await fetch(apiUrl('/api/slides/clear'), {
        method: 'POST',
        credentials: 'include'
      });
      setSlides([]);
      setTimeline([]);
      setStats(null);
      setTranscription('');
      setPipelineDebug(null);
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

    switch (slide.template_type) {
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
          Slides Auto-Generees v3
        </h1>
        <p style={{
          fontFamily: 'Poppins, sans-serif',
          color: '#aaa',
          fontSize: '1rem'
        }}>
          Architecture hierarchique multi-pass avec event mapping et fusion
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
          {[
            { label: 'Duree audio', value: formatTime(stats.audio_duration) },
            { label: 'Chunks', value: stats.chunks_processed },
            { label: 'Evenements', value: stats.events_detected },
            { label: 'Apres fusion', value: stats.events_after_fusion },
            { label: 'Slides', value: stats.slides_generated }
          ].map((stat, i) => (
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
        <button
          onClick={generateSlides}
          disabled={loading}
          style={{
            padding: '1rem 2rem',
            backgroundColor: loading ? '#666' : '#DC2626',
            color: 'white',
            border: 'none',
            borderRadius: '8px',
            cursor: loading ? 'not-allowed' : 'pointer',
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
              Generation v3 en cours...
            </>
          ) : (
            'Generer les slides (v3)'
          )}
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
                  minWidth: '100px'
                }}>
                  {formatTime(event.start_time)} - {formatTime(event.end_time)}
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
          {/* Phase 1: Event Mapping */}
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
              Event Mapping (GPT-4)
              <span style={{ color: '#6B7280', fontSize: '0.9rem', fontWeight: 400 }}>
                - {pipelineDebug.raw_events?.length || 0} evenements detectes
              </span>
            </h3>
            <p style={{
              fontFamily: 'Poppins, sans-serif',
              color: '#9CA3AF',
              fontSize: '0.85rem',
              marginBottom: '1rem'
            }}>
              Analyse de la transcription pour identifier les evenements pedagogiques (story, definition, concept, example, etc.)
            </p>
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '0.4rem',
              maxHeight: '300px',
              overflowY: 'auto'
            }}>
              {pipelineDebug.raw_events?.map((event, i) => (
                <div key={i} style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '0.75rem',
                  padding: '0.5rem',
                  backgroundColor: '#0F172A',
                  borderRadius: '6px',
                  borderLeft: `3px solid ${getEventTypeColor(event.type)}`
                }}>
                  <span style={{
                    fontFamily: 'monospace',
                    color: '#60A5FA',
                    fontSize: '0.75rem',
                    minWidth: '90px'
                  }}>
                    {formatTime(event.start_time)}-{formatTime(event.end_time)}
                  </span>
                  <span style={{
                    backgroundColor: getEventTypeColor(event.type),
                    color: '#fff',
                    padding: '0.15rem 0.4rem',
                    borderRadius: '4px',
                    fontSize: '0.7rem',
                    fontWeight: 600,
                    minWidth: '70px',
                    textAlign: 'center'
                  }}>
                    {event.type}
                  </span>
                  <span style={{
                    fontFamily: 'Poppins, sans-serif',
                    color: '#D1D5DB',
                    fontSize: '0.8rem',
                    flex: 1
                  }}>
                    {event.summary}
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
                    @{formatTime(plan.trigger_time)}
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
            Pipeline v3 pret !
          </p>
          <p style={{
            fontFamily: 'Poppins, sans-serif',
            color: '#aaa',
            fontSize: '0.9rem'
          }}>
            Architecture hierarchique multi-pass:
            <br />1. Transcription par chunks
            <br />2. Event mapping local
            <br />3. Fusion inter-blocs
            <br />4. Construction du plan
            <br />5. Generation minimale
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
            Pipeline v3 en cours...
          </p>
          <p style={{
            fontFamily: 'Poppins, sans-serif',
            color: '#aaa',
            fontSize: '0.85rem'
          }}>
            1. Telechargement audio
            <br />2. Transcription Whisper
            <br />3. Event mapping GPT-4
            <br />4. Fusion timeline
            <br />5. Plan + generation slides
            <br /><br />Cela peut prendre 1-2 minutes.
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
              Trigger: {formatTime(slides[currentSlide].trigger_time)}
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
            {renderSlide(slides[currentSlide])}
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
              Voir le texte source (transcription de l'evenement)
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
              <p style={{
                fontFamily: 'Poppins, sans-serif',
                color: '#ccc',
                fontSize: '0.85rem',
                lineHeight: 1.6,
                margin: 0
              }}>
                {slides[currentSlide].source_text || 'Texte source non disponible'}
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
      `}</style>
    </div>
  );
}
