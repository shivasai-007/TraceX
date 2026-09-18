import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { Address, Chip, Empty, humanize } from '../components/Evidence'

const TYPES = ['vasp', 'exchange', 'dex', 'mixer', 'bridge', 'custodian', 'scam', 'ransomware']
const TIERS = ['observed', 'inferred', 'attributed', 'confirmed']

export default function Entities() {
  const [entities, setEntities] = useState([])
  const [filter, setFilter] = useState('')
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState(null)
  const [form, setForm] = useState({
    name: '', entity_type: 'exchange', chain: 'ethereum', address: '',
    source: '', source_date: '', evidence: '', confidence: 'attributed',
  })

  const load = () => api.listEntities().then(setEntities).catch((err) => setError(err.message))
  useEffect(() => { load() }, [])

  async function submit(e) {
    e.preventDefault()
    setError(null)
    try {
      await api.createEntity({ ...form, source_date: form.source_date || null, evidence: form.evidence || null })
      setForm({ ...form, name: '', address: '', source: '', evidence: '' })
      setAdding(false)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  const shown = entities.filter(
    (e) => !filter || e.name.toLowerCase().includes(filter.toLowerCase()) || e.address.includes(filter.toLowerCase()),
  )

  return (
    <div>
      <div className="page-head row-between wrap">
        <div>
          <h1>Entity intelligence</h1>
          <p>
            Known addresses the tracer checks against. Every confirmed attribution you record here makes the next
            case faster — this is where a closed case feeds back into the system.
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => setAdding(!adding)}>
          {adding ? 'Cancel' : 'Add attribution'}
        </button>
      </div>

      {error && <div className="notice notice-error" style={{ marginBottom: 'var(--space-4)' }}>{error}</div>}

      {adding && (
        <div className="panel" style={{ marginBottom: 'var(--space-5)' }}>
          <div className="panel-head"><h2>Record an attribution</h2></div>
          <form className="panel-body" onSubmit={submit}>
            <div className="row wrap" style={{ gap: 'var(--space-4)', alignItems: 'flex-start' }}>
              <div className="field grow" style={{ minWidth: '12rem' }}>
                <label htmlFor="e-name">Entity name</label>
                <input id="e-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              </div>
              <div className="field grow" style={{ minWidth: '9rem' }}>
                <label htmlFor="e-type">Type</label>
                <select id="e-type" value={form.entity_type} onChange={(e) => setForm({ ...form, entity_type: e.target.value })}>
                  {TYPES.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
                </select>
              </div>
              <div className="field grow" style={{ minWidth: '9rem' }}>
                <label htmlFor="e-chain">Chain</label>
                <select id="e-chain" value={form.chain} onChange={(e) => setForm({ ...form, chain: e.target.value })}>
                  {['ethereum', 'polygon', 'bitcoin', 'tron'].map((c) => <option key={c} value={c}>{humanize(c)}</option>)}
                </select>
              </div>
            </div>

            <div className="field">
              <label htmlFor="e-address">Address</label>
              <input id="e-address" className="mono-input" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} required />
            </div>

            <div className="row wrap" style={{ gap: 'var(--space-4)', alignItems: 'flex-start' }}>
              <div className="field grow" style={{ minWidth: '12rem' }}>
                <label htmlFor="e-source">Source of attribution</label>
                <input id="e-source" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })}
                       placeholder="Exchange response ref. 2026/114, CryptoScamDB export, …" required />
              </div>
              <div className="field" style={{ minWidth: '9rem' }}>
                <label htmlFor="e-date">Source date</label>
                <input id="e-date" type="date" value={form.source_date} onChange={(e) => setForm({ ...form, source_date: e.target.value })} />
              </div>
              <div className="field" style={{ minWidth: '9rem' }}>
                <label htmlFor="e-conf">Confidence</label>
                <select id="e-conf" value={form.confidence} onChange={(e) => setForm({ ...form, confidence: e.target.value })}>
                  {TIERS.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
                </select>
              </div>
            </div>

            <div className="field">
              <label htmlFor="e-evidence">Evidence</label>
              <textarea id="e-evidence" value={form.evidence} onChange={(e) => setForm({ ...form, evidence: e.target.value })}
                        placeholder="How this address was attributed. Be specific — this text appears in generated reports." />
            </div>

            <button className="btn btn-primary" type="submit">Save attribution</button>
          </form>
        </div>
      )}

      <div className="panel">
        <div className="panel-head">
          <h2>Known addresses</h2>
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by name or address"
                 style={{ width: '16rem' }} aria-label="Filter known addresses" />
        </div>
        <div className="panel-body-flush">
          {shown.length === 0 ? (
            <Empty title={entities.length === 0 ? 'The intelligence database is nearly empty' : 'Nothing matches that filter'}>
              {entities.length === 0
                ? 'Load a feed into backend/app/entity_intel/seed_data/known_addresses.json, or record attributions here as your cases confirm them.'
                : 'Try a different name or address fragment.'}
            </Empty>
          ) : (
            <table className="table">
              <thead>
                <tr><th>Entity</th><th>Type</th><th>Chain</th><th>Address</th><th>Source</th><th>Confidence</th></tr>
              </thead>
              <tbody>
                {shown.map((e) => (
                  <tr key={e.id}>
                    <td style={{ fontWeight: 600 }}>{e.name}</td>
                    <td className="secondary">{humanize(e.entity_type)}</td>
                    <td className="secondary">{humanize(e.chain)}</td>
                    <td><Address value={e.address} short /></td>
                    <td className="tiny muted">{e.source}{e.source_date ? ` · ${e.source_date}` : ''}</td>
                    <td><Chip tone={`tier-${e.confidence}`}>{e.confidence}</Chip></td>
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
