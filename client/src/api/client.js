// src/api/client.js
// Centralised API layer. All components import from here, not axios directly.

import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,  // 60s — LLM calls can be slow
})

// ── Documents ────────────────────────────────────────────────────────────────

export const uploadDocument = (file, onProgress) => {
  const form = new FormData()
  form.append('file', file)
  return api.post('/documents/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress) onProgress(Math.round((e.loaded * 100) / e.total))
    },
  })
}

export const listDocuments = () =>
  api.get('/documents/').then(r => r.data)

export const getDocument = (id) =>
  api.get(`/documents/${id}`).then(r => r.data)

export const deleteDocument = (id) =>
  api.delete(`/documents/${id}`)

// ── Q&A ──────────────────────────────────────────────────────────────────────

export const askQuestion = (documentId, question) =>
  api.post(`/qa/${documentId}/ask`, { question }).then(r => r.data)

export const getQAHistory = (documentId) =>
  api.get(`/qa/${documentId}/history`).then(r => r.data)

// ── Health ───────────────────────────────────────────────────────────────────

export const checkHealth = () =>
  api.get('/health').then(r => r.data)
