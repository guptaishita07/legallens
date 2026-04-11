// src/components/ChunksPanel.jsx
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getDocument } from '../api/client'

export default function ChunksPanel({ document }) {
  const [search, setSearch] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['document', document?.id],
    queryFn: () => getDocument(document.id),
    enabled: !!document?.id && document?.status === 'ready',
  })

  if (!document) return null

  if (document.status !== 'ready') {
    return (
      <div className="empty">
        <p className="empty-sub">Document not yet indexed.</p>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="empty">
        <div className="spinner" />
      </div>
    )
  }

  const chunks = data?.chunks || []
  const filtered = search
    ? chunks.filter(c =>
        c.content.toLowerCase().includes(search.toLowerCase()) ||
        c.section?.toLowerCase().includes(search.toLowerCase())
      )
    : chunks

  return (
    <div style={{ padding: '20px 24px', overflowY: 'auto', height: '100%' }}>
      <div className="flex items-center justify-between mb-12">
        <p className="font-medium">{chunks.length} chunks indexed</p>
        <span className="badge badge-info">
          {data?.char_count?.toLocaleString()} chars · {data?.page_count} pages
        </span>
      </div>

      <input
        placeholder="Search chunks..."
        value={search}
        onChange={e => setSearch(e.target.value)}
        style={{ marginBottom: 16 }}
      />

      <div className="chunk-list">
        {filtered.map(chunk => (
          <div key={chunk.id} className="chunk-card">
            <div className="flex items-center justify-between mb-4">
              <p className="chunk-section">{chunk.section || `Chunk ${chunk.chunk_index}`}</p>
              <span className="text-sm text-muted">
                {chunk.token_count} tokens
                {chunk.page_numbers?.length > 0 && ` · p.${chunk.page_numbers.join(', ')}`}
              </span>
            </div>
            <p className="chunk-content">
              {chunk.content.length > 400 ? chunk.content.slice(0, 400) + '…' : chunk.content}
            </p>
          </div>
        ))}
        {filtered.length === 0 && (
          <p className="text-muted text-sm" style={{ textAlign: 'center', marginTop: 24 }}>
            No chunks match your search.
          </p>
        )}
      </div>
    </div>
  )
}
