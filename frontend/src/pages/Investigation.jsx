import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import GraphCanvas from '../components/GraphCanvas'
import {
  Address,
  Chip,
  Empty,
  Metric,
  PatternList,
  RiskPanel,
  Timeline,
  VaspCandidates,
  formatTime,
  humanize,
} from '../components/Evidence'

const TABS = [
  { id: 'graph', label: 'Fund flow' },
  { id: 'candidates', label: 'VASP candidates' },
  { id: 'patterns', label: 'Patterns' },
  { id: 'timeline', label: 'Timeline' },
  { id: 'copilot', label: 'Copilot' },
]

export default function Investigation() {
  const { investigationId } = useParams()
  const [inv, setInv] = useState(null)
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('graph')
  const [selectedNode, setSelectedNode] = useState(null)
  const [downloading, setDownloading] = useState(false)

  const load = useCallback(() => {
    api.getInvestigation(investigationId).then(setInv).catch((err) => setError(err.message))
  }, [investigationId])

  useEffect(load, [load])

  useEffect(() => {
    if (!inv || (inv.status !== 'queued' && inv.status !== 'running')) return undefined
    const timer = setInterval(load, 2500)
    return () => clearInterval(timer)
  }, [inv, load])

  if (error) return <div className="notice notice-error">{error}</div>
  if (!inv) return <div className="empty"><span className="spinner" /> Loading trace…</div>

  const summary = inv.summary || {}
  const candidates = inv.vasp_candidates?.candidates || []
  const patterns = inv.patterns?.hits || []
  const timeline = inv.timeline?.events || []
  const crossChain = inv.cross_chain?.events || []

  if (inv.status === 'queued' || inv.status === 'running') {
    return (
      <div>
        <div className="page-head">
          <h1>Tracing wallet</h1>
          <p>
            <Address value={inv.address} short /> on {humanize(inv.chain)}
          </p>
        </div>
        <div className="panel">
          <div className="panel-body">
            <div className="row" style={{ gap: 'var(--space-3)' }}>
              <span className="spinner" />
              <div>
                <div style={{ fontWeight: 600 }}>Collecting and analysing transactions</div>
                <div className="small muted">
                  Fetching the wallet&rsquo;s history, expanding {inv.max_hops} hop
                  {inv.max_hops === 1 ? '' : 's'} of counterparties, then clustering and pattern-matching.
                  This page updates itself when the trace finishes.
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (inv.status === 'failed') {
    return (
      <div>
        <div className="page-head">
          <h1>Trace failed</h1>
        </div>
        <div className="notice notice-error">
          {summary.error || 'The trace did not complete.'}
        </div>
        <p className="small muted" style={{ marginTop: 'var(--space-4)' }}>
          Common causes: the blockchain API key is missing or rate-limited, the address does not exist on the
          selected chain, or the network was unreachable. Check <code>GET /api/health</code> to see what is
          configured.
        </p>
      </div>
    )
  }

  return (
    <div>
      <div className="page-head">
        <div className="row-between wrap">
          <div>
            <h1>Wallet trace</h1>
            <div className="row wrap" style={{ gap: 'var(--space-3)', marginTop: 'var(--space-2)' }}>
              <Address value={inv.address} />
              <Chip>{humanize(inv.chain)}</Chip>
              <Chip>{inv.max_hops} hop{inv.max_hops === 1 ? '' : 's'}</Chip>
              {inv.risk_result && <Chip tone={`risk-${inv.risk_result.risk_band}`}>{inv.risk_result.risk_band} risk</Chip>}
            </div>
          </div>
          <div className="row">
            <Link to={`/cases/${inv.case_id}`} className="btn btn-quiet">
              Back to case
            </Link>
            <button
              className="btn"
              disabled={downloading}
              onClick={async () => {
                setDownloading(true)
                try {
                  await api.downloadReport(investigationId, 'json')
                } finally {
                  setDownloading(false)
                }
              }}
            >
              Export JSON
            </button>
            <button
              className="btn btn-primary"
              disabled={downloading}
              onClick={async () => {
                setDownloading(true)
                try {
                  await api.downloadReport(investigationId, 'pdf')
                } finally {
                  setDownloading(false)
                }
              }}
            >
              {downloading && <span className="spinner" />}
              Download report
            </button>
          </div>
        </div>
      </div>

      <div className="metric-grid" style={{ marginBottom: 'var(--space-5)' }}>
        <Metric label="Balance" value={fmtNum(summary.balance)} />
        <Metric label="Transactions" value={summary.total_transactions} hint={`${summary.incoming_transactions ?? 0} in · ${summary.outgoing_transactions ?? 0} out`} />
        <Metric label="Counterparties" value={summary.counterparty_count} />
        <Metric label="Assets" value={(summary.assets_used || []).length} hint={(summary.assets_used || []).slice(0, 3).join(', ')} />
        <Metric label="First activity" value={summary.first_activity ? formatTime(summary.first_activity).split(',')[0] : '—'} />
        <Metric label="Last activity" value={summary.last_activity ? formatTime(summary.last_activity).split(',')[0] : '—'} />
        <Metric label="Graph size" value={`${summary.nodes_traced ?? 0} / ${summary.edges_traced ?? 0}`} hint="wallets / flows" />
        <Metric label="VASP candidates" value={candidates.length} />
      </div>

      <div className="workspace">
        <div>
          <div className="tabs" role="tablist">
            {TABS.map((t) => (
              <button
                key={t.id}
                className={`tab${tab === t.id ? ' active' : ''}`}
                onClick={() => setTab(t.id)}
                role="tab"
                aria-selected={tab === t.id}
              >
                {t.label}
                {t.id === 'candidates' && candidates.length > 0 && ` (${candidates.length})`}
                {t.id === 'patterns' && patterns.length > 0 && ` (${patterns.length})`}
              </button>
            ))}
          </div>

          {tab === 'graph' && (
            <div className="panel">
              <div className="panel-body">
                <GraphCanvas graph={summary.graph} focusAddress={inv.address} onSelectNode={setSelectedNode} />
                {selectedNode && (
                  <div className="notice" style={{ marginTop: 'var(--space-4)' }}>
                    <div className="row-between wrap" style={{ marginBottom: 'var(--space-2)' }}>
                      <strong className="small">{selectedNode.entityName || 'Wallet'}</strong>
                      {selectedNode.entityType && <Chip>{humanize(selectedNode.entityType)}</Chip>}
                    </div>
                    <Address value={selectedNode.id} />
                  </div>
                )}
              </div>
            </div>
          )}

          {tab === 'candidates' && (
            <div className="panel">
              <div className="panel-head">
                <h2>VASP candidates</h2>
                <span className="tiny muted">ranked by evidence strength</span>
              </div>
              <div className="panel-body-flush">
                <VaspCandidates candidates={candidates} caveat={inv.vasp_candidates?.caveat} />
              </div>
            </div>
          )}

          {tab === 'patterns' && (
            <div className="panel">
              <div className="panel-head">
                <h2>Detected patterns</h2>
                <span className="tiny muted">each with its research basis</span>
              </div>
              <div className="panel-body-flush">
                <PatternList patterns={patterns} />
              </div>
            </div>
          )}

          {tab === 'timeline' && (
            <div className="panel">
              <div className="panel-head">
                <h2>Investigation timeline</h2>
                <span className="tiny muted">{timeline.length} events</span>
              </div>
              <div className="panel-body">
                <Timeline events={timeline} />
              </div>
            </div>
          )}

          {tab === 'copilot' && <Copilot investigationId={investigationId} existingSummary={inv.copilot_summary} />}
        </div>

        <div className="stack" style={{ gap: 'var(--space-5)' }}>
          <RiskPanel risk={inv.risk_result} />

          {crossChain.length > 0 && (
            <div className="panel">
              <div className="panel-head">
                <h2>Cross-chain movement</h2>
              </div>
              <div className="panel-body-flush">
                {crossChain.map((c, i) => (
                  <div className="evidence-item" key={i}>
                    <div className="evidence-title">{c.bridge_name}</div>
                    <p className="evidence-body">
                      {c.amount} {c.asset} · destination chain {c.destination_chain}
                    </p>
                    <p className="tiny muted" style={{ margin: 0 }}>{c.note}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {summary.known_labels?.length > 0 && (
            <div className="panel">
              <div className="panel-head">
                <h2>Known labels</h2>
              </div>
              <div className="panel-body-flush">
                {summary.known_labels.map((l) => (
                  <div className="evidence-item" key={l.address}>
                    <div className="row-between">
                      <span className="evidence-title">{l.name}</span>
                      <Chip tone={`tier-${l.confidence}`}>{l.confidence}</Chip>
                    </div>
                    <div style={{ marginTop: 'var(--space-2)' }}>
                      <Address value={l.address} short />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {summary.related_wallets?.length > 0 && (
            <div className="panel">
              <div className="panel-head">
                <h2>Related wallets</h2>
                <span className="tiny muted">{summary.related_wallets.length}</span>
              </div>
              <div className="panel-body" style={{ maxHeight: '18rem', overflowY: 'auto' }}>
                <div className="stack" style={{ gap: 'var(--space-2)' }}>
                  {summary.related_wallets.slice(0, 40).map((w) => (
                    <Address key={w} value={w} short />
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Copilot({ investigationId, existingSummary }) {
  const [available, setAvailable] = useState(null)
  const [summary, setSummary] = useState(existingSummary || null)
  const [answer, setAnswer] = useState(null)
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState(null)

  useEffect(() => {
    api.copilotStatus().then((s) => setAvailable(s.available)).catch(() => setAvailable(false))
  }, [])

  if (available === false) {
    return (
      <div className="panel">
        <div className="panel-body">
          <Empty title="Copilot is not configured">
            Set <code>ANTHROPIC_API_KEY</code> in <code>backend/.env</code> to have the copilot draft case-note
            summaries from this trace&rsquo;s findings. Every other feature works without it.
          </Empty>
        </div>
      </div>
    )
  }

  async function runSummary() {
    setBusy(true)
    setNotice(null)
    try {
      const result = await api.summarize(investigationId)
      if (result.available) setSummary(result.summary)
      else setNotice(result.reason)
    } catch (err) {
      setNotice(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function runAsk(e) {
    e.preventDefault()
    if (!question.trim()) return
    setBusy(true)
    setNotice(null)
    try {
      const result = await api.ask(investigationId, question.trim())
      if (result.available) setAnswer(result.answer)
      else setNotice(result.reason)
    } catch (err) {
      setNotice(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Copilot</h2>
        <span className="tiny muted">works only from this trace&rsquo;s findings</span>
      </div>
      <div className="panel-body">
        <p className="small secondary">
          The copilot can only see what the pipeline already produced — the wallet summary, patterns, candidates
          and their evidence. It has no independent chain access, so it cannot introduce a fact that is not in the
          evidence record.
        </p>

        {notice && <div className="notice notice-warn" style={{ marginBottom: 'var(--space-4)' }}>{notice}</div>}

        <button className="btn btn-primary" onClick={runSummary} disabled={busy}>
          {busy && <span className="spinner" />}
          {summary ? 'Regenerate summary' : 'Draft case-note summary'}
        </button>

        {summary && (
          <div className="copilot-output" style={{ marginTop: 'var(--space-4)' }}>
            {summary}
          </div>
        )}

        <hr className="divider" />

        <form onSubmit={runAsk}>
          <div className="field">
            <label htmlFor="question">Ask about this trace</label>
            <input
              id="question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Which candidate has the strongest evidence, and what would confirm it?"
            />
          </div>
          <button className="btn" type="submit" disabled={busy || !question.trim()}>
            Ask
          </button>
        </form>

        {answer && <div className="copilot-output" style={{ marginTop: 'var(--space-4)' }}>{answer}</div>}
      </div>
    </div>
  )
}

function fmtNum(value) {
  if (value == null) return '—'
  const num = Number(value)
  if (Number.isNaN(num)) return String(value)
  return num.toLocaleString(undefined, { maximumFractionDigits: 6 })
}
