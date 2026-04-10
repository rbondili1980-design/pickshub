const KEY = 'pickshub_creds'

export function getCreds() {
  try {
    const creds = JSON.parse(localStorage.getItem(KEY) || 'null')
    if (!creds?.token) return null
    // Check JWT expiry client-side — clear if expired
    const payload = JSON.parse(atob(creds.token.split('.')[1]))
    if (payload.exp * 1000 < Date.now()) {
      localStorage.removeItem(KEY)
      return null
    }
    return creds
  } catch {
    return null
  }
}

export function saveCreds(serverURL, username, role, token) {
  localStorage.setItem(KEY, JSON.stringify({
    serverURL: serverURL.replace(/\/$/, ''),
    username,
    role,
    token,
  }))
}

export function clearCreds() {
  localStorage.removeItem(KEY)
}

export function authHeader(creds) {
  if (!creds?.token) return {}
  return { Authorization: `Bearer ${creds.token}` }
}

export function isAdmin(creds) {
  return creds?.role === 'admin'
}
