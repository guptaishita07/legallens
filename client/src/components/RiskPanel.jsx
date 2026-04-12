// src/components/RiskPanel.jsx
import { useQuery } from '@tanstack/react-query'
import { getRiskScore, getClauses, reanalyseDocument } from '../api/client'

const LEVEL_COLORS = {
  low:      { bg: 'var(--success-bg)', text: 'var(--success)',  bar: '#3B6D11' },
  medium:   { bg: 'var(--warn-bg)',    text: 'var(--warn)',     bar: '#854F0B' },
  high:     { bg: 'var(--danger-bg)', text: 'var(--danger)',   bar: '#A32D2D' },
  critical: { bg: '#500000',          text: '#FCEBEB',         bar: '#E24B4A' },
}

const CLAUSE_LABELS = {
  indemnification:   'Indemnification',
  termination:       'Termination',
  liability_cap:     'Liability cap',
  confidentiality:   'Confidentiality',
  governing_law:     'Governing law',
  dispute_resolution:'Dispute resolution',
  payment:           'Payment terms',
  ip_ownership:      'IP ownership',
  non_compete:       'Non-compete',
  force_majeure:     'Force majeure',
  auto_renewal:      'Auto-renewal',
  penalty:           'Penalty / damages',
  other:             'Other',
}

function ScoreMeter({ score }) {
  const level = score >= 80 ? 'critical' : score >= 60 ? 'high' : score >= 30 ? 'medium' : 'low'
  const col = LEVEL_COLORS[level]
  const label = level.charAt(0).toUpperCase() + level.slice(1)
  const circumference = 2 * Math.PI * 54
  const dashOffset = circumference - (score / 100) * circumference

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
      <svg width="130" height="130" viewBox="0 0 130 130">
        <circle cx="65" cy="65" r="54" fill="none" stroke="var(--border)" strokeWidth="10" />
        <circle
          cx="65" cy="65" r="54"
          fill="none"
          stroke={col.bar}
          strokeWidth="10"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          strokeLinecap="round"
          transform="rotate(-90 65 65)"
          style={{ transition: 'stroke-dashoffset 0.6s ease' }}
        />
        <text x="65" y="60" textAnchor="middle" fontSize="28" fontWeight="500"
              fill="var(--color-text-primary, #1a1a18)">{score}</text>
        <text x="65" y="80" textAnchor="middle" fontSize="12"
              fill="var(--color-text-secondary, #6b6b68)">/100</text>
      </svg>
      <div>
        <div style={{
          display: 'inline-block', padding: '3px 12px', borderRadius: 20,
          background: col.bg, color: col.text, fontWeight: 500, fontSize: 13, marginBottom: 8,
        }}>
          {label} risk
        </div>
        <p style={{ fontSize: 12, color: 'var(--muted)', maxWidth: 240, lineHeight: 1.6 }}>
          Risk score combines 7 contract signals and per-clause analysis.
        </p>
      </div>
    </div>
  )
}

function ClauseCard({ clause }) {
  const col = LEVEL_COLORS[clause.risk_level] || LEVEL_COLORS.low

  return (
    <div style={{
      background: 'var(--surface)',
      border: '1px solid var(--border)',
      borderLeft: `3px solid ${col.bar}`,
      borderRadius: 'var(--radius-sm)',
      padding: '14px 16px',
      borderTopLeftRadius: 0,
      borderBottomLeftRadius: 0,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <p style={{ fontWeight: 500, fontSize: 13 }}>{clause.title}</p>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            padding: '2px 8px', borderRadius: 12, fontSize: 11, fontWeight: 500,
            background: col.bg, color: col.text,
          }}>
            {clause.risk_score}/100
          </div>
          <span style={{ fontSize: 11, color: 'var(--muted)', background: 'var(--bg)',
            padding: '2px 7px', borderRadius: 10 }}>
            {CLAUSE_LABELS[clause.clause_type] || clause.clause_type}
          </span>
        </div>
      </div>

      {clause.summary && (
        <p style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.65, marginBottom: 8 }}>
          {clause.summary}
        </p>
      )}

      {clause.risk_reasons?.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 8 }}>
          {clause.risk_reasons.map((r, i) => (
            <span key={i} style={{
              fontSize: 11, padding: '2px 7px', borderRadius: 10,
              background: col.bg, color: col.text,
            }}>
              {r}
            </span>
          ))}
        </div>
      )}

      {clause.page_numbers?.length > 0 && (
        <p style={{ fontSize: 11, color: 'var(--hint)' }}>
          p.{clause.page_numbers.join(', ')}
        </p>
      )}
    </div>
  )
}

function SignalBreakdown({ breakdown }) {
  const signals = breakdown._signals || {}
  const entries = Object.entries(signals)
  if (!entries.length) return null

  const SIGNAL_LABELS = {
    uncapped_liability:       'Uncapped liability',
    unilateral_termination:   'Unilateral termination',
    missing_indemnification:  'Missing indemnification',
    auto_renewal_trap:        'Auto-renewal trap',
    onesided_ip:              'One-sided IP',
    punitive_penalties:       'Punitive penalties',
    unlimited_confidentiality:'Unlimited confidentiality',
  }
  const MAX = { uncapped_liability: 25, unilateral_termination: 20,
    missing_indemnification: 15, auto_renewal_trap: 15,
    onesided_ip: 10, punitive_penalties: 10, unlimited_confidentiality: 5 }

  return (
    <div>
      <p style={{ fontSize: 12, fontWeight: 500, marginBottom: 10, color: 'var(--text)' }}>
        7-signal breakdown
      </p>
      {entries.map(([key, val]) => {
        const max = MAX[key] || 25
        const pct = Math.round((val / max) * 100)
        const barColor = pct >= 80 ? '#A32D2D' : pct >= 50 ? '#854F0B' : '#3B6D11'
        return (
          <div key={key} style={{ marginBottom: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
              <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                {SIGNAL_LABELS[key] || key}
              </span>
              <span style={{ fontSize: 12, fontWeight: 500 }}>{val}/{max}</span>
            </div>
            <div style={{ height: 4, background: 'var(--border)', borderRadius: 4, overflow: 'hidden' }}>
              <div style={{ height: '100%', width: `${pct}%`, background: barColor,
                borderRadius: 4, transition: 'width 0.5s ease' }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default function RiskPanel({ document }) {
  const { data: risk, isLoading: rLoading, error: rError } = useQuery({
    queryKey: ['risk', document?.id],
    queryFn: () => getRiskScore(document.id),
    enabled: !!document?.id && document?.status === 'ready',
  })

  const { data: clauses = [], isLoading: cLoading } = useQuery({
    queryKey: ['clauses', document?.id],
    queryFn: () => getClauses(document.id),
    enabled: !!document?.id && document?.status === 'ready',
  })

  const handleReanalyse = async () => {
    try {
      await reanalyseDocument(document.id)
      alert('Reanalysis queued. Refresh in a moment.')
    } catch (e) {
      alert(e.response?.data?.detail || 'Failed to queue reanalysis.')
    }
  }

  if (!document) return (
    <div className="empty">
      <div className="empty-icon">🛡</div>
      <p className="empty-title">Select a document to view risk analysis</p>
    </div>
  )

  if (document.status !== 'ready') return (
    <div className="empty">
      <p className="empty-sub">Risk analysis will run automatically after ingestion completes.</p>
    </div>
  )

  if (rLoading || cLoading) return (
    <div className="empty"><div className="spinner" /></div>
  )

  if (rError) return (
    <div className="empty">
      <p className="empty-title">Risk score not yet available</p>
      <p className="empty-sub">The document may still be processing, or clause extraction hasn't run yet.</p>
      <button className="btn-primary" style={{ marginTop: 16 }} onClick={handleReanalyse}>
        Run analysis
      </button>
    </div>
  )

  return (
    <div style={{ padding: '20px 24px', overflowY: 'auto', height: '100%' }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20 }}>
        <p style={{ fontWeight: 500, fontSize: 15 }}>Risk analysis</p>
        <button className="btn-ghost" style={{ fontSize: 12 }} onClick={handleReanalyse}>
          Re-run analysis
        </button>
      </div>

      {/* Score meter */}
      <div className="card" style={{ marginBottom: 16 }}>
        <ScoreMeter score={risk.overall_score} />
        {risk.summary && (
          <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 16,
            lineHeight: 1.7, borderTop: '1px solid var(--border)', paddingTop: 14 }}>
            {risk.summary}
          </p>
        )}
      </div>

      {/* Stats row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 16 }}>
        {[
          { label: 'Clauses found', value: risk.clause_count },
          { label: 'High-risk clauses', value: risk.high_risk_count },
          { label: 'Overall score', value: `${risk.overall_score}/100` },
        ].map(s => (
          <div key={s.label} style={{
            background: 'var(--bg)', borderRadius: 'var(--radius-sm)',
            padding: '12px 14px',
          }}>
            <p style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>{s.label}</p>
            <p style={{ fontSize: 20, fontWeight: 500 }}>{s.value}</p>
          </div>
        ))}
      </div>

      {/* Signal breakdown */}
      {risk.score_breakdown && (
        <div className="card" style={{ marginBottom: 16 }}>
          <SignalBreakdown breakdown={risk.score_breakdown} />
        </div>
      )}

      {/* Clause cards */}
      <p style={{ fontSize: 12, fontWeight: 500, marginBottom: 10, color: 'var(--text)' }}>
        Extracted clauses ({clauses.length}) — sorted by risk
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {clauses.map(c => <ClauseCard key={c.id} clause={c} />)}
        {clauses.length === 0 && (
          <p className="text-sm text-muted" style={{ textAlign: 'center', padding: '24px 0' }}>
            No clauses extracted yet.
          </p>
        )}
      </div>
    </div>
  )
}
