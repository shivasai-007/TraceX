/**
 * Thin API client. Holds the session token, attaches it to every request,
 * and turns a non-2xx response into an Error carrying the backend's own
 * message -- the backend writes user-facing error text (see the FastAPI
 * routes), so the UI shows that rather than inventing its own wording.
 */

const BASE = import.meta.env.VITE_API_BASE_URL || ''
const TOKEN_KEY = 'tracex.token'
const USER_KEY = 'tracex.user'

export const session = {
  get token() {
    return localStorage.getItem(TOKEN_KEY)
  },
  get user() {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? JSON.parse(raw) : null
  },
  save(token, user) {
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  },
  clear() {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  },
}

async function request(path, { method = 'GET', body, raw = false } = {}) {
  const headers = {}
  if (body) headers['Content-Type'] = 'application/json'
  if (session.token) headers.Authorization = `Bearer ${session.token}`

  const response = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })

  if (response.status === 401) {
    session.clear()
    window.location.hash = '#/login'
    throw new Error('Your session has ended. Sign in again.')
  }

  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const data = await response.json()
      if (data.detail) message = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch {
      /* response had no JSON body; keep the status message */
    }
    throw new Error(message)
  }

  if (raw) return response
  if (response.status === 204) return null
  return response.json()
}

export const api = {
  health: () => request('/api/health'),

  login: (email, password) => request('/api/auth/login', { method: 'POST', body: { email, password } }),
  register: (payload) => request('/api/auth/register', { method: 'POST', body: payload }),
  me: () => request('/api/auth/me'),

  listCases: () => request('/api/cases'),
  createCase: (payload) => request('/api/cases', { method: 'POST', body: payload }),
  getCase: (id) => request(`/api/cases/${id}`),
  setCaseStatus: (id, status) => request(`/api/cases/${id}/status?new_status=${status}`, { method: 'PATCH' }),
  addNote: (id, bodyText) => request(`/api/cases/${id}/notes`, { method: 'POST', body: { body: bodyText } }),
  acknowledgeAlert: (caseId, alertId) =>
    request(`/api/cases/${caseId}/alerts/${alertId}/acknowledge`, { method: 'POST' }),

  chains: () => request('/api/wallets/chains'),
  investigate: (caseId, payload) => request(`/api/wallets/${caseId}/investigate`, { method: 'POST', body: payload }),
  getInvestigation: (id) => request(`/api/wallets/investigations/${id}`),

  listEntities: (chain) => request(`/api/entities${chain ? `?chain=${chain}` : ''}`),
  createEntity: (payload) => request('/api/entities', { method: 'POST', body: payload }),

  mlStatus: () => request('/api/ml/status'),
  reloadModel: () => request('/api/ml/reload', { method: 'POST' }),

  copilotStatus: () => request('/api/copilot/status'),
  summarize: (id) => request(`/api/copilot/${id}/summarize`, { method: 'POST' }),
  ask: (id, question) => request(`/api/copilot/${id}/ask`, { method: 'POST', body: { question } }),

  reportJson: (id) => request(`/api/reports/${id}/json`),
  reportPdfUrl: (id) => `${BASE}/api/reports/${id}/pdf`,

  /** PDF download needs the auth header, so fetch as a blob rather than
   *  navigating the browser to the URL (which would send no token). */
  async downloadReport(id, kind = 'pdf') {
    const path = kind === 'pdf' ? `/api/reports/${id}/pdf` : `/api/reports/${id}/download.json`
    const response = await request(path, { raw: true })
    const blob = await response.blob()
    const disposition = response.headers.get('Content-Disposition') || ''
    const match = disposition.match(/filename="?([^"]+)"?/)
    const filename = match ? match[1] : `tracex-report.${kind}`
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  },
}
