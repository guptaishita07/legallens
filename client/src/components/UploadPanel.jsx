// src/components/UploadPanel.jsx
import { useState, useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { uploadDocument } from '../api/client'

export default function UploadPanel({ onUploaded }) {
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)

  const onDrop = useCallback(async (accepted) => {
    const file = accepted[0]
    if (!file) return
    setError(null)
    setDone(null)
    setUploading(true)
    setProgress(0)
    try {
      const res = await uploadDocument(file, setProgress)
      setDone(res.data)
      onUploaded && onUploaded(res.data)
    } catch (e) {
      setError(e.response?.data?.detail || 'Upload failed. Is the backend running?')
    } finally {
      setUploading(false)
    }
  }, [onUploaded])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'application/pdf': ['.pdf'] },
    maxFiles: 1,
    disabled: uploading,
  })

  return (
    <div style={{ padding: '24px', maxWidth: 560 }}>
      <p className="font-medium mb-12" style={{ fontSize: 15 }}>Upload a contract</p>

      <div {...getRootProps()} className={`dropzone${isDragActive ? ' active' : ''}`}>
        <input {...getInputProps()} />
        <div className="dropzone-icon">📄</div>
        <p className="dropzone-text">
          {isDragActive ? 'Drop the PDF here' : 'Drag & drop a PDF, or click to browse'}
        </p>
        <p className="dropzone-hint">Max 20 MB · PDF only</p>
      </div>

      {uploading && (
        <div className="mt-16">
          <div className="flex items-center gap-8 text-muted text-sm mb-4">
            <div className="spinner" />
            Uploading... {progress}%
          </div>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}

      {error && (
        <div className="mt-16" style={{
          padding: '10px 14px',
          background: 'var(--danger-bg)',
          color: 'var(--danger)',
          borderRadius: 'var(--radius-sm)',
          fontSize: 13,
        }}>
          {error}
        </div>
      )}

      {done && (
        <div className="mt-16" style={{
          padding: '10px 14px',
          background: 'var(--success-bg)',
          color: 'var(--success)',
          borderRadius: 'var(--radius-sm)',
          fontSize: 13,
        }}>
          ✓ <strong>{done.filename}</strong> uploaded — processing in background.
          Select it from the sidebar when status turns green.
        </div>
      )}

      <div className="mt-24">
        <p className="text-sm text-muted" style={{ lineHeight: 1.7 }}>
          After upload, LegalLens will:<br />
          1. Parse the PDF and split it into semantic chunks<br />
          2. Generate embeddings for each chunk<br />
          3. Build a hybrid BM25 + vector index<br />
          4. Mark the document as Ready for Q&A
        </p>
      </div>
    </div>
  )
}
