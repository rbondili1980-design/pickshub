import { useState } from 'react'
import { PicksHubIcon } from './Logo'

export default function LoginPage({ onLogin }) {
  // Local dev → localhost; everywhere else (Vercel, iPhone, etc.) → Fly.io cloud backend
  const defaultServer = (() => {
    const h = window.location.hostname
    return (h === 'localhost' || h === '127.0.0.1') ? 'http://localhost:8000' : 'https://pickshub-api.fly.dev'
  })()
  const [serverURL, setServerURL] = useState(defaultServer)
  const [username,  setUsername]  = useState('guest')
  const [password,  setPassword]  = useState('')
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState('')

  const canSubmit = serverURL && username && password && !loading

  const submit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const { loginRequest } = await import('./api')
      const { saveCreds }    = await import('./auth')
      const base = serverURL.replace(/\/$/, '')
      const { token, role, username: user } = await loginRequest(base, username, password)
      saveCreds(base, user, role, token)
      onLogin({ serverURL: base, username: user, role, token })
    } catch (err) {
      setError(err.message || 'Could not connect to server')
    }
    setLoading(false)
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 relative overflow-hidden"
      style={{ background: 'linear-gradient(135deg, #0f0c29 0%, #1a1040 40%, #24243e 100%)' }}>

      {/* Background orbs */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <div className="absolute -top-40 -left-40 w-80 h-80 rounded-full opacity-20"
          style={{ background: 'radial-gradient(circle, #6366f1, transparent)' }} />
        <div className="absolute -bottom-40 -right-40 w-96 h-96 rounded-full opacity-15"
          style={{ background: 'radial-gradient(circle, #8b5cf6, transparent)' }} />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full opacity-5"
          style={{ background: 'radial-gradient(circle, #a78bfa, transparent)' }} />
      </div>

      <div className="w-full max-w-sm relative z-10">

        {/* Logo */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center justify-center mb-5">
            <PicksHubIcon size={64} />
          </div>
          <h1 className="text-3xl font-extrabold text-white tracking-tight">
            Picks<span style={{ color: '#a78bfa' }}>Hub</span>
          </h1>
          <p className="text-sm mt-2" style={{ color: '#9ca3af' }}>
            Your personal picks dashboard
          </p>
        </div>

        {/* Card */}
        <div className="rounded-2xl border p-6 flex flex-col gap-5"
          style={{
            background: 'rgba(255,255,255,0.05)',
            borderColor: 'rgba(255,255,255,0.1)',
            backdropFilter: 'blur(20px)',
          }}>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider" style={{ color: '#9ca3af' }}>
              Server URL
            </label>
            <input
              type="url"
              value={serverURL}
              onChange={e => setServerURL(e.target.value)}
              placeholder="http://localhost:8000"
              className="px-3.5 py-3 rounded-xl text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-all"
              style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)' }}
              required
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider" style={{ color: '#9ca3af' }}>
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="admin"
              autoCapitalize="none"
              className="px-3.5 py-3 rounded-xl text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-all"
              style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)' }}
              required
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider" style={{ color: '#9ca3af' }}>
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="••••••••"
              className="px-3.5 py-3 rounded-xl text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-all"
              style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)' }}
              required
            />
          </div>

          {error && (
            <div className="flex items-center gap-2 text-sm rounded-xl px-3.5 py-3"
              style={{ background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.3)', color: '#fca5a5' }}>
              <svg className="w-4 h-4 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
              </svg>
              {error}
            </div>
          )}

          <button
            type="button"
            onClick={submit}
            disabled={!canSubmit}
            className="w-full py-3 rounded-xl text-sm font-bold text-white transition-all flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ background: canSubmit ? 'linear-gradient(135deg, #6366f1, #8b5cf6)' : '#4b5563', boxShadow: canSubmit ? '0 0 20px rgba(99,102,241,0.4)' : 'none' }}
          >
            {loading ? (
              <>
                <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                Connecting…
              </>
            ) : (
              <>
                Sign In
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13 7l5 5m0 0l-5 5m5-5H6" />
                </svg>
              </>
            )}
          </button>

          <p className="text-xs text-center" style={{ color: '#6b7280' }}>
            Credentials stored in browser only
          </p>
        </div>

        <p className="text-center text-xs mt-6" style={{ color: '#4b5563' }}>
          PicksHub · Personal Edition
        </p>
      </div>
    </div>
  )
}
