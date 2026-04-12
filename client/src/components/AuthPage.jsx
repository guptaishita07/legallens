// src/components/AuthPage.jsx
import { useState } from 'react'
import { register, login } from '../api/client'
import { useAuth } from '../../../../legallens 3/client/src/context/AuthContext'

export default function AuthPage() {
  const { signIn } = useAuth()
  const [mode, setMode]       = useState('login')   // 'login' | 'register'
  const [email, setEmail]     = useState('')
  const [name, setName]       = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      let res
      if (mode === 'register') {
        res = await register(email, name, password)
      } else {
        res = await login(email, password)
      }
      signIn(res.access_token, res.user)
    } catch (err) {
      setError(err.response?.data?.detail || 'Something went wrong.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center',
      justifyContent: 'center', background: 'var(--bg)',
    }}>
      <div style={{
        width: 380, background: 'var(--surface)',
        border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)',
        padding: '32px 28px',
      }}>
        {/* Logo */}
        <p style={{ fontSize: 20, fontWeight: 600, marginBottom: 4, textAlign: 'center' }}>
          Legal<span style={{ color: 'var(--accent)' }}>Lens</span>
        </p>
        <p style={{ fontSize: 13, color: 'var(--muted)', textAlign: 'center', marginBottom: 24 }}>
          {mode === 'login' ? 'Sign in to your account' : 'Create an account'}
        </p>

        <form onSubmit={submit}>
          {mode === 'register' && (
            <div style={{ marginBottom: 12 }}>
              <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>
                Name
              </label>
              <input
                value={name} onChange={e => setName(e.target.value)}
                placeholder="Your name" required
              />
            </div>
          )}

          <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>
              Email
            </label>
            <input
              type="email" value={email} onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com" required
            />
          </div>

          <div style={{ marginBottom: 20 }}>
            <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>
              Password
            </label>
            <input
              type="password" value={password} onChange={e => setPassword(e.target.value)}
              placeholder={mode === 'register' ? 'At least 8 characters' : '••••••••'} required
            />
          </div>

          {error && (
            <div style={{
              padding: '8px 12px', background: 'var(--danger-bg)', color: 'var(--danger)',
              borderRadius: 'var(--radius-sm)', fontSize: 13, marginBottom: 12,
            }}>
              {error}
            </div>
          )}

          <button type="submit" className="btn-primary"
            style={{ width: '100%', padding: '10px' }} disabled={loading}>
            {loading
              ? <div className="spinner" style={{ borderTopColor: '#fff', margin: '0 auto' }} />
              : mode === 'login' ? 'Sign in' : 'Create account'
            }
          </button>
        </form>

        <p style={{ marginTop: 16, fontSize: 12, color: 'var(--muted)', textAlign: 'center' }}>
          {mode === 'login' ? "Don't have an account? " : "Already have an account? "}
          <button
            onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(null) }}
            style={{
              background: 'none', border: 'none', color: 'var(--accent)',
              cursor: 'pointer', fontSize: 12, textDecoration: 'underline', padding: 0,
            }}>
            {mode === 'login' ? 'Register' : 'Sign in'}
          </button>
        </p>

        {/* Dev shortcut — skip auth */}
        <p style={{ marginTop: 8, fontSize: 11, color: 'var(--hint)', textAlign: 'center' }}>
          <button
            onClick={() => signIn('dev-token', { id: 'dev', email: 'dev@local', name: 'Dev User' })}
            style={{ background: 'none', border: 'none', color: 'var(--hint)',
              cursor: 'pointer', fontSize: 11, textDecoration: 'underline', padding: 0 }}>
            Skip auth (dev mode)
          </button>
        </p>
      </div>
    </div>
  )
}
