/* eslint-disable react-refresh/only-export-components */
import { createRoot } from 'react-dom/client'
import './index.css'
import { SlidePreviewFrame } from './components/slides/PipelineSlidePreview'
import slides from './overflow-test-data.json'

function OverflowBench() {
  return (
    <div>
      {slides.map((slide, index) => (
        <div className="case" key={slide.slide_id || index} data-case-index={index}>
          <div className="case-label">
            #{index} · {slide.template_type} · {slide.slide_id || ''}
          </div>
          <SlidePreviewFrame slide={slide} maxWidth={960} padding={0} />
        </div>
      ))}
    </div>
  )
}

createRoot(document.getElementById('root')).render(<OverflowBench />)
