import { useEffect, useRef, useState } from 'react'

import ReflectionTemplate from './templates/ReflectionTemplate'
import CaseStudyTemplate from './templates/CaseStudyTemplate'
import FacilitatorTemplate from './templates/FacilitatorTemplate'
import ChartTemplate from './templates/ChartTemplate'
import StatsTemplate from './templates/StatsTemplate'
import StoryTemplate from './templates/StoryTemplate'
import RecapTemplate from './templates/RecapTemplate'
import AnalogyTemplate from './templates/AnalogyTemplate'
import WarningTemplate from './templates/WarningTemplate'
import TipTemplate from './templates/TipTemplate'
import OpinionTemplate from './templates/OpinionTemplate'
import TransitionTemplate from './templates/TransitionTemplate'
import PlayfulTemplate from './templates/PlayfulTemplate'
import DefinitionTemplate from './templates/DefinitionTemplate'
import ComparisonTemplate from './templates/ComparisonTemplate'
import StepsTemplate from './templates/StepsTemplate'
import ChecklistTemplate from './templates/ChecklistTemplate'
import QuotableTemplate from './templates/QuotableTemplate'
import PracticeExerciseTemplate from './templates/PracticeExerciseTemplate'
import BeforeAfterTemplate from './templates/BeforeAfterTemplate'
import FrameworkTemplate from './templates/FrameworkTemplate'
import ProfilesTemplate from './templates/ProfilesTemplate'
import ScriptTemplate from './templates/ScriptTemplate'
import MatrixTemplate from './templates/MatrixTemplate'
import GradientTemplate from './templates/GradientTemplate'
import SignalsTemplate from './templates/SignalsTemplate'
import TimelineTemplate from './templates/TimelineTemplate'
import ChannelAdaptationTemplate from './templates/ChannelAdaptationTemplate'
import EscalationLadderTemplate from './templates/EscalationLadderTemplate'
import ToolkitTemplate from './templates/ToolkitTemplate'
import DecisionTreeTemplate from './templates/DecisionTreeTemplate'
import TemperatureScaleTemplate from './templates/TemperatureScaleTemplate'
import KPIExplainerTemplate from './templates/KPIExplainerTemplate'
import SelfDiagTemplate from './templates/SelfDiagTemplate'
import ParadoxTemplate from './templates/ParadoxTemplate'
import LearningPathTemplate from './templates/LearningPathTemplate'
import SelfManagementTemplate from './templates/SelfManagementTemplate'
import SignalRadarTemplate from './templates/SignalRadarTemplate'
import {
  DeckChapterOpener,
  DeckDayProgram7Steps,
  DeckPause,
  DeckProgramYear,
  DeckQA,
  DeckWelcome,
} from './templates/DeckTemplates'

const COMMON_PROPS = {
  badge: 'TP-CRCD',
  brandName: 'SALES HACKING',
}

export function SlidePreviewFrame({
  slide,
  maxWidth = 720,
  padding = 14,
  className = '',
  style = {},
}) {
  const frameRef = useRef(null)
  const [frameWidth, setFrameWidth] = useState(maxWidth)
  const stageWidth = 1200
  const stageHeight = 675
  const scale = Math.min(1, frameWidth / stageWidth)

  useEffect(() => {
    if (!frameRef.current) return undefined
    const updateWidth = () => {
      const width = frameRef.current?.clientWidth || maxWidth
      setFrameWidth(width)
    }
    updateWidth()
    const observer = new ResizeObserver(updateWidth)
    observer.observe(frameRef.current)
    return () => observer.disconnect()
  }, [maxWidth])

  return (
    <div
      className={className}
      style={{
        padding,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden',
        ...style,
      }}
    >
      <div
        ref={frameRef}
        style={{
          width: '100%',
          maxWidth,
          aspectRatio: '16 / 9',
          flex: `0 1 ${maxWidth}px`,
          borderRadius: '6px',
          overflow: 'hidden',
          position: 'relative',
          background: '#020617',
        }}
        className="pipeline-slide-preview-scope"
      >
        <div
          className="pipeline-slide-preview-stage"
          style={{
            width: `${stageWidth}px`,
            height: `${stageHeight}px`,
            transform: `scale(${scale})`,
            transformOrigin: 'top left',
            position: 'absolute',
            top: 0,
            left: 0,
          }}
        >
          {renderPipelineSlidePreview(slide)}
        </div>
      </div>
    </div>
  )
}

function renderPipelineSlidePreview(slide = {}) {
  const templateType = slide.template_type || slide.type || ''
  const props = { ...(slide.data || {}), ...COMMON_PROPS }
  const isSevenStepDayProgram = Array.isArray(slide.data?.items) && slide.data.items.length === 7

  switch (templateType) {
    case 'welcome':
      return <DeckWelcome {...props} />
    case 'program_year':
    case 'day_year':
      return <DeckProgramYear {...props} />
    case 'day_program':
      return isSevenStepDayProgram ? <DeckDayProgram7Steps {...props} /> : <DeckProgramYear {...props} />
    case 'day_program_7_steps':
      return <DeckDayProgram7Steps {...props} />
    case 'chapter_opener':
    case 'chapter_intro':
      return <DeckChapterOpener {...props} />
    case 'pause':
      return <DeckPause {...props} />
    case 'qa':
      return <DeckQA {...props} />
    case 'context':
      return <ContextSlidePreview {...props} />
    case 'definition':
      return <DefinitionTemplate {...props} />
    case 'comparison':
    case 'comparison-ternary':
      return <ComparisonTemplate {...props} />
    case 'beforeafter':
      return <BeforeAfterTemplate {...props} />
    case 'steps':
    case 'steps-mini':
      return <StepsTemplate {...props} />
    case 'checklist':
      return <ChecklistTemplate {...props} />
    case 'quotable':
    case 'quotable-2':
      return <QuotableTemplate {...props} />
    case 'exercise':
      return <PracticeExerciseTemplate {...props} />
    case 'reflection':
      return <ReflectionTemplate {...props} />
    case 'casestudy':
      return <CaseStudyTemplate {...props} />
    case 'facilitator':
      return <FacilitatorTemplate {...props} />
    case 'chart':
      return <ChartTemplate {...props} />
    case 'stats':
      return <StatsTemplate {...props} />
    case 'story':
      return <StoryTemplate {...props} />
    case 'recap':
      return <RecapTemplate {...props} />
    case 'analogy':
      return <AnalogyTemplate {...props} />
    case 'warning':
      return <WarningTemplate {...props} />
    case 'tip':
      return <TipTemplate {...props} />
    case 'opinion':
      return <OpinionTemplate {...props} />
    case 'transition':
      return <TransitionTemplate {...props} />
    case 'playful':
      return <PlayfulTemplate {...props} />
    case 'framework':
      return <FrameworkTemplate {...props} />
    case 'profiles':
      return <ProfilesTemplate {...props} />
    case 'script':
      return <ScriptTemplate {...props} />
    case 'matrix':
      return <MatrixTemplate {...props} />
    case 'gradient':
      return <GradientTemplate {...props} />
    case 'signals':
      return <SignalsTemplate {...props} />
    case 'timeline':
      return <TimelineTemplate {...props} />
    case 'channel':
      return <ChannelAdaptationTemplate {...props} />
    case 'escalation':
      return <EscalationLadderTemplate {...props} />
    case 'toolkit':
      return <ToolkitTemplate {...props} />
    case 'decisiontree':
      return <DecisionTreeTemplate {...props} />
    case 'temperature':
      return <TemperatureScaleTemplate {...props} />
    case 'kpi':
      return <KPIExplainerTemplate {...props} />
    case 'selfdiag':
      return <SelfDiagTemplate {...props} />
    case 'paradox':
      return <ParadoxTemplate {...props} />
    case 'learningpath':
      return <LearningPathTemplate {...props} />
    case 'selfmanagement':
      return <SelfManagementTemplate {...props} />
    case 'signalradar':
      return <SignalRadarTemplate {...props} />
    default:
      return (
        <div style={{ width: '100%', height: '100%', background: '#f8fafc', color: '#0f172a', padding: '48px', fontFamily: 'Inter, system-ui, sans-serif' }}>
          <div style={{ fontSize: '42px', fontWeight: 800, marginBottom: '18px' }}>
            Template non reconnu
          </div>
          <div style={{ fontSize: '24px' }}>{templateType || 'inconnu'}</div>
        </div>
      )
  }
}

function ContextSlidePreview({
  formation_name,
  chapter,
  label,
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) {
  return (
    <div style={{
      width: '100%',
      height: '100%',
      background: '#f8fafc',
      color: '#0f172a',
      fontFamily: 'Inter, system-ui, sans-serif',
      display: 'flex',
      flexDirection: 'column',
      padding: '36px 44px',
      boxSizing: 'border-box',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: '#64748b', fontSize: '16px', fontWeight: 800 }}>
        <span>{badge}</span>
        <span>{brandName}</span>
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
        <div style={{ color: '#dc2626', fontSize: '18px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '18px' }}>
          {label || 'Séquence en cours'}
        </div>
        <div style={{ fontSize: '42px', lineHeight: 1.08, fontWeight: 900, maxWidth: '820px' }}>
          {formation_name || 'Formation'}
        </div>
        <div style={{ marginTop: '24px', height: '3px', width: '88px', background: '#dc2626', borderRadius: '999px' }} />
        <div style={{ marginTop: '24px', fontSize: '28px', lineHeight: 1.25, fontWeight: 800, color: '#334155', maxWidth: '780px' }}>
          {chapter || 'Chapitre en cours'}
        </div>
      </div>
    </div>
  )
}
