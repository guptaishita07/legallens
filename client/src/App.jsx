// src/App.jsx — Phase 3
import { useState } from 'react'
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query'
import { listDocuments, deleteDocument, downloadPdfReport } from './api/client'
import { AuthProvider, useAuth } from '../../../legallens 3/client/src/context/AuthContext'
import AuthPage from './components/AuthPage'
import UploadPanel from './components/UploadPanel'
import QAPanel from './components/QAPanel'
import ChunksPanel from './components/ChunksPanel'
import RiskPanel from './components/RiskPanel'
import ComparePanel from './components/ComparePanel'
import JobProgress from './components/JobProgress'
import './index.css'

const queryClient = new QueryClient()

const TABS = [
  { id: 'risk',    label: '🛡 Risk' },
  { id: 'qa',      label: '💬 Q&A' },
  { id: 'chunks',  label: '🗂 Chunks' },
  { id: 'compare', label: '⚖ Compare' },
  { id: 'upload',  label: '+ Upload' },
]

function AppShell() {
  const { user, signOut, isAuthed } = useAuth()
  const qc = useQueryClient()
  const [selectedId, setSelectedId] = useState(null)
  const [tab, setTab] = useState('upload')

  const { data: docs = [], isLoading } = useQuery({
    queryKey: ['documents'],
    queryFn: listDocuments,
    refetchInterval: (query) => {
      const data = query.state.data
      const anyProcessing = data?.some(d => d.status === 'pending' || d.status === 'processing')
      return anyProcessing ? 3000 : false
    },
  })

  const selected = docs.find(d => d.id === selectedId) || null

  const handleUploaded = (doc) => {
    qc.invalidateQueries({ queryKey: ['documents'] })
    setSelectedId(doc.id)
    setTab('risk')
  }

  const handleDelete = async (e, id) => {
    e.stopPropagation()
    if (!confirm('Delete this document and all its data?')) return
    await deleteDocument(id)
    if (selectedId === id) setSelectedId(null)
    qc.invalidateQueries({ queryKey: ['documents'] })
  }

  const handleJobComplete = () => {
    qc.invalidateQueries({ queryKey: ['documents'] })
    qc.invalidateQueries({ queryKey: ['risk', selectedId] })
    qc.invalidateQueries({ queryKey: ['clauses', selectedId] })
  }

  return (
    <div className="app">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-logo">Legal<span>Lens</span></div>

        <div style={{ padding: '12px 8px 4px', display: 'flex', flexDirection: 'column', gap: 6 }}>
          <button className="btn-primary" style={{ width: '100%' }}
            onClick={() => { setSelectedId(null); setTab('upload') }}>
            + Upload contract
          </button>
          <button className="btn-ghost" style={{ width: '100%', fontSize: 12 }}
            onClick={() => { setSelectedId(null); setTab('compare') }}>
            ⚖ Compare contracts
          </button>
        </div>

        <div className="sidebar-section">Contracts</div>

        {isLoading && <div style={{ padding: '12px 20px' }} className="text-muted text-sm">Loading...</div>}

        {docs.map(doc => (
          <div key={doc.id}>
            <div
              className={`doc-item${doc.id === selectedId ? ' active' : ''}`}
              onClick={() => { setSelectedId(doc.id); setTab('risk') }}>
              <div className={`status-dot ${doc.status}`} title={doc.status} />
              <span className="doc-item-name" title={doc.filename}>{doc.filename}</span>
              {doc.status === 'ready' && (
                <button
                  title="Download PDF report"
                  onClick={e => { e.stopPropagation(); downloadPdfReport(doc.id) }}
                  style={{
                    background: 'none', border: 'none', cursor: 'pointer',
                    fontSize: 13, padding: '0 2px', color: 'var(--muted)',
                  }}>
                  ↓
                </button>
              )}
              <button className="btn-danger" style={{ padding: '2px 6px', fontSize: 11, opacity: 0.6 }}
                onClick={(e) => handleDelete(e, doc.id)} title="Delete">✕</button>
            </div>
            {(doc.status === 'processing' || doc.status === 'pending') && doc.metadata_?.task_id && (
              <JobProgress taskId={doc.metadata_.task_id} onComplete={handleJobComplete} />
            )}
          </div>
        ))}

        {docs.length === 0 && !isLoading && (
          <div style={{ padding: '16px 20px' }} className="text-muted text-sm">
            No contracts yet. Upload one above.
          </div>
        )}

        {/* User bar */}
        <div style={{
          marginTop: 'auto', padding: '12px 16px',
          borderTop: '1px solid var(--border)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div>
            <p style={{ fontSize: 12, fontWeight: 500, color: 'var(--text)' }}>{user?.name || 'Guest'}</p>
            <p style={{ fontSize: 11, color: 'var(--muted)' }}>{user?.email || 'No account'}</p>
          </div>
          {isAuthed && (
            <button className="btn-ghost" style={{ fontSize: 11, padding: '4px 8px' }} onClick={signOut}>
              Sign out
            </button>
          )}
        </div>
      </aside>

      {/* Main */}
      <div className="main">
        <div className="topbar">
          <div>
            <p className="topbar-title">
              {tab === 'compare' ? 'Compare contracts'
               : tab === 'upload' ? 'Upload contract'
               : selected ? selected.filename : 'LegalLens'}
            </p>
            {selected && tab !== 'compare' && tab !== 'upload' && (
              <p className="topbar-sub">
                <span className={`badge badge-${selected.status}`}>{selected.status}</span>
                {selected.chunk_count > 0 && ` · ${selected.chunk_count} chunks`}
                {selected.page_count && ` · ${selected.page_count} pages`}
                {selected.status === 'ready' && (
                  <button
                    onClick={() => downloadPdfReport(selected.id)}
                    style={{
                      marginLeft: 10, fontSize: 11, padding: '2px 8px',
                      background: 'var(--accent-bg)', color: 'var(--accent)',
                      border: '1px solid var(--accent)', borderRadius: 'var(--radius-sm)',
                      cursor: 'pointer',
                    }}>
                    ↓ PDF report
                  </button>
                )}
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
          {tab === 'upload'  && <UploadPanel onUploaded={handleUploaded} />}
          {tab === 'risk'    && <RiskPanel document={selected} />}
          {tab === 'qa'      && <QAPanel document={selected} />}
          {tab === 'chunks'  && <ChunksPanel document={selected} />}
          {tab === 'compare' && <ComparePanel docs={docs} />}
        </div>
      </div>
    </div>
  )
}

function AuthGate() {
  const { isAuthed } = useAuth()
  if (!isAuthed) return <AuthPage />
  return <AppShell />
}

export default function App() {
  return (
    <AuthProvider>
      <QueryClientProvider client={queryClient}>
        <AuthGate />
      </QueryClientProvider>
    </AuthProvider>
  )
}
