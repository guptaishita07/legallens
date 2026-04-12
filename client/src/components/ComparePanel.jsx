// src/components/ComparePanel.jsx
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listDocuments, compareDocuments, listComparisons, getComparison } from '../api/client'

const WINNER_LABELS = {
  a:            { text: 'A better', color: '#3B6D11', bg: '#EAF3DE' },
  b:            { text: 'B better', color: '#185FA5', bg: '#E6F1FB' },
  tie:          { text: 'Tie',      color: '#854F0B', bg: '#FAEEDA' },
  missing_both: { text: 'Missing',  color: '#6b6b68', bg: '#f1efe8' },
}

function ScorePill({ score, label }) {
  if (score == null) return <span style={{ color: '#a3a3a0', fontSize: 12 }}>—</span>
  const color = score >= 80 ? '#A32D2D' : score >= 60 ? '#854F0B' : score >= 30 ? '#185FA5' : '#3B6D11'
  const bg    = score >= 80 ? '#FCEBEB' : score >= 60 ? '#FAEEDA' : score >= 30 ? '#E6F1FB' : '#EAF3DE'
  return (
    <span style={{ padding: '2px 8px', borderRadius: 10, background: bg, color, fontSize: 11, fontWeight: 500 }}>
      {label && `${label}: `}{score}/100
    </span>
  )
}

function ClauseDiffRow({ diff }) {
  const [open, setOpen] = useState(false)
  const w = WINNER_LABELS[diff.winner] || WINNER_LABELS.tie

  return (
    <div style={{
      border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
      overflow: 'hidden', marginBottom: 8,
    }}>
      <div
        onClick={() => setOpen(!open)}
        style={{
          display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px',
          cursor: 'pointer', background: 'var(--surface)',
        }}>
        <span style={{ fontWeight: 500, fontSize: 13, flex: 1 }}>{diff.label}</span>
        <ScorePill score={diff.doc_a_score} label="A" />
        <ScorePill score={diff.doc_b_score} label="B" />
        <span style={{
          fontSize: 11, fontWeight: 500, padding: '2px 8px', borderRadius: 10,
          background: w.bg, color: w.color,
        }}>
          {w.text}
        </span>
        <span style={{ fontSize: 12, color: 'var(--hint)' }}>{open ? '▲' : '▼'}</span>
      </div>

      {open && (
        <div style={{ padding: '12px 14px', background: 'var(--bg)', borderTop: '1px solid var(--border)' }}>
          {diff.narrative && (
            <p style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.65, marginBottom: 10 }}>
              {diff.narrative}
            </p>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            {[
              { label: 'Contract A', summary: diff.doc_a_summary, risks: diff.doc_a_risks, score: diff.doc_a_score },
              { label: 'Contract B', summary: diff.doc_b_summary, risks: diff.doc_b_risks, score: diff.doc_b_score },
            ].map((side) => (
              <div key={side.label} style={{
                background: 'var(--surface)', border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)', padding: '10px 12px',
              }}>
                <p style={{ fontSize: 11, fontWeight: 500, color: 'var(--muted)', marginBottom: 6 }}>
                  {side.label}
                </p>
                {side.summary
                  ? <p style={{ fontSize: 12, color: 'var(--text)', lineHeight: 1.6 }}>{side.summary}</p>
                  : <p style={{ fontSize: 12, color: 'var(--hint)' }}>Not present in this contract</p>
                }
                {side.risks?.length > 0 && (
                  <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {side.risks.map((r, i) => (
                      <span key={i} style={{
                        fontSize: 10, padding: '1px 6px', borderRadius: 8,
                        background: 'var(--danger-bg)', color: 'var(--danger)',
                      }}>{r}</span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function ReportView({ reportId, onBack }) {
  const { data: report, isLoading } = useQuery({
    queryKey: ['comparison', reportId],
    queryFn: () => getComparison(reportId),
  })

  if (isLoading) return <div className="empty"><div className="spinner" /></div>
  if (!report) return null

  const aWins = report.clause_diffs.filter(d => d.winner === 'a').length
  const bWins = report.clause_diffs.filter(d => d.winner === 'b').length

  return (
    <div style={{ padding: '20px 24px', overflowY: 'auto', height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <button className="btn-ghost" style={{ fontSize: 12 }} onClick={onBack}>← Back</button>
        <p style={{ fontWeight: 500, fontSize: 15 }}>Comparison report</p>
      </div>

      {/* Doc scores */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
        {[
          { name: report.doc_a_name, score: report.doc_a_score, wins: aWins, label: 'A' },
          { name: report.doc_b_name, score: report.doc_b_score, wins: bWins, label: 'B' },
        ].map(d => (
          <div key={d.label} className="card">
            <p style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Contract {d.label}</p>
            <p style={{ fontWeight: 500, fontSize: 13, marginBottom: 8, overflow: 'hidden',
              textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.name}</p>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <ScorePill score={d.score} />
              <span style={{ fontSize: 12, color: 'var(--muted)' }}>{d.wins} clauses won</span>
            </div>
          </div>
        ))}
      </div>

      {/* Recommendation */}
      {report.recommendation && (
        <div style={{
          padding: '14px 16px', background: 'var(--accent-bg)',
          borderRadius: 'var(--radius-sm)', marginBottom: 16,
          borderLeft: '3px solid var(--accent)',
        }}>
          <p style={{ fontSize: 11, fontWeight: 500, color: 'var(--accent)', marginBottom: 4 }}>
            Recommendation
          </p>
          <p style={{ fontSize: 13, color: 'var(--text)', lineHeight: 1.65 }}>
            {report.recommendation}
          </p>
        </div>
      )}

      {/* Clause diffs */}
      <p style={{ fontSize: 12, fontWeight: 500, marginBottom: 10 }}>
        Clause-by-clause comparison ({report.clause_diffs.length} clauses)
      </p>
      {report.clause_diffs.map((d, i) => <ClauseDiffRow key={i} diff={d} />)}
    </div>
  )
}

export default function ComparePanel({ docs = [] }) {
  const [docA, setDocA]       = useState('')
  const [docB, setDocB]       = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [viewReport, setViewReport] = useState(null)

  const { data: comparisons = [], refetch } = useQuery({
    queryKey: ['comparisons'],
    queryFn: listComparisons,
  })

  const readyDocs = docs.filter(d => d.status === 'ready')

  const run = async () => {
    if (!docA || !docB) return
    setError(null)
    setLoading(true)
    try {
      const report = await compareDocuments(docA, docB)
      refetch()
      setViewReport(report.id)
    } catch (e) {
      setError(e.response?.data?.detail || 'Comparison failed.')
    } finally {
      setLoading(false)
    }
  }

  if (viewReport) {
    return <ReportView reportId={viewReport} onBack={() => setViewReport(null)} />
  }

  return (
    <div style={{ padding: '20px 24px', overflowY: 'auto', height: '100%' }}>
      <p style={{ fontWeight: 500, fontSize: 15, marginBottom: 16 }}>Compare contracts</p>

      {/* Selector */}
      <div className="card" style={{ marginBottom: 16 }}>
        <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 12 }}>
          Select two ready contracts to compare side-by-side.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
          {[
            { label: 'Contract A', val: docA, set: setDocA, exclude: docB },
            { label: 'Contract B', val: docB, set: setDocB, exclude: docA },
          ].map(s => (
            <div key={s.label}>
              <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>
                {s.label}
              </label>
              <select
                value={s.val}
                onChange={e => s.set(e.target.value)}
                style={{
                  width: '100%', padding: '8px 10px', fontSize: 13,
                  border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
                  background: 'var(--surface)', color: 'var(--text)',
                }}>
                <option value="">— Select —</option>
                {readyDocs.filter(d => d.id !== s.exclude).map(d => (
                  <option key={d.id} value={d.id}>{d.filename}</option>
                ))}
              </select>
            </div>
          ))}
        </div>

        {error && (
          <p style={{ fontSize: 12, color: 'var(--danger)', marginBottom: 10 }}>{error}</p>
        )}

        <button
          className="btn-primary"
          onClick={run}
          disabled={!docA || !docB || loading || docA === docB}>
          {loading
            ? <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div className="spinner" style={{ borderTopColor: '#fff' }} /> Comparing...
              </span>
            : 'Run comparison'}
        </button>

        {readyDocs.length < 2 && (
          <p style={{ fontSize: 12, color: 'var(--hint)', marginTop: 10 }}>
            You need at least 2 ready contracts to compare. Upload and process more contracts first.
          </p>
        )}
      </div>

      {/* Past comparisons */}
      {comparisons.length > 0 && (
        <>
          <p style={{ fontSize: 12, fontWeight: 500, marginBottom: 10, color: 'var(--text)' }}>
            Past comparisons
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {comparisons.map(c => (
              <div
                key={c.id}
                onClick={() => setViewReport(c.id)}
                className="card"
                style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <p style={{ fontSize: 13, fontWeight: 500 }}>
                    {c.doc_a_name} <span style={{ color: 'var(--muted)' }}>vs</span> {c.doc_b_name}
                  </p>
                  <p style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
                    {new Date(c.created_at).toLocaleDateString()}
                  </p>
                </div>
                <ScorePill score={c.doc_a_score} label="A" />
                <ScorePill score={c.doc_b_score} label="B" />
                <span style={{ fontSize: 12, color: 'var(--hint)' }}>→</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
