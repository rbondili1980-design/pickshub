import { useState, useMemo, useCallback, useEffect } from 'react'
import { ChevronLeft, Trophy, TrendingUp, Target, Clock, Zap, Star, Users } from 'lucide-react'
import { gradePick, toggleHidden, fetchTracker, saveGuestExperts } from './api'

// ── Shared helpers ────────────────────────────────────────────────────────────

const SPORT_CLS = {
  MLB: 'bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300',
  NBA: 'bg-orange-100 text-orange-700 dark:bg-orange-900/50 dark:text-orange-300',
  NHL: 'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300',
  NFL: 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300',
  CBB: 'bg-purple-100 text-purple-700 dark:bg-purple-900/50 dark:text-purple-300',
  CFB: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/50 dark:text-yellow-300',
}

const RESULT_CLS = {
  win:     'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300',
  loss:    'bg-red-100 text-red-600 dark:bg-red-900/50 dark:text-red-400',
  push:    'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400',
  void:    'bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500',
  pending: 'bg-yellow-50 text-yellow-600 dark:bg-yellow-950/50 dark:text-yellow-400',
}
const RESULT_LABEL = { win: 'W', loss: 'L', push: 'P', void: '—', pending: '?' }

const TYPE_CLS = {
  spread:    'bg-violet-100 text-violet-700',
  total:     'bg-sky-100 text-sky-700',
  moneyline: 'bg-amber-100 text-amber-700',
  props:     'bg-pink-100 text-pink-700',
  parlay:    'bg-emerald-100 text-emerald-700',
}
const TYPE_LABEL = { total: 'Total', spread: 'Spread', moneyline: 'ML', props: 'Prop', parlay: 'Parlay' }

const SOURCE_CLS = {
  winible:        'bg-purple-100 text-purple-700',
  action_network: 'bg-blue-100 text-blue-700',
}

function fmtDate(s) {
  if (!s) return '—'
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString([], { month: 'short', day: 'numeric' })
}

// ── Grade buttons ─────────────────────────────────────────────────────────────

function GradeButtons({ pick, creds, onChange }) {
  const [busy, setBusy] = useState(false)
  const result = pick.result || 'pending'

  const grade = async (r) => {
    if (busy) return
    setBusy(true)
    try {
      await gradePick(creds, pick.id, r)
      onChange(pick.id, { result: r })
    } catch {}
    setBusy(false)
  }

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${RESULT_CLS[result]}`}>
        {RESULT_LABEL[result]}
      </span>
      <div className="flex gap-0.5">
        {[
          { r: 'win',  label: 'W', cls: 'hover:bg-green-100 hover:text-green-700' },
          { r: 'loss', label: 'L', cls: 'hover:bg-red-100 hover:text-red-600' },
          { r: 'push', label: 'P', cls: 'hover:bg-gray-200 hover:text-gray-700' },
          { r: 'void', label: '✕', cls: 'hover:bg-slate-200 hover:text-slate-500' },
        ].map(({ r, label, cls }) => (
          <button key={r} disabled={busy || pick.result === r} onClick={() => grade(r)}
            className={`text-[10px] font-bold px-2 py-0.5 rounded transition-colors disabled:opacity-40 ${
              pick.result === r ? RESULT_CLS[r] : `bg-gray-100 dark:bg-gray-800 text-gray-500 ${cls}`
            }`}>
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Expert card (grid view) ───────────────────────────────────────────────────

function ExpertCard({ e, pickCount, onSelect, isFollowed, onToggleFollow }) {
  const hasStat = e && e.graded > 0

  const sports = e ? Object.keys(e.by_sport).filter(s => {
    const sp = e.by_sport[s]
    return (sp.wins + sp.losses + sp.pushes + sp.pending) > 0
  }) : []

  const streakLabel = e && e.streak > 0
    ? `${e.streak_type === 'win' ? '🔥' : '❄️'} ${e.streak}`
    : null

  return (
    <div className={`relative bg-white dark:bg-gray-900 rounded-2xl border-2 transition-all ${
      isFollowed
        ? 'border-indigo-400 dark:border-indigo-600 shadow-md shadow-indigo-100 dark:shadow-indigo-950/30'
        : 'border-gray-200 dark:border-gray-800'
    }`}>

      {/* Follow toggle */}
      <button
        onClick={e2 => { e2.stopPropagation(); onToggleFollow() }}
        title={isFollowed ? 'Unfollow expert' : 'Follow expert'}
        className={`absolute top-3 right-3 p-1.5 rounded-full transition-all ${
          isFollowed
            ? 'text-indigo-500 bg-indigo-50 dark:bg-indigo-950/50 hover:bg-indigo-100'
            : 'text-gray-300 hover:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-950/30'
        }`}>
        <Star size={14} fill={isFollowed ? 'currentColor' : 'none'} />
      </button>

      {/* Clickable body → drill in */}
      <button onClick={onSelect} className="text-left w-full p-4 group">
        {/* Name */}
        <div className="flex items-start gap-2 mb-3 pr-7">
          <p className={`text-sm font-bold leading-tight transition-colors ${
            isFollowed ? 'text-indigo-600 dark:text-indigo-400' : 'text-gray-900 dark:text-white group-hover:text-indigo-600 dark:group-hover:text-indigo-400'
          }`}>
            {e ? e.expert : 'Unknown'}
          </p>
          {streakLabel && <span className="text-xs font-semibold shrink-0 ml-auto">{streakLabel}</span>}
        </div>

        {/* Stats */}
        {hasStat ? (
          <div className="grid grid-cols-3 gap-1 mb-3">
            <div className="text-center">
              <p className={`text-base font-extrabold ${e.win_rate >= 55 ? 'text-green-600' : e.win_rate >= 50 ? 'text-emerald-600' : 'text-red-500'}`}>
                {e.win_rate}%
              </p>
              <p className="text-[9px] text-gray-400 uppercase">Win</p>
            </div>
            <div className="text-center">
              <p className={`text-base font-extrabold font-mono ${e.net_units >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                {e.net_units >= 0 ? '+' : ''}{e.net_units}u
              </p>
              <p className="text-[9px] text-gray-400 uppercase">Units</p>
            </div>
            <div className="text-center">
              <p className="text-base font-extrabold text-gray-700 dark:text-gray-300">{e.record}</p>
              <p className="text-[9px] text-gray-400 uppercase">Record</p>
            </div>
          </div>
        ) : (
          <p className="text-xs text-gray-400 mb-3">No graded picks yet</p>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between">
          <div className="flex gap-1 flex-wrap">
            {sports.slice(0, 4).map(s => (
              <span key={s} className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${SPORT_CLS[s] || 'bg-gray-100 text-gray-500'}`}>{s}</span>
            ))}
          </div>
          <span className="text-[10px] text-gray-400">{pickCount} picks</span>
        </div>
      </button>
    </div>
  )
}

// ── Expert detail view ────────────────────────────────────────────────────────

function ExpertDetail({ expertName, picks, trackerData, creds, onChange, onBack }) {
  const [resultFilter, setResultFilter] = useState('')
  const [sportFilter,  setSportFilter]  = useState('')

  const expertPicks = useMemo(() =>
    picks
      .filter(p => p.expert === expertName)
      .sort((a, b) => {
        const d = (b.posted_at || '').localeCompare(a.posted_at || '')
        return d !== 0 ? d : b.id - a.id
      }),
    [picks, expertName]
  )

  const e = trackerData?.experts?.find(x => x.expert === expertName)

  const filtered = useMemo(() => {
    return expertPicks
      .filter(p => !resultFilter || (p.result || 'pending') === resultFilter)
      .filter(p => !sportFilter  || p.sport === sportFilter)
  }, [expertPicks, resultFilter, sportFilter])

  const sports = useMemo(() => [...new Set(expertPicks.map(p => p.sport).filter(Boolean))].sort(), [expertPicks])

  const hasStat = e && e.graded > 0

  const sel = 'text-xs border border-gray-200 dark:border-gray-700 rounded-lg px-2.5 py-1.5 bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500'

  return (
    <div className="flex flex-col gap-5">

      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={onBack}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors">
          <ChevronLeft size={16} /> All Experts
        </button>
        <span className="text-gray-300 dark:text-gray-700">|</span>
        <h1 className="text-lg font-bold text-gray-900 dark:text-white">{expertName}</h1>
        {e?.record && (
          <span className="text-xs font-mono text-gray-500">{e.record}</span>
        )}
      </div>

      {/* Stat cards */}
      {hasStat && (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
          {[
            { icon: Trophy,    label: 'Record',     value: e.record,                         cls: 'text-gray-900 dark:text-white' },
            { icon: TrendingUp, label: 'Win Rate',   value: `${e.win_rate}%`,                cls: e.win_rate >= 55 ? 'text-green-600' : e.win_rate >= 50 ? 'text-emerald-600' : 'text-red-500' },
            { icon: Target,    label: 'Net Units',   value: `${e.net_units >= 0 ? '+' : ''}${e.net_units}u`, cls: e.net_units >= 0 ? 'text-green-600' : 'text-red-500' },
            { icon: Zap,       label: 'ROI',         value: `${e.roi >= 0 ? '+' : ''}${e.roi}%`,            cls: e.roi >= 0 ? 'text-green-600' : 'text-red-500' },
            { icon: Clock,     label: 'Pending',     value: e.pending,                        cls: 'text-yellow-500' },
            { icon: Target,    label: 'Total Picks', value: e.total,                          cls: 'text-gray-700 dark:text-gray-300' },
          ].map(({ icon: Icon, label, value, cls }) => (
            <div key={label} className="bg-white dark:bg-gray-900 rounded-xl border border-gray-100 dark:border-gray-800 p-3 text-center">
              <p className={`text-xl font-extrabold font-mono ${cls}`}>{value}</p>
              <p className="text-[9px] text-gray-400 uppercase tracking-wide mt-0.5">{label}</p>
            </div>
          ))}
        </div>
      )}

      {/* Sport breakdown */}
      {hasStat && Object.keys(e.by_sport).length > 0 && (
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-100 dark:border-gray-800 p-4">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">By Sport</p>
          <div className="flex flex-wrap gap-3">
            {Object.entries(e.by_sport).filter(([, s]) => s.wins + s.losses + s.pushes + s.pending > 0).map(([sport, s]) => (
              <div key={sport} className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3 text-center min-w-[80px]">
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${SPORT_CLS[sport] || 'bg-gray-100 text-gray-500'}`}>{sport}</span>
                <p className="text-sm font-bold text-gray-900 dark:text-white mt-1.5">{s.wins}-{s.losses}{s.pushes > 0 ? `-${s.pushes}` : ''}</p>
                {s.pending > 0 && <p className="text-[9px] text-yellow-500">{s.pending} pending</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Filters + picks */}
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          <p className="text-xs font-semibold text-gray-500">{filtered.length} picks</p>
          <select value={resultFilter} onChange={e => setResultFilter(e.target.value)} className={sel}>
            <option value="">All results</option>
            {['pending','win','loss','push','void'].map(r => (
              <option key={r} value={r}>{r.charAt(0).toUpperCase()+r.slice(1)}</option>
            ))}
          </select>
          {sports.length > 1 && (
            <select value={sportFilter} onChange={e => setSportFilter(e.target.value)} className={sel}>
              <option value="">All sports</option>
              {sports.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          )}
          {(resultFilter || sportFilter) && (
            <button onClick={() => { setResultFilter(''); setSportFilter('') }}
              className="text-xs text-gray-400 hover:text-red-500 transition-colors">✕ Clear</button>
          )}
        </div>

        <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-x-auto">
          <table className="w-full text-sm min-w-[640px]">
            <thead>
              <tr className="border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/50">
                {['Date','Pick','Game','Sport','Type','Odds','Units','Grade'].map(h => (
                  <th key={h} className="text-left text-xs font-semibold text-gray-400 uppercase tracking-wide px-4 py-3 whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr><td colSpan={8} className="px-4 py-12 text-center text-sm text-gray-400">No picks match filters</td></tr>
              ) : filtered.map(p => (
                <tr key={p.id} className="border-b border-gray-50 dark:border-gray-800/40 last:border-0 hover:bg-indigo-50/30 dark:hover:bg-indigo-950/10 transition-colors">
                  <td className="px-4 py-3 whitespace-nowrap text-xs text-gray-500">{fmtDate(p.posted_at)}</td>
                  <td className="px-4 py-3 max-w-[200px]">
                    <p className="text-xs font-semibold text-gray-900 dark:text-white line-clamp-2 leading-snug">{p.pick}</p>
                    {p.comment && <p className="text-[10px] text-gray-400 mt-0.5 line-clamp-1">{p.comment}</p>}
                    <span className={`inline-block text-[9px] font-bold px-1.5 py-0.5 rounded mt-1 ${SOURCE_CLS[p.source] || 'bg-gray-100 text-gray-500'}`}>
                      {p.source === 'action_network' ? 'AN' : 'WIN'}
                    </span>
                  </td>
                  <td className="px-4 py-3 max-w-[140px]">
                    <p className="text-xs text-gray-500 truncate">{p.game || '—'}</p>
                  </td>
                  <td className="px-4 py-3">
                    {p.sport
                      ? <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${SPORT_CLS[p.sport] || 'bg-gray-100 text-gray-500'}`}>{p.sport}</span>
                      : <span className="text-xs text-gray-300">—</span>}
                  </td>
                  <td className="px-4 py-3">
                    {p.pick_type
                      ? <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${TYPE_CLS[p.pick_type] || 'bg-gray-100 text-gray-500'}`}>{TYPE_LABEL[p.pick_type] || p.pick_type}</span>
                      : <span className="text-xs text-gray-300">—</span>}
                  </td>
                  <td className="px-4 py-3">
                    {p.odds
                      ? <span className={`font-mono text-xs font-bold px-2 py-0.5 rounded-full ${parseFloat(p.odds) > 0 ? 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300' : 'bg-red-100 text-red-600 dark:bg-red-900/50 dark:text-red-400'}`}>{p.odds}</span>
                      : <span className="text-xs text-gray-300">—</span>}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">{p.units || '—'}</td>
                  <td className="px-4 py-3">
                    <GradeButtons pick={p} creds={creds} onChange={onChange} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ExpertPage({ picks, setPicks, creds, followed, setFollowed }) {
  const [selected, setSelected] = useState(null)
  const [tracker,  setTracker]  = useState(null)
  const [showOnlyFollowed, setShowOnlyFollowed] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [publishMsg, setPublishMsg] = useState(null)

  useEffect(() => {
    fetchTracker(creds).then(setTracker).catch(() => {})
  }, [picks, creds])

  const experts = useMemo(() => {
    const countByExpert = {}
    picks.forEach(p => {
      if (p.expert) countByExpert[p.expert] = (countByExpert[p.expert] || 0) + 1
    })

    const trackerMap = {}
    if (tracker?.experts) {
      tracker.experts.forEach(e => { trackerMap[e.expert] = e })
    }

    const names = new Set([...Object.keys(countByExpert), ...Object.keys(trackerMap)])
    return [...names]
      .map(name => ({
        name,
        pickCount: countByExpert[name] || 0,
        stats: trackerMap[name] || null,
      }))
      .sort((a, b) => {
        // Followed experts always first, then by pick count
        const aF = followed.includes(a.name) ? 1 : 0
        const bF = followed.includes(b.name) ? 1 : 0
        if (bF !== aF) return bF - aF
        return b.pickCount - a.pickCount
      })
  }, [picks, tracker, followed])

  const displayedExperts = useMemo(() =>
    showOnlyFollowed ? experts.filter(e => followed.includes(e.name)) : experts,
    [experts, showOnlyFollowed, followed]
  )

  const onChange = useCallback((id, patch) => {
    setPicks(prev => prev.map(p => p.id === id ? { ...p, ...patch } : p))
  }, [setPicks])

  const toggleFollow = useCallback((name) => {
    setFollowed(prev => {
      const set = new Set(prev)
      if (set.has(name)) set.delete(name)
      else set.add(name)
      return [...set]
    })
  }, [setFollowed])

  if (selected) {
    return (
      <ExpertDetail
        expertName={selected}
        picks={picks}
        trackerData={tracker}
        creds={creds}
        onChange={onChange}
        onBack={() => setSelected(null)}
      />
    )
  }

  const followedCount = followed.length

  return (
    <div className="flex flex-col gap-5">

      {/* Header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-lg font-bold text-gray-900 dark:text-white">Experts</h1>
          <p className="text-xs text-gray-400 mt-0.5">
            {displayedExperts.length} expert{displayedExperts.length !== 1 ? 's' : ''} · ☆ to follow · click name to drill in
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {followedCount > 0 && (
            <button onClick={() => setShowOnlyFollowed(v => !v)}
              className={`flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-full border transition-all ${
                showOnlyFollowed
                  ? 'bg-indigo-600 text-white border-indigo-600'
                  : 'bg-white dark:bg-gray-900 text-indigo-600 dark:text-indigo-400 border-indigo-300 dark:border-indigo-700 hover:bg-indigo-50 dark:hover:bg-indigo-950/30'
              }`}>
              <Star size={11} fill={showOnlyFollowed ? 'currentColor' : 'none'} />
              {showOnlyFollowed ? `Following (${followedCount})` : `${followedCount} followed`}
            </button>
          )}
          {followedCount > 0 && (
            <button
              disabled={publishing}
              onClick={async () => {
                setPublishing(true)
                setPublishMsg(null)
                try {
                  await saveGuestExperts(creds, followed)
                  setPublishMsg({ ok: true, text: `Published ${followed.length} experts to guests` })
                } catch {
                  setPublishMsg({ ok: false, text: 'Failed to publish' })
                } finally {
                  setPublishing(false)
                  setTimeout(() => setPublishMsg(null), 3000)
                }
              }}
              className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-full border transition-all bg-white dark:bg-gray-900 text-emerald-600 dark:text-emerald-400 border-emerald-300 dark:border-emerald-700 hover:bg-emerald-50 dark:hover:bg-emerald-950/30 disabled:opacity-50">
              <Users size={11} />
              {publishing ? 'Publishing…' : 'Publish to guests'}
            </button>
          )}
          {publishMsg && (
            <span className={`text-xs font-medium ${publishMsg.ok ? 'text-emerald-600' : 'text-red-500'}`}>
              {publishMsg.text}
            </span>
          )}
        </div>
      </div>

      {/* Followed callout when none selected */}
      {followedCount === 0 && (
        <div className="bg-indigo-50 dark:bg-indigo-950/30 border border-indigo-200 dark:border-indigo-800 rounded-xl p-3 flex items-center gap-3">
          <Star size={16} className="text-indigo-400 shrink-0" />
          <p className="text-xs text-indigo-700 dark:text-indigo-300">
            Click <Star size={10} className="inline mx-0.5" /> on any expert card to follow them — followed experts filter your Dashboard.
          </p>
        </div>
      )}

      {displayedExperts.length === 0 ? (
        <div className="rounded-2xl border-2 border-dashed border-gray-200 dark:border-gray-800 py-24 text-center text-gray-400">
          <p className="text-4xl mb-3">👥</p>
          <p className="font-semibold">No experts yet — scrape picks first</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {displayedExperts.map(({ name, pickCount, stats }) => (
            <ExpertCard
              key={name}
              e={stats}
              pickCount={pickCount}
              isFollowed={followed.includes(name)}
              onSelect={() => setSelected(name)}
              onToggleFollow={() => toggleFollow(name)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
