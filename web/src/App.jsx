import { useState, useEffect, useCallback } from 'react'
import { LayoutDashboard, List, TrendingUp, Users, RefreshCw, CheckSquare, LogOut, Moon, Sun, RotateCcw } from 'lucide-react'
import { getCreds, clearCreds, isAdmin } from './auth'
import { getFollowed, saveFollowed } from './prefs'
import { triggerScrape, triggerGrade, fetchPicks, fetchGuestExperts } from './api'
import { PicksHubIcon } from './Logo'
import LoginPage from './LoginPage'
import DashboardPage from './DashboardPage'
import FeedPage from './FeedPage'
import TrackerPage from './TrackerPage'
import ExpertPage from './ExpertPage'

// All tabs — guests only see dashboard + tracker
const ALL_TABS = [
  { id: 'dashboard', label: 'Dashboard', Icon: LayoutDashboard, guestAllowed: true },
  { id: 'feed',      label: 'Feed',      Icon: List,            guestAllowed: false },
  { id: 'tracker',   label: 'Tracker',   Icon: TrendingUp,      guestAllowed: true },
  { id: 'experts',   label: 'Experts',   Icon: Users,           guestAllowed: false },
]

function useTheme() {
  const [dark, setDark] = useState(() =>
    window.matchMedia('(prefers-color-scheme: dark)').matches
  )
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
  }, [dark])
  return [dark, setDark]
}

export default function App() {
  const [creds,       setCreds]         = useState(getCreds)
  const [tab,         setTab]           = useState('dashboard')
  const [picks,       setPicks]         = useState([])
  const [followed,    setFollowedState] = useState(getFollowed)
  const [scraping,    setScraping]      = useState(false)
  const [grading,     setGrading]       = useState(false)
  const [reloading,   setReloading]     = useState(false)
  const [wsConnected, setWsConnected]   = useState(false)
  const [toast,       setToast]         = useState(null)
  const [dark,        setDark]          = useTheme()

  const admin = isAdmin(creds)
  const tabs  = ALL_TABS.filter(t => admin || t.guestAllowed)

  // If current tab is not visible for this role, reset to dashboard
  useEffect(() => {
    if (!tabs.find(t => t.id === tab)) setTab('dashboard')
  }, [creds]) // eslint-disable-line

  const setFollowed = useCallback((list) => {
    const next = typeof list === 'function' ? list(followed) : list
    saveFollowed(next)
    setFollowedState(next)
  }, [followed])

  const showToast = useCallback((msg, type = 'info') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }, [])

  const loadPicks = useCallback(async () => {
    if (!creds) return
    try { setPicks(await fetchPicks(creds)) }
    catch (err) { showToast(err.message, 'error') }
  }, [creds, showToast])

  useEffect(() => { loadPicks() }, [loadPicks])

  // Guests: always load expert list from server (admin-configured), not localStorage
  useEffect(() => {
    if (!creds || admin) return
    fetchGuestExperts(creds)
      .then(({ experts }) => { if (experts?.length) setFollowedState(experts) })
      .catch(() => {})
  }, [creds, admin])

  // WebSocket auto-refresh
  useEffect(() => {
    if (!creds) return
    // Derive WS URL from the stored backend URL (works both locally via proxy and on Vercel)
    const base = creds.serverURL || ''
    const isLocal = !base || base.includes('localhost') || base.includes('127.0.0.1')
    const wsBase = isLocal
      ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`
      : base.replace(/^http/, 'ws')
    const wsUrl = `${wsBase}/ws?token=${encodeURIComponent(creds.token || '')}`
    let ws, reconnectTimer

    function connect() {
      ws = new WebSocket(wsUrl)
      ws.onopen = () => setWsConnected(true)
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data)
          if (msg.type === 'scrape_done' || msg.type === 'pick_batch') { loadPicks() }
          if (msg.type === 'scrape_started') { setScraping(true) }
          if (msg.type === 'scrape_done')    { setScraping(false) }
        } catch {}
      }
      ws.onclose = () => {
        setWsConnected(false)
        reconnectTimer = setTimeout(connect, 5000)
      }
    }
    connect()
    return () => { clearTimeout(reconnectTimer); ws?.close() }
  }, [creds, loadPicks])

  const handleLogout = () => { clearCreds(); setCreds(null); setPicks([]) }

  const handleReload = useCallback(async () => {
    setReloading(true)
    await loadPicks()
    showToast('Picks refreshed', 'success')
    setReloading(false)
  }, [loadPicks, showToast])

  const handleScrape = async () => {
    setScraping(true)
    try {
      await triggerScrape(creds)
      showToast('Scrape started — picks will update automatically', 'info')
    } catch (err) { showToast(err.message, 'error') }
  }

  const handleGrade = async () => {
    setGrading(true)
    try {
      await triggerGrade(creds)
      showToast('Auto-grader started', 'success')
      setTimeout(loadPicks, 12000)
    } catch (err) { showToast(err.message, 'error') }
    setGrading(false)
  }

  if (!creds) return <LoginPage onLogin={setCreds} />

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-[#0a0f1e] flex flex-col">

      {/* Toast */}
      {toast && (
        <div className={`fixed top-4 left-1/2 -translate-x-1/2 z-50 px-5 py-2.5 rounded-full text-sm font-semibold text-white shadow-xl flex items-center gap-2 transition-all ${
          toast.type === 'error'   ? 'bg-red-500 shadow-red-500/30' :
          toast.type === 'success' ? 'bg-emerald-500 shadow-emerald-500/30' :
                                     'bg-indigo-600 shadow-indigo-500/30'
        }`}>
          {toast.type === 'success' && (
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          )}
          {toast.msg}
        </div>
      )}

      {/* Header */}
      <header className="bg-white dark:bg-[#0d1424] border-b border-gray-200 dark:border-gray-800/80 sticky top-0 z-40 shadow-sm dark:shadow-black/20">
        <div className="max-w-6xl mx-auto px-4 flex items-center justify-between h-14">

          {/* Brand */}
          <div className="flex items-center gap-2.5">
            <PicksHubIcon size={30} />
            <span className="font-extrabold text-lg tracking-tight text-gray-900 dark:text-white hidden sm:block">
              Picks<span className="text-indigo-500">Hub</span>
            </span>

            {/* Live / WS status */}
            <div className="flex items-center gap-1.5 ml-1">
              {scraping ? (
                <span className="flex items-center gap-1 text-[10px] font-semibold text-indigo-500 bg-indigo-50 dark:bg-indigo-950/50 px-2 py-0.5 rounded-full border border-indigo-200 dark:border-indigo-800">
                  <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse" />
                  Live
                </span>
              ) : wsConnected ? (
                <span className="w-2 h-2 rounded-full bg-emerald-400" title="Connected" />
              ) : (
                <span className="w-2 h-2 rounded-full bg-gray-300 dark:bg-gray-600" title="Disconnected" />
              )}

              {/* Guest badge */}
              {!admin && (
                <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-50 dark:bg-amber-950/40 text-amber-600 dark:text-amber-400 border border-amber-200 dark:border-amber-800">
                  Guest
                </span>
              )}
            </div>
          </div>

          {/* Controls */}
          <div className="flex items-center gap-1">
            {/* Theme toggle */}
            <button onClick={() => setDark(d => !d)}
              className="p-2 rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
              {dark ? <Sun size={15} /> : <Moon size={15} />}
            </button>

            {/* Reload picks */}
            <button onClick={handleReload} disabled={reloading} title="Reload picks"
              className="p-2 rounded-lg text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-950/40 transition-colors disabled:opacity-40">
              <RotateCcw size={15} className={reloading ? 'animate-spin' : ''} />
            </button>

            {/* Admin-only controls */}
            {admin && (
              <>
                <button onClick={handleGrade} disabled={grading}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all disabled:opacity-50"
                  style={{ background: grading ? '#d1fae5' : '#ecfdf5', color: '#059669' }}>
                  <CheckSquare size={13} className={grading ? 'animate-pulse' : ''} />
                  <span className="hidden sm:inline">{grading ? 'Grading…' : 'Grade'}</span>
                </button>

                <button onClick={handleScrape} disabled={scraping}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white transition-all disabled:opacity-50"
                  style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)', boxShadow: scraping ? 'none' : '0 2px 8px rgba(99,102,241,0.35)' }}>
                  <RefreshCw size={13} className={scraping ? 'animate-spin' : ''} />
                  <span className="hidden sm:inline">{scraping ? 'Scraping…' : 'Scrape'}</span>
                </button>
              </>
            )}

            {/* Logout */}
            <button onClick={handleLogout} title="Sign out"
              className="p-2 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/40 transition-colors ml-1">
              <LogOut size={15} />
            </button>
          </div>
        </div>

        {/* Tabs — filtered by role */}
        <div className="max-w-6xl mx-auto px-4 flex overflow-x-auto">
          {tabs.map(({ id, label, Icon }) => (
            <button key={id} onClick={() => setTab(id)}
              className={`relative flex items-center gap-1.5 px-4 py-2.5 text-sm font-semibold transition-colors whitespace-nowrap border-b-2 ${
                tab === id
                  ? 'text-indigo-600 dark:text-indigo-400 border-indigo-500'
                  : 'text-gray-500 dark:text-gray-400 border-transparent hover:text-gray-800 dark:hover:text-gray-200'
              }`}>
              <Icon size={14} />
              {label}
              {id === 'feed' && picks.length > 0 && (
                <span className="text-[9px] font-bold bg-indigo-100 dark:bg-indigo-900/60 text-indigo-600 dark:text-indigo-400 px-1.5 py-0.5 rounded-full">
                  {picks.length}
                </span>
              )}
            </button>
          ))}
        </div>
      </header>

      {/* Page content */}
      <main className="flex-1 max-w-6xl w-full mx-auto px-4 py-6">
        {tab === 'dashboard' && <DashboardPage picks={picks} creds={creds} followed={followed} />}
        {tab === 'feed'      && admin && <FeedPage   picks={picks} setPicks={setPicks} creds={creds} />}
        {tab === 'tracker'   && <TrackerPage creds={creds} picks={picks} followed={followed} admin={admin} />}
        {tab === 'experts'   && admin && <ExpertPage picks={picks} setPicks={setPicks} creds={creds} followed={followed} setFollowed={setFollowed} />}
      </main>
    </div>
  )
}
