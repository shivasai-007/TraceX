/**
 * Shared presentational pieces for the investigation workspace.
 *
 * The rule these all follow: never show a conclusion without the evidence
 * next to it. A risk score shows its components; a VASP candidate shows the
 * evidence lines that produced it; a pattern shows its research reference.
 */

export function Chip({ children, tone }) {
  return <span className={`chip${tone ? ` chip-${tone}` : ''}`}>{children}</span>
}

export function Address({ value, short = false }) {
  if (!value) return <span className="muted">—</span>
  const text = short && value.length > 20 ? `${value.slice(0, 10)}…${value.slice(-8)}` : value
  return (
    <span
      className="addr"
      title={`${value} — click to copy`}
      onClick={() => navigator.clipboard?.writeText(value)}
      style={{ cursor: 'copy' }}
    >
      {text}
    </span>
  )
}

export function Metric({ label, value, hint }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value ?? '—'}</div>
      {hint && <div className="tiny muted">{hint}</div>}
    </div>
  )
}

export function Empty({ title, children }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children}
    </div>
  )
}

/* ------------------------------------------------------------------ risk */

export function RiskPanel({ risk }) {
  if (!risk) return <Empty title="No risk assessment yet">Run a trace to score this wallet.</Empty>

  const { risk_score: score, risk_band: band, components, indicators, methodology_note: note } = risk
  const pct = Math.round((score ?? 0) * 100)

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Risk assessment</h2>
        <Chip tone={`risk-${band}`}>{band}</Chip>
      </div>
      <div className="panel-body">
        <div className="risk-meter">
          <div className="row-between" style={{ marginBottom: 'var(--space-2)' }}>
            <span className="small secondary">Fused score</span>
            <span style={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{score?.toFixed(2)}</span>
          </div>
          <div className="risk-track">
            <div className="risk-fill" style={{ width: `${pct}%`, background: `var(--risk-${band})` }} />
          </div>
        </div>

        <h3 style={{ margin: 'var(--space-5) 0 var(--space-2)' }}>What this score is made of</h3>
        <div>
          <ComponentRow
            label="Rule indicators"
            detail={`${components?.rules?.indicator_count ?? 0} triggered`}
            score={components?.rules?.score}
            weight={components?.rules?.weight}
          />
          <ComponentRow
            label="Threat intelligence"
            detail={`${components?.threat_intel?.hits?.length ?? 0} known-address hits`}
            score={components?.threat_intel?.score}
            weight={components?.threat_intel?.weight}
          />
          <ComponentRow
            label="ML behavioural model"
            detail={components?.ml?.available ? components.ml.algorithm : 'not trained yet'}
            score={components?.ml?.score}
            weight={components?.ml?.weight}
          />
        </div>

        {!components?.ml?.available && components?.ml?.note && (
          <div className="notice notice-warn" style={{ marginTop: 'var(--space-4)' }}>
            {components.ml.note}
          </div>
        )}

        {note && <p className="tiny muted" style={{ marginTop: 'var(--space-4)' }}>{note}</p>}

        {indicators?.length > 0 && (
          <>
            <h3 style={{ margin: 'var(--space-5) 0 var(--space-2)' }}>Indicators</h3>
            <div className="stack" style={{ gap: 'var(--space-2)' }}>
              {indicators.map((ind, i) => (
                <div key={`${ind.indicator}-${i}`} style={{ borderLeft: `2px solid var(--risk-${severityBand(ind.severity)})`, paddingLeft: 'var(--space-3)' }}>
                  <div className="row-between">
                    <span className="small" style={{ fontWeight: 600 }}>{humanize(ind.indicator)}</span>
                    <Chip tone={`risk-${severityBand(ind.severity)}`}>{ind.severity}</Chip>
                  </div>
                  <p className="tiny muted" style={{ margin: '0.15rem 0 0' }}>{ind.evidence}</p>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function ComponentRow({ label, detail, score, weight }) {
  return (
    <div className="component-row">
      <div>
        <div>{label}</div>
        <div className="tiny muted">{detail}</div>
      </div>
      <span className="component-weight">weight {weight != null ? weight.toFixed(2) : '—'}</span>
      <span className="component-score">{score != null ? Number(score).toFixed(2) : '—'}</span>
    </div>
  )
}

/* -------------------------------------------------------------- patterns */

export function PatternList({ patterns }) {
  if (!patterns?.length) {
    return (
      <Empty title="No patterns matched">
        The rule engine found no laundering or structuring signatures in the collected transactions. That is a
        result, not a gap — it narrows what needs explaining.
      </Empty>
    )
  }

  return (
    <div>
      {patterns.map((p, i) => (
        <div className="evidence-item" key={`${p.pattern}-${i}`}>
          <div className="evidence-head">
            <span className="evidence-title">{humanize(p.pattern)}</span>
            <div className="row" style={{ gap: 'var(--space-2)' }}>
              <Chip tone={`tier-${p.confidence}`}>{p.confidence}</Chip>
              <Chip tone={`risk-${severityBand(p.severity)}`}>{p.severity}</Chip>
            </div>
          </div>
          <p className="evidence-body">{p.explanation}</p>
          <p className="evidence-body" style={{ color: 'var(--ink-muted)' }}>{p.evidence}</p>
          {p.tx_hashes?.length > 0 && (
            <div className="tiny muted">
              {p.tx_hashes.length} transaction{p.tx_hashes.length === 1 ? '' : 's'} involved
            </div>
          )}
          {p.research_reference && <div className="evidence-ref">{p.research_reference}</div>}
        </div>
      ))}
    </div>
  )
}

/* -------------------------------------------------------- VASP candidates */

export function VaspCandidates({ candidates, caveat }) {
  if (!candidates?.length) {
    return (
      <Empty title="No VASP candidates generated">
        The trace did not reach any address in the intelligence database, and no exchange-like deposit cluster met
        the evidence threshold. This does not rule out exchange involvement — it means this trace found no evidence
        for it.
      </Empty>
    )
  }

  return (
    <div>
      {candidates.map((c) => (
        <div className="evidence-item" key={c.address}>
          <div className="evidence-head">
            <div>
              <div className="evidence-title">{c.name}</div>
              <div className="tiny muted">{humanize(c.entity_type)}</div>
            </div>
            <Chip tone={`tier-${c.confidence}`}>{c.confidence}</Chip>
          </div>

          <div className="row wrap small secondary" style={{ gap: 'var(--space-4)', margin: 'var(--space-2) 0' }}>
            <span>{c.exposure} exposure</span>
            <span>{c.hops != null ? `${c.hops} hop${c.hops === 1 ? '' : 's'}` : 'hops unknown'}</span>
            <span>{c.supporting_transactions} supporting tx</span>
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>{c.amount_transferred} transferred</span>
          </div>

          <Address value={c.address} short />

          {c.last_interaction && (
            <div className="tiny muted" style={{ marginTop: 'var(--space-2)' }}>
              Last interaction {formatTime(c.last_interaction)}
            </div>
          )}

          {c.supporting_wallet_cluster?.length > 0 && (
            <div className="tiny muted" style={{ marginTop: 'var(--space-1)' }}>
              Supported by a cluster of {c.supporting_wallet_cluster.length} wallet
              {c.supporting_wallet_cluster.length === 1 ? '' : 's'}
            </div>
          )}

          <ul className="evidence-list">
            {c.evidence?.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </div>
      ))}
      {caveat && (
        <div className="evidence-item">
          <div className="notice notice-warn">{caveat}</div>
        </div>
      )}
    </div>
  )
}

/* -------------------------------------------------------------- timeline */

export function Timeline({ events }) {
  if (!events?.length) return <Empty title="No timeline yet">Events appear once a trace completes.</Empty>

  return (
    <ul className="timeline">
      {events.slice(0, 120).map((e, i) => (
        <li key={i} className={e.type === 'suspicious_event' ? 'event-suspicious' : e.type === 'cross_chain_exit' ? 'event-cross-chain' : ''}>
          <div className="timeline-time">{e.timestamp ? formatTime(e.timestamp) : 'no timestamp'}</div>
          <div className="secondary">{e.description}</div>
        </li>
      ))}
      {events.length > 120 && (
        <li>
          <span className="tiny muted">{events.length - 120} further events — see the full report.</span>
        </li>
      )}
    </ul>
  )
}

/* ---------------------------------------------------------------- alerts */

export function AlertList({ alerts, onAcknowledge }) {
  if (!alerts?.length) return <Empty title="No alerts">Alerts are raised when a trace hits a VASP, mixer or bridge.</Empty>

  return (
    <div>
      {alerts.map((a) => (
        <div className={`alert-item${a.acknowledged ? ' acknowledged' : ''}`} key={a.id}>
          <div className={`alert-bar severity-${a.severity}`} />
          <div className="grow">
            <div>{a.message}</div>
            <div className="tiny muted">
              {humanize(a.alert_type)} · {formatTime(a.created_at)}
            </div>
          </div>
          {!a.acknowledged && onAcknowledge && (
            <button className="btn btn-sm btn-quiet" onClick={() => onAcknowledge(a.id)}>
              Acknowledge
            </button>
          )}
        </div>
      ))}
    </div>
  )
}

/* --------------------------------------------------------------- helpers */

export function humanize(value) {
  if (!value) return ''
  return String(value).replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}

export function severityBand(severity) {
  return ['minimal', 'low', 'medium', 'high', 'critical'].includes(severity) ? severity : 'low'
}

export function formatTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 19).replace('T', ' ')
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
