import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, session } from '../api/client'
import { ThemeToggle } from '../theme/ThemeProvider'

export default function Login() {
  const navigate = useNavigate()
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState({ email: '', password: '', badge_id: '', full_name: '', unit: '' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  async function submit(e) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const result =
        mode === 'login'
          ? await api.login(form.email, form.password)
          : await api.register({
              badge_id: form.badge_id,
              full_name: form.full_name,
              email: form.email,
              password: form.password,
              unit: form.unit || null,
            })
      session.save(result.access_token, { id: result.investigator_id, name: result.investigator_name })
      navigate('/cases')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="row-between" style={{ marginBottom: 'var(--space-5)' }}>
          <div>
            <h1 style={{ letterSpacing: '-0.03em' }}>TraceX</h1>
            <p className="small muted" style={{ margin: 0 }}>
              Cryptocurrency investigation workspace
            </p>
          </div>
          <ThemeToggle />
        </div>

        <div className="panel">
          <div className="panel-head">
            <h2>{mode === 'login' ? 'Sign in' : 'Create an investigator account'}</h2>
          </div>
          <form className="panel-body" onSubmit={submit}>
            {mode === 'register' && (
              <>
                <div className="field">
                  <label htmlFor="full_name">Full name</label>
                  <input id="full_name" value={form.full_name} onChange={set('full_name')} required autoComplete="name" />
                </div>
                <div className="field">
                  <label htmlFor="badge_id">Badge or service ID</label>
                  <input id="badge_id" value={form.badge_id} onChange={set('badge_id')} required />
                </div>
                <div className="field">
                  <label htmlFor="unit">Unit</label>
                  <input id="unit" value={form.unit} onChange={set('unit')} placeholder="Cyber Crime Cell" />
                </div>
              </>
            )}

            <div className="field">
              <label htmlFor="email">Email</label>
              <input id="email" type="email" value={form.email} onChange={set('email')} required autoComplete="username" />
            </div>

            <div className="field">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                value={form.password}
                onChange={set('password')}
                required
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              />
            </div>

            {error && <div className="notice notice-error" style={{ marginBottom: 'var(--space-4)' }}>{error}</div>}

            <button className="btn btn-primary" type="submit" disabled={busy} style={{ width: '100%' }}>
              {busy && <span className="spinner" />}
              {mode === 'login' ? 'Sign in' : 'Create account'}
            </button>

            <hr className="divider" />

            <button
              type="button"
              className="btn btn-quiet"
              style={{ width: '100%' }}
              onClick={() => {
                setMode(mode === 'login' ? 'register' : 'login')
                setError(null)
              }}
            >
              {mode === 'login' ? 'Create an investigator account' : 'I already have an account'}
            </button>
          </form>
        </div>

        <p className="tiny muted" style={{ marginTop: 'var(--space-4)', textAlign: 'center' }}>
          Case data stays on your own deployment. Nothing is sent to a third party except the blockchain API calls
          needed to fetch public transaction data.
        </p>
      </div>
    </div>
  )
}
