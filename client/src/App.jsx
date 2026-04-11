// src/App.jsx
import { useState } from 'react'
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query'
import { listDocuments, deleteDocument } from './api/client'
import UploadPanel from './components/UploadPanel'
import QAPanel from './components/QAPanel'
import ChunksPanel from './components/ChunksPanel'
import './index.css'

const queryClient = new QueryClient()

const TABS = [
  { id: 'qa',     label: '💬 Q&A' },
  { id: 'chunks', label: '🗂 Chunks' },
  { id: 'upload', label: '+ Upload' },
]

function Inner() {
  const qc = useQueryClient()
  const [selectedId, setSelectedId] = useState(null)
  const [tab, setTab] = useState('upload')

  const { data: docs = [], isLoading } = useQuery({
    queryKey: ['documents'],
    queryFn: listDocuments,
    refetchInterval: (query) => {
      const data = query.state.data
      const processing = data?.some(d => d.status === 'pending' || d.status === 'processing')
      return processing ? 3000 : false
    },
  })

  const selected = docs.find(d => d.id === selectedId) || null

  const handleUploaded = (doc) => {
    qc.invalidateQueries({ queryKey: ['documents'] })
    setSelectedId(doc.id)
    setTab('qa')
  }

  const handleDelete = async (e, id) => {
    e.stopPropagation()
    if (!confirm('Delete this document and all its data?')) return
    await deleteDocument(id)
    if (selectedId === id) setSelectedId(null)
    qc.invalidateQueries({ queryKey: ['documents'] })
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar-logo">Legal<span>Lens</span></div>

        <div style={{ padding: '12px 8px 4px' }}>
          <button className="btn-primary" style={{ width: '100%' }}
            onClick={() => { setSelectedId(null); setTab('upload') }}>
            + Upload contract
          </button>
        </div>

        <div className="sidebar-section">Contracts</div>

        {isLoading && <div style={{ padding: '12px 20px' }} className="text-muted text-sm">Loading...</div>}

        {docs.map(doc => (
          <div key={doc.id}
            className={`doc-item${doc.id === selectedId ? ' active' : ''}`}
            onClick={() => { setSelectedId(doc.id); setTab('qa') }}>
            <div className={`status-dot ${doc.status}`} title={doc.status} />
            <span className="doc-item-name" title={doc.filename}>{doc.filename}</span>
            <button className="btn-danger" style={{ padding: '2px 6px', fontSize: 11, opacity: 0.6 }}
              onClick={(e) => handleDelete(e, doc.id)} title="Delete">✕</button>
          </div>
        ))}

        {docs.length === 0 && !isLoading && (
          <div style={{ padding: '16px 20px' }} className="text-muted text-sm">
            No contracts yet. Upload one above.
          </div>
        )}

        <div style={{ marginTop: 'auto', padding: '12px 20px', borderTop: '1px solid var(--border)' }}>
          <p className="text-sm text-muted">Phase 1 — RAG foundation</p>
        </div>
      </aside>

      <div className="main">
        <div className="topbar">
          <div>
            <p className="topbar-title">{selected ? selected.filename : 'LegalLens'}</p>
            {selected && (
              <p className="topbar-sub">
                <span className={`badge badge-${selected.status}`}>{selected.status}</span>
                {selected.chunk_count > 0 && ` · ${selected.chunk_count} chunks`}
                {selected.page_count && ` · ${selected.page_count} pages`}
              </p>
            )}
          </div>
          <div className="flex gap-8" style={{ marginLeft: 'auto' }}>
            {TABS.map(t => (
              <button key={t.id}
                className={tab === t.id ? 'btn-primary' : 'btn-ghost'}
                style={{ fontSize: 12 }}
                onClick={() => setTab(t.id)}>
                {t.label}
              </button>
            ))}
          </div>
        </div>

        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          {tab === 'upload' && <UploadPanel onUploaded={handleUploaded} />}
          {tab === 'qa'     && <QAPanel document={selected} />}
          {tab === 'chunks' && <ChunksPanel document={selected} />}
        </div>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Inner />
    </QueryClientProvider>
  )
}
