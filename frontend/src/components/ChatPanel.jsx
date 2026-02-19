import { useState, useRef, useEffect } from 'react'
import { apiUrl } from '../api'

function formatMarkdown(text) {
  // Gras **texte**
  let html = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  // Listes à puces "- item"
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>')
  html = html.replace(/(<li>.*<\/li>)/s, '<ul class="list-disc pl-4 my-1">$1</ul>')
  // Sauts de ligne
  html = html.replace(/\n/g, '<br/>')
  // Nettoyer les <br/> autour des <ul>
  html = html.replace(/<br\/><ul/g, '<ul').replace(/<\/ul><br\/>/g, '</ul>')
  html = html.replace(/<br\/><li/g, '<li').replace(/<\/li><br\/>/g, '</li>')
  return html
}

export default function ChatPanel({ open, onClose }) {
  const [messages, setMessages] = useState([])
  const [history, setHistory] = useState([])
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [panelWidth, setPanelWidth] = useState(400)
  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)
  const isDragging = useRef(false)

  // Resize handle drag
  useEffect(() => {
    const handleMouseMove = (e) => {
      if (!isDragging.current) return
      const newWidth = window.innerWidth - e.clientX
      const maxWidth = Math.floor(window.innerWidth * 0.40)
      setPanelWidth(Math.max(300, Math.min(maxWidth, newWidth)))
    }
    const handleMouseUp = () => {
      isDragging.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [])

  // Auto-resize du textarea
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = '44px'
    if (question) {
      el.style.height = `${Math.max(44, el.scrollHeight)}px`
    }
  }, [question])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = async (event) => {
    event.preventDefault()
    const text = question.trim()
    if (!text || loading) return

    const userMessage = { id: Date.now(), role: 'user', content: text }
    setMessages((prev) => [...prev, userMessage])
    setQuestion('')
    setLoading(true)

    try {
      const response = await fetch(apiUrl('/api/chat'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ question: text, history }),
      })
      const data = await response.json()
      const answer = data.answer || "Désolé, je n'ai pas pu répondre."

      // Délai de 5 secondes avant d'afficher la réponse
      setTimeout(() => {
        setMessages((prev) => [...prev, { id: Date.now() + 1, role: 'assistant', content: answer }])
        setHistory((prev) => [
          ...prev,
          { role: 'user', content: text },
          { role: 'assistant', content: answer },
        ])
        setLoading(false)
      }, 5000)
    } catch {
      setTimeout(() => {
        setMessages((prev) => [
          ...prev,
          { id: Date.now() + 1, role: 'assistant', content: "Erreur de connexion au serveur." },
        ])
        setLoading(false)
      }, 5000)
    }
  }

  return (
    <div
      id="chat"
      className="flex-shrink-0 h-screen flex flex-row"
      style={{ width: open ? `${panelWidth}px` : '0px', overflow: open ? 'visible' : 'hidden' }}
    >
      {/* Resize handle */}
      <div
        className="w-1.5 h-full cursor-col-resize flex items-center justify-center group hover:bg-purple-500/20 transition-colors"
        style={{ backgroundColor: 'rgba(147, 51, 234, 0.08)' }}
        onMouseDown={() => {
          isDragging.current = true
          document.body.style.cursor = 'col-resize'
          document.body.style.userSelect = 'none'
        }}
      >
        <div className="w-0.5 h-8 rounded-full bg-purple-400/50 group-hover:bg-purple-500 group-hover:h-12 transition-all" />
      </div>
      <div className="flex-1 flex flex-col border-l border-gray-200 overflow-hidden" style={{ backgroundColor: '#ffffff' }}>
      {/* Header */}
      <div className="px-6 border-b border-gray-200 flex-shrink-0 flex flex-col justify-center" style={{ height: '64px' }}>
        <h3 className="text-xl font-semibold text-gray-800">Messages</h3>
        <p className="text-sm text-gray-400 mt-0.5 truncate">
          Posez vos questions sur le cours, l'assistant vous répond en temps réel.
        </p>
      </div>

      {/* Messages */}
      <div
        id="messages"
        className="flex-1 overflow-y-auto px-6 py-4 space-y-4 scrollbar-thin scrollbar-thumb-gray-300 scrollbar-track-transparent min-h-0 bg-gray-50"
      >
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center text-gray-400 gap-2">
            <svg xmlns="http://www.w3.org/2000/svg" className="w-10 h-10 text-gray-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
            </svg>
            <p className="text-sm">Posez votre première question sur le cours</p>
          </div>
        )}

        {messages.map((msg) => (
          <div key={msg.id} className={`flex gap-3 items-start ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
            {msg.role === 'assistant' && (
              <div className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center bg-amber-100 border border-black">
                <img src="/professor-icon.png" alt="Professeur" className="w-5 h-5" />
              </div>
            )}
            <div className={`max-w-[80%] px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
              msg.role === 'user'
                ? 'bg-purple-600 text-white rounded-tr-sm'
                : 'bg-white text-gray-700 border border-gray-200 rounded-tl-sm'
            }`}>
              {msg.role === 'assistant'
                ? <span dangerouslySetInnerHTML={{ __html: formatMarkdown(msg.content) }} />
                : msg.content
              }
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex gap-3 items-start">
            <div className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center bg-amber-100 border border-black">
              <img src="/professor-icon.png" alt="Professeur" className="w-5 h-5" />
            </div>
            <div className="max-w-[80%] px-4 py-2.5 rounded-2xl text-sm leading-relaxed bg-white text-gray-700 border border-gray-200 rounded-tl-sm">
              Un instant, le professeur va vous répondre...
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <form className="p-6 border-t border-gray-200 flex-shrink-0 bg-white" onSubmit={handleSend}>
        <div className="flex gap-3 items-end">
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              id="question"
              rows={1}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSend(e)
                }
              }}
              placeholder="Écrire un message..."
              className="w-full resize-none overflow-hidden px-4 py-3 bg-gray-100 rounded-lg text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500/50 transition-all leading-relaxed"
              style={{ maxHeight: '160px', overflowY: 'auto' }}
              disabled={loading}
            />
          </div>
          <button
            id="send-btn"
            type="submit"
            className="w-10 h-10 bg-purple-600 hover:bg-purple-700 rounded-lg flex items-center justify-center transition-colors flex-shrink-0 disabled:opacity-50 disabled:cursor-not-allowed self-end mb-3"
            disabled={!question.trim() || loading}
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5 text-white" viewBox="0 0 24 24" fill="currentColor">
              <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
            </svg>
          </button>
        </div>
      </form>
      </div>
    </div>
  )
}
