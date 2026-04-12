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

// ── Phase 2 ──────────────────────────────────────────────────────────────────

export const getClauses = (id) =>
  api.get(`/documents/${id}/clauses`).then(r => r.data)

export const getRiskScore = (id) =>
  api.get(`/documents/${id}/risk`).then(r => r.data)

export const reanalyseDocument = (id) =>
  api.post(`/documents/${id}/reanalyse`).then(r => r.data)

export const getJobStatus = (taskId) =>
  api.get(`/documents/jobs/${taskId}`).then(r => r.data)

// ── Phase 3 — Auth ────────────────────────────────────────────────────────────

export const register = (email, name, password) =>
  api.post('/auth/register', { email, name, password }).then(r => r.data)

export const login = (email, password) => {
  const form = new FormData()
  form.append('username', email)
  form.append('password', password)
  return api.post('/auth/login', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
  }).then(r => r.data)
}

export const getMe = () =>
  api.get('/auth/me').then(r => r.data)

// ── Phase 3 — Comparison ──────────────────────────────────────────────────────

export const compareDocuments = (docAId, docBId) =>
  api.post('/compare/', { doc_a_id: docAId, doc_b_id: docBId }).then(r => r.data)

export const listComparisons = () =>
  api.get('/compare/').then(r => r.data)

export const getComparison = (id) =>
  api.get(`/compare/${id}`).then(r => r.data)

// ── Phase 3 — PDF Report ──────────────────────────────────────────────────────

export const downloadPdfReport = (documentId) => {
  window.open(`/api/reports/${documentId}/pdf`, '_blank')
}

// ── Auth token injection ──────────────────────────────────────────────────────

export const setAuthToken = (token) => {
  if (token) {
    api.defaults.headers.common['Authorization'] = `Bearer ${token}`
  } else {
    delete api.defaults.headers.common['Authorization']
  }
}
