import { useEffect, useRef, useState } from 'react'

import { renderSlideTemplate } from './slideTemplateRegistry'

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
          {renderSlideTemplate(slide)}
        </div>
      </div>
    </div>
  )
}
