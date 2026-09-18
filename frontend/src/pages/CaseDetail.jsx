import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { AlertList, Chip, Empty, formatTime, humanize } from '../components/Evidence'

const STATUSES = ['open', 'in_progress', 'pending_review', 'closed']

export default function CaseDetail() {
  const { caseId } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [chains, setChains] = useState({ live: ['ethereum', 'polygon', 'bitcoin'], supported: [] })
  const [error, setError] = useState(null)
  const [note, setNote] = useState('')
  const [form, setForm] = useState({ address: '', chain: 'ethereum', seed_tx_hash: '', max_hops: 2 })
  const [starting, setStarting] = useState(false)

  const load = useCallback(() => {
    api.getCase(caseId).then(setData).catch((err) => setError(err.message))
  }, [caseId])

  useEffect(() => {
    load()
    api.chains().then(setChains).catch(() => {})
  }, [load])

  // Poll while a trace is running so the list updates without a manual refresh.
  useEffect(() => {
    const running = data?.investigations?.some((i) => i.status === 'queued' || i.status === 'running')
    if (!running) return undefined
    const timer = setInterval(load, 3000)
    return () => clearInterval(timer)
  }, [data, load])

  async function startTrace(e) {
    e.preventDefault()
    setError(null)
    setStarting(true)
    try {
      const investigation = await api.investigate(caseId, {
        address: form.address.trim(),
        chain: form.chain,
        seed_tx_hash: form.seed_tx_hash.trim() || null,
        max_hops: Number(form.max_hops),
      })
      navigate(`/investigations/${investigation.id}`)
    } catch (err) {
      setError(err.message)
    } finally {
      setStarting(false)
    }
  }

  async function submitNote(e) {
    e.preventDefault()
    if (!note.trim()) return
    await api.addNote(caseId, note.trim())
    setNote('')
    load()
  }

  async function changeStatus(status) {
    await api.setCaseStatus(caseId, status)
    load()
  }

  if (error && !data) return <div className="notice notice-error">{error}</div>
  if (!data) return <div className="empty"><span className="spinner" /> Loading case…</div>

  const unackAlerts = data.alerts.filter((a) => !a.acknowledged).length

  return (
    <div>
      <div className="page-head">
        <div className="row-between wrap">
          <div>
            <h1>{data.case_number}</h1>
            <p>
              {data.crime_type} · opened {formatTime(data.created_at)}
            </p>
          </div>
          <div className="row">
            <label htmlFor="status" className="tiny muted" style={{ margin: 0 }}>
              Status
            </label>
            <select
              id="status"
              value={data.status}
              onChange={(e) => changeStatus(e.target.value)}
              style={{ width: 'auto' }}
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {humanize(s)}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {data.victim_complaint && (
        <div className="panel" style={{ marginBottom: 'var(--space-5)' }}>
          <div className="panel-head">
            <h2>Complaint</h2>
          </div>
          <div className="panel-body">
            <p className="secondary" style={{ margin: 0 }}>{data.victim_complaint}</p>
          </div>
        </div>
      )}

      {error && <div className="notice notice-error" style={{ marginBottom: 'var(--space-4)' }}>{error}</div>}

      <div className="workspace">
        <div className="stack" style={{ gap: 'var(--space-5)' }}>
          <div className="panel">
            <div className="panel-head">
              <h2>Trace a wallet</h2>
            </div>
            <form className="panel-body" onSubmit={startTrace}>
              <div className="field">
                <label htmlFor="address">Wallet address</label>
                <input
                  id="address"
                  className="mono-input"
                  value={form.address}
                  onChange={(e) => setForm({ ...form, address: e.target.value })}
                  placeholder="0x… or bc1…"
                  required
                />
                <div className="field-hint">The address the complainant reported funds were sent to.</div>
              </div>

              <div className="row wrap" style={{ gap: 'var(--space-4)' }}>
                <div className="field grow" style={{ minWidth: '9rem' }}>
                  <label htmlFor="chain">Blockchain</label>
                  <select id="chain" value={form.chain} onChange={(e) => setForm({ ...form, chain: e.target.value })}>
                    {(chains.live || []).map((c) => (
                      <option key={c} value={c}>
                        {humanize(c)}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="field grow" style={{ minWidth: '9rem' }}>
                  <label htmlFor="max_hops">Trace depth</label>
                  <select
                    id="max_hops"
                    value={form.max_hops}
                    onChange={(e) => setForm({ ...form, max_hops: e.target.value })}
                  >
                    <option value={1}>1 hop — direct counterparties</option>
                    <option value={2}>2 hops — one layer beyond</option>
                    <option value={3}>3 hops — deepest, slowest</option>
                  </select>
                  <div className="field-hint">Deeper traces make many more API calls and take longer.</div>
                </div>
              </div>

              <div className="field">
                <label htmlFor="seed_tx_hash">Transaction hash (optional)</label>
                <input
                  id="seed_tx_hash"
                  className="mono-input"
                  value={form.seed_tx_hash}
                  onChange={(e) => setForm({ ...form, seed_tx_hash: e.target.value })}
                  placeholder="0x… the specific transfer the victim reported"
                />
              </div>

              <button className="btn btn-primary" type="submit" disabled={starting}>
                {starting && <span className="spinner" />}
                Start trace
              </button>
            </form>
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>Traces in this case</h2>
              <span className="tiny muted">{data.investigations.length} total</span>
            </div>
            <div className="panel-body-flush">
              {data.investigations.length === 0 ? (
                <Empty title="No traces yet">Enter a wallet address above to run the first trace.</Empty>
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Address</th>
                      <th>Chain</th>
                      <th>Status</th>
                      <th>Risk</th>
                      <th>Started</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.investigations.map((inv) => (
                      <tr key={inv.id} className="clickable" onClick={() => navigate(`/investigations/${inv.id}`)}>
                        <td>
                          <span className="addr">{`${inv.address.slice(0, 12)}…${inv.address.slice(-6)}`}</span>
                        </td>
                        <td className="secondary">{humanize(inv.chain)}</td>
                        <td>
                          {inv.status === 'running' || inv.status === 'queued' ? (
                            <span className="row tiny muted" style={{ gap: '0.35rem' }}>
                              <span className="spinner" /> {humanize(inv.status)}
                            </span>
                          ) : (
                            <Chip tone={inv.status === 'failed' ? 'risk-critical' : undefined}>{humanize(inv.status)}</Chip>
                          )}
                        </td>
                        <td>
                          {inv.risk_band ? (
                            <Chip tone={`risk-${inv.risk_band}`}>
                              {inv.risk_band} · {Number(inv.risk_score).toFixed(2)}
                            </Chip>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td className="muted tiny">{formatTime(inv.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>

        <div className="stack" style={{ gap: 'var(--space-5)' }}>
          <div className="panel">
            <div className="panel-head">
              <h2>Alerts</h2>
              {unackAlerts > 0 && <Chip tone="risk-high">{unackAlerts} new</Chip>}
            </div>
            <div className="panel-body-flush">
              <AlertList
                alerts={data.alerts}
                onAcknowledge={async (alertId) => {
                  await api.acknowledgeAlert(caseId, alertId)
                  load()
                }}
              />
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>Investigation notes</h2>
            </div>
            <div className="panel-body">
              <form onSubmit={submitNote}>
                <textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Record a decision, a request sent to an exchange, or a lead to follow."
                  aria-label="New investigation note"
                />
                <button className="btn btn-sm" type="submit" style={{ marginTop: 'var(--space-2)' }} disabled={!note.trim()}>
                  Add note
                </button>
              </form>

              {data.notes.length > 0 && (
                <>
                  <hr className="divider" />
                  <div className="stack" style={{ gap: 'var(--space-3)' }}>
                    {data.notes.map((n) => (
                      <div key={n.id}>
                        <div className="tiny muted">{formatTime(n.created_at)}</div>
                        <div className="small secondary">{n.body}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
