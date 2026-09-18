import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { Chip, Empty, formatTime, humanize } from '../components/Evidence'

const CRIME_TYPES = [
  'Investment fraud',
  'Pig butchering / romance scam',
  'Phishing',
  'Ransomware',
  'Extortion',
  'Unauthorised transfer',
  'Darknet marketplace',
  'Other',
]

export default function Cases() {
  const navigate = useNavigate()
  const [cases, setCases] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ case_number: '', crime_type: CRIME_TYPES[0], victim_complaint: '' })

  useEffect(() => {
    api
      .listCases()
      .then(setCases)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  async function createCase(e) {
    e.preventDefault()
    setError(null)
    try {
      const created = await api.createCase(form)
      navigate(`/cases/${created.id}`)
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div>
      <div className="page-head row-between">
        <div>
          <h1>Cases</h1>
          <p>Every trace belongs to a case, so the evidence trail stays attached to the complaint it came from.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setCreating(!creating)}>
          {creating ? 'Cancel' : 'New case'}
        </button>
      </div>

      {error && <div className="notice notice-error" style={{ marginBottom: 'var(--space-4)' }}>{error}</div>}

      {creating && (
        <div className="panel" style={{ marginBottom: 'var(--space-5)' }}>
          <div className="panel-head">
            <h2>Open a case</h2>
          </div>
          <form className="panel-body" onSubmit={createCase}>
            <div className="field">
              <label htmlFor="case_number">Case number</label>
              <input
                id="case_number"
                value={form.case_number}
                onChange={(e) => setForm({ ...form, case_number: e.target.value })}
                placeholder="CYB/2026/00412"
                required
              />
              <div className="field-hint">Use your unit&rsquo;s own reference so this matches the physical file.</div>
            </div>

            <div className="field">
              <label htmlFor="crime_type">Crime type</label>
              <select
                id="crime_type"
                value={form.crime_type}
                onChange={(e) => setForm({ ...form, crime_type: e.target.value })}
              >
                {CRIME_TYPES.map((type) => (
                  <option key={type}>{type}</option>
                ))}
              </select>
            </div>

            <div className="field">
              <label htmlFor="victim_complaint">Victim complaint</label>
              <textarea
                id="victim_complaint"
                value={form.victim_complaint}
                onChange={(e) => setForm({ ...form, victim_complaint: e.target.value })}
                placeholder="What the complainant reported: how contact was made, what was transferred, when, and to which address."
              />
            </div>

            <button className="btn btn-primary" type="submit">
              Open case
            </button>
          </form>
        </div>
      )}

      <div className="panel">
        <div className="panel-body-flush">
          {loading ? (
            <div className="empty">
              <span className="spinner" /> Loading cases…
            </div>
          ) : cases.length === 0 ? (
            <Empty title="No cases yet">Open a case to start tracing a reported wallet.</Empty>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Case number</th>
                  <th>Crime type</th>
                  <th>Status</th>
                  <th>Opened</th>
                  <th>Last activity</th>
                </tr>
              </thead>
              <tbody>
                {cases.map((c) => (
                  <tr key={c.id} className="clickable" onClick={() => navigate(`/cases/${c.id}`)}>
                    <td>
                      <Link to={`/cases/${c.id}`} style={{ fontWeight: 600 }} onClick={(e) => e.stopPropagation()}>
                        {c.case_number}
                      </Link>
                    </td>
                    <td className="secondary">{c.crime_type}</td>
                    <td>
                      <Chip>{humanize(c.status)}</Chip>
                    </td>
                    <td className="muted tiny">{formatTime(c.created_at)}</td>
                    <td className="muted tiny">{formatTime(c.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
