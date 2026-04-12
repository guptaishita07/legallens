// src/components/JobProgress.jsx
// Polls /documents/jobs/{taskId} every 2s and shows a progress bar.
// Rendered in the sidebar next to a processing document.

import { useEffect, useState } from 'react'
import { getJobStatus } from '../api/client'

const STEP_LABELS = {
  parsing:             'Parsing PDF...',
  embedding:           'Generating embeddings...',
  extracting_clauses:  'Extracting clauses...',
  scoring_risk:        'Scoring risk...',
  ready:               'Complete',
}

export default function JobProgress({ taskId, onComplete }) {
  const [job, setJob] = useState(null)

  useEffect(() => {
    if (!taskId) return
    let stopped = false

    const poll = async () => {
      try {
        const data = await getJobStatus(taskId)
        if (!stopped) setJob(data)
        if (data.status === 'SUCCESS') {
          onComplete && onComplete()
          return
        }
        if (data.status !== 'FAILURE') {
          setTimeout(poll, 2000)
        }
      } catch {
        if (!stopped) setTimeout(poll, 3000)
      }
    }

    poll()
    return () => { stopped = true }
  }, [taskId])

  if (!job || job.status === 'SUCCESS') return null

  const pct = job.pct || 0
  const label = STEP_LABELS[job.step] || 'Processing...'
  const failed = job.status === 'FAILURE'

  return (
    <div style={{ padding: '8px 12px 4px', margin: '0 8px 8px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 11, color: failed ? 'var(--danger)' : 'var(--muted)' }}>
          {failed ? `Failed: ${job.error}` : label}
        </span>
        {!failed && <span style={{ fontSize: 11, color: 'var(--hint)' }}>{pct}%</span>}
      </div>
      {!failed && (
        <div style={{ height: 3, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
          <div style={{
            height: '100%', width: `${pct}%`,
            background: 'var(--accent)', borderRadius: 3,
            transition: 'width 0.4s ease',
          }} />
        </div>
      )}
    </div>
  )
}
