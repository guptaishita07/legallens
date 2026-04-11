// src/components/QAPanel.jsx
import { useState, useRef, useEffect } from 'react'
import { askQuestion } from '../api/client'

const SUGGESTED = [
  'What are the termination conditions?',
  'Summarise the indemnification clause.',
  'What is the liability cap?',
  'Are there any auto-renewal terms?',
  'What jurisdiction governs this contract?',
]

function ConfidenceBar({ value }) {
  const pct = Math.round(value * 100)
  const color = value >= 0.75 ? 'var(--success)' : value >= 0.5 ? 'var(--warn)' : 'var(--danger)'
  return (
    <div className="confidence-row">
      <div className="conf-bar">
        <div className="conf-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span>{pct}% confidence</span>
    </div>
  )
}

function Message({ msg }) {
  const [expanded, setExpanded] = useState(null)

  if (msg.role === 'user') {
    return (
      <div className="msg msg-user">
        <div className="msg-bubble">{msg.content}</div>
      </div>
    )
  }

  return (
    <div className="msg msg-bot">
      <div className="msg-bubble">
        {msg.loading ? (
          <div className="flex items-center gap-8 text-muted">
            <div className="spinner" /> Thinking...
          </div>
        ) : (
          <>
            <p style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</p>
            {msg.confidence != null && <ConfidenceBar value={msg.confidence} />}
            {msg.sources?.length > 0 && (
              <div className="sources">
                {msg.sources.map((s, i) => (
                  <button
                    key={s.chunk_id}
                    className="source-chip"
                    onClick={() => setExpanded(expanded === i ? null : i)}
                  >
                    {s.section || `Excerpt ${i + 1}`}
                  </button>
                ))}
              </div>
            )}
            {expanded != null && msg.sources[expanded] && (
              <div style={{
                marginTop: 10,
                padding: '10px 12px',
                background: 'var(--bg)',
                borderRadius: 'var(--radius-sm)',
                fontSize: 12,
                color: 'var(--muted)',
                lineHeight: 1.65,
                borderLeft: '3px solid var(--accent)',
              }}>
                <p style={{ fontWeight: 500, color: 'var(--accent)', marginBottom: 4, fontSize: 11 }}>
                  {msg.sources[expanded].section || 'Source excerpt'}
                  {msg.sources[expanded].page_numbers?.length > 0 &&
                    ` · p.${msg.sources[expanded].page_numbers.join(', ')}`}
                </p>
                {msg.sources[expanded].excerpt}
              </div>
            )}
          </>
        )}
      </div>
      <span className="msg-meta">{msg.time}</span>
    </div>
  )
}

export default function QAPanel({ document }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Reset chat when document changes
  useEffect(() => {
    setMessages([])
  }, [document?.id])

  const send = async (question) => {
    const q = question || input.trim()
    if (!q || loading) return
    setInput('')

    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    const userMsg = { role: 'user', content: q, time }
    const loadingMsg = { role: 'bot', content: '', loading: true, time }

    setMessages(prev => [...prev, userMsg, loadingMsg])
    setLoading(true)

    try {
      const res = await askQuestion(document.id, q)
      setMessages(prev => [
        ...prev.slice(0, -1),
        {
          role: 'bot',
          content: res.answer,
          confidence: res.confidence,
          is_grounded: res.is_grounded,
          sources: res.sources,
          time,
        },
      ])
    } catch (e) {
      setMessages(prev => [
        ...prev.slice(0, -1),
        {
          role: 'bot',
          content: e.response?.data?.detail || 'Something went wrong. Please try again.',
          time,
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  if (!document) {
    return (
      <div className="empty">
        <div className="empty-icon">💬</div>
        <p className="empty-title">Select a document to start Q&A</p>
        <p className="empty-sub">Upload a contract and select it from the sidebar.</p>
      </div>
    )
  }

  if (document.status !== 'ready') {
    return (
      <div className="empty">
        <div className="empty-icon" style={{ fontSize: 28 }}>⏳</div>
        <p className="empty-title">Processing document...</p>
        <p className="empty-sub">
          Status: <span className={`badge badge-${document.status}`}>{document.status}</span>
          <br /><br />
          LegalLens is parsing and indexing your contract.<br />
          Refresh the sidebar in a few seconds.
        </p>
      </div>
    )
  }

  return (
    <div className="chat-wrap">
      {messages.length === 0 && (
        <div style={{ padding: '24px 24px 0' }}>
          <p className="text-muted text-sm mb-12">Try a question about this contract:</p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {SUGGESTED.map(q => (
              <button key={q} className="btn-ghost" style={{ fontSize: 12 }} onClick={() => send(q)}>
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="chat-messages">
        {messages.map((msg, i) => <Message key={i} msg={msg} />)}
        <div ref={bottomRef} />
      </div>

      <div className="chat-input-bar">
        <textarea
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask anything about this contract... (Enter to send)"
          rows={1}
          disabled={loading}
        />
        <button
          className="btn-primary"
          onClick={() => send()}
          disabled={!input.trim() || loading}
          style={{ padding: '8px 18px', whiteSpace: 'nowrap' }}
        >
          {loading ? <div className="spinner" style={{ borderTopColor: '#fff' }} /> : 'Ask'}
        </button>
      </div>
    </div>
  )
}
