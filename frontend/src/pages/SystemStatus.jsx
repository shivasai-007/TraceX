import { useEffect, useState } from 'react'
import { api } from '../api/client'

/**
 * What is actually wired up. An investigator needs to know whether a risk
 * score came from a trained model or from rules alone before they rely on
 * it, so that state is shown plainly rather than hidden in a config file.
 */
export default function SystemStatus() {
  const [health, setHealth] = useState(null)
  const [ml, setMl] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)

  const load = () => {
    api.health().then(setHealth).catch(() => {})
    api.mlStatus().then(setMl).catch(() => {})
  }

  useEffect(load, [])

  async function reload() {
    setBusy(true)
    try {
      const result = await api.reloadModel()
      setMessage(result.message)
      load()
    } finally {
      setBusy(false)
    }
  }

  const rows = health
    ? [
        ['Blockchain data (Etherscan key)', health.etherscan_key_configured, 'Required for Ethereum and Polygon traces.'],
        ['Risk model trained', health.risk_model_loaded, 'Without it, risk is scored from rules and threat intelligence only.'],
        ['Background workers (Redis)', health.workers_enabled, 'Optional. Traces run inline in the API process when off.'],
        ['AI copilot', health.copilot_enabled, 'Optional. Drafts case-note summaries from trace findings.'],
        ['Graph store', health.graph_backend === 'neo4j', `Currently ${health.graph_backend}. Neo4j adds durable cross-case graph queries.`],
      ]
    : []

  return (
    <div>
      <div className="page-head">
        <h1>System status</h1>
        <p>Which capabilities are live on this deployment, and which still need configuring.</p>
      </div>

      {message && <div className="notice" style={{ marginBottom: 'var(--space-4)' }}>{message}</div>}

      <div className="panel" style={{ marginBottom: 'var(--space-5)' }}>
        <div className="panel-head"><h2>Capabilities</h2></div>
        <div className="panel-body-flush">
          {!health ? (
            <div className="empty"><span className="spinner" /> Checking…</div>
          ) : (
            <table className="table">
              <tbody>
                {rows.map(([label, on, hint]) => (
                  <tr key={label}>
                    <td style={{ width: '1rem' }}><span className={`status-dot ${on ? 'on' : 'off'}`} /></td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{label}</div>
                      <div className="tiny muted">{hint}</div>
                    </td>
                    <td className="secondary small" style={{ textAlign: 'right' }}>{on ? 'Configured' : 'Not configured'}</td>
                  </tr>
                ))}
                <tr>
                  <td />
                  <td>
                    <div style={{ fontWeight: 600 }}>Chains available</div>
                    <div className="tiny muted">Chains with a working data adapter.</div>
                  </td>
                  <td className="secondary small" style={{ textAlign: 'right' }}>{(health.chains_live || []).join(', ')}</td>
                </tr>
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Risk model</h2>
          <button className="btn btn-sm" onClick={reload} disabled={busy}>
            {busy && <span className="spinner" />}Reload model
          </button>
        </div>
        <div className="panel-body">
          {!ml ? (
            <div className="empty"><span className="spinner" /> Checking…</div>
          ) : !ml.available ? (
            <>
              <div className="notice notice-warn">{ml.note}</div>
              <p className="small secondary" style={{ marginTop: 'var(--space-4)' }}>
                Training instructions are in <code>ml/MODEL_TRAINING.md</code>, and the dataset download links are
                in <code>ml/DATASET.md</code>. After training, use Reload model above — no restart needed.
              </p>
              <p className="tiny muted">Expected model path: <span className="mono">{ml.model_path}</span></p>
            </>
          ) : (
            <>
              <div className="metric-grid">
                <div className="metric">
                  <div className="metric-label">Algorithm</div>
                  <div className="metric-value">{ml.metadata?.algorithm}</div>
                </div>
                <div className="metric">
                  <div className="metric-label">Dataset</div>
                  <div className="metric-value">{ml.metadata?.dataset}</div>
                </div>
                <div className="metric">
                  <div className="metric-label">PR-AUC</div>
                  <div className="metric-value">{ml.metadata?.metrics?.pr_auc ?? '—'}</div>
                </div>
                <div className="metric">
                  <div className="metric-label">Recall (illicit)</div>
                  <div className="metric-value">{ml.metadata?.metrics?.recall_illicit ?? '—'}</div>
                </div>
                <div className="metric">
                  <div className="metric-label">Precision (illicit)</div>
                  <div className="metric-value">{ml.metadata?.metrics?.precision_illicit ?? '—'}</div>
                </div>
                <div className="metric">
                  <div className="metric-label">Training rows</div>
                  <div className="metric-value">{ml.metadata?.training_rows?.toLocaleString?.() ?? '—'}</div>
                </div>
              </div>
              <p className="tiny muted" style={{ marginTop: 'var(--space-4)' }}>
                Trained {ml.metadata?.trained_at?.slice(0, 19).replace('T', ' ')} UTC using a {ml.metadata?.split} split.
                Feature coverage {ml.metadata?.feature_coverage?.mapped}/{ml.metadata?.feature_coverage?.total}.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
