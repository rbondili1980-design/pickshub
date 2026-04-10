import { authHeader } from './auth'

// When running via Vite proxy the serverURL portion is stripped —
// calls go to /api/... which Vite proxies to localhost:8000.
// When a custom serverURL is stored we prepend it directly (for non-proxied use).
function url(creds, path) {
  const base = creds?.serverURL || ''
  // In dev mode rely on Vite proxy for localhost — in production always use full URL
  if (import.meta.env.DEV && (!base || base.includes('localhost') || base.includes('127.0.0.1'))) return path
  return base ? `${base}${path}` : path
}

async function request(creds, path, options = {}) {
  const res = await fetch(url(creds, path), {
    ...options,
    headers: { ...authHeader(creds), ...(options.headers || {}) },
  })
  if (res.status === 401) {
    // Token expired — clear and force re-login
    const { clearCreds } = await import('./auth')
    clearCreds()
    window.location.reload()
    throw new Error('Session expired — please log in again')
  }
  if (!res.ok) throw new Error(`Server error ${res.status}`)
  return res.json()
}

export async function loginRequest(serverURL, username, password) {
  const base = serverURL.replace(/\/$/, '')
  const res = await fetch(`${base}/api/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (res.status === 429) throw new Error('Too many attempts — try again in 15 minutes')
  if (!res.ok) throw new Error('Invalid username or password')
  return res.json()  // { token, role, username }
}

// ── Picks ──────────────────────────────────────────────────────────────────────
export const fetchPicks = (creds) =>
  request(creds, '/api/picks?admin=true').then(d => Array.isArray(d) ? d : (d.picks ?? []))

// ── Stats ──────────────────────────────────────────────────────────────────────
export const fetchStats = (creds) => request(creds, '/api/stats/summary')

// ── Tracker ───────────────────────────────────────────────────────────────────
export const fetchTracker = (creds, sport = '') =>
  request(creds, sport ? `/api/tracker?sport=${encodeURIComponent(sport)}` : '/api/tracker')

// ── Splits ────────────────────────────────────────────────────────────────────
export const fetchSplits = (creds, date) => request(creds, `/api/splits?date=${date}`)

// ── Mutations ─────────────────────────────────────────────────────────────────
export const gradePick = (creds, id, result) =>
  request(creds, `/api/picks/${id}/result`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ result }),
  })

export const toggleHidden = (creds, id, hidden) =>
  request(creds, `/api/picks/${id}/hidden`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ hidden }),
  })

export const triggerScrape = (creds) =>
  request(creds, '/api/scrape?source=all', { method: 'POST' })

export const triggerGrade = (creds) =>
  request(creds, '/api/grade', { method: 'POST' })

export const fetchMe = (creds) => request(creds, '/api/me')

export const testConnection = (creds) => request(creds, '/api/stats/summary')

export const fetchGuestExperts = (creds) =>
  request(creds, '/api/config/guest-experts')

export const saveGuestExperts = (creds, experts) =>
  request(creds, '/api/config/guest-experts', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ experts }),
  })
