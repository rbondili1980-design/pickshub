import { useState, useEffect, useMemo } from 'react'
import { ChevronDown, ChevronRight, ArrowUpDown, Trophy } from 'lucide-react'
import { fetchTracker } from './api'

const RESULT_DOT = { win: 'bg-green-500', loss: 'bg-red-500', push: 'bg-gray-400', void: 'bg-slate-300', pending: 'bg-yellow-400' }

const SPORT_COLOR = {
  MLB: 'bg-red-500', NBA: 'bg-orange-500', NHL: 'bg-blue-500',
  NFL: 'bg-green-600', CBB: 'bg-purple-500', Other: 'bg-gray-400',
}

const SORT_COLS = [
  { key: 'expert',    label: 'Expert' },
  { key: 'graded',    label: 'Graded' },
  { key: 'win_rate',  label: 'Win %' },
  { key: 'net_units', label: 'Net Units' },
  { key: 'roi',       label: 'ROI' },
  { key: 'pending',   label: 'Pending' },
  { key: 'streak',    label: 'Streak' },
]

function SortTh({ col, label, sortKey, sortDir, onSort }) {
  const active = sortKey === col
  return (
    <th onClick={() => onSort(col)}
      className={`text-left text-xs font-semibold uppercase tracking-wide px-4 py-3 cursor-pointer select-none whitespace-nowrap hover:text-indigo-500 transition-colors ${active ? 'text-indigo-600 dark:text-indigo-400' : 'text-gray-400'}`}>
      <span className="flex items-center gap-1">
        {label}
        {active
          ? <span className="text-[10px]">{sortDir === 'asc' ? '↑' : '↓'}</span>
          : <ArrowUpDown size={10} className="opacity-30" />}
      </span>
    </th>
  )
}

function ExpertRow({ e, expanded, onToggle }) {
  const netPos = e.net_units >= 0
  return (
    <>
      <tr onClick={onToggle} className="border-b border-gray-50 dark:border-gray-800/40 hover:bg-indigo-50/30 dark:hover:bg-indigo-950/10 cursor-pointer transition-colors">
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            {expanded ? <ChevronDown size={13} className="text-gray-400 shrink-0" /> : <ChevronRight size={13} className="text-gray-400 shrink-0" />}
            <span className="text-sm font-semibold text-gray-900 dark:text-white">{e.expert}</span>
          </div>
        </td>
        <td className="px-4 py-3 text-xs text-gray-500">{e.total}</td>
        <td className="px-4 py-3 text-xs text-gray-500">{e.graded}</td>
        <td className="px-4 py-3"><span className="text-xs font-mono font-bold text-gray-700 dark:text-gray-300">{e.record}</span></td>
        <td className="px-4 py-3">
          {e.graded > 0
            ? <span className={`text-xs font-semibold ${e.win_rate >= 55 ? 'text-green-600' : e.win_rate >= 50 ? 'text-emerald-600' : 'text-red-500'}`}>{e.win_rate}%</span>
            : <span className="text-xs text-gray-300">—</span>}
        </td>
        <td className="px-4 py-3">
          {e.graded > 0
            ? <span className={`text-xs font-bold font-mono ${netPos ? 'text-green-600 dark:text-green-400' : 'text-red-500'}`}>{netPos ? '+' : ''}{e.net_units}u</span>
            : <span className="text-xs text-gray-300">—</span>}
        </td>
        <td className="px-4 py-3">
          {e.graded > 0
            ? <span className={`text-xs font-semibold ${e.roi >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500'}`}>{e.roi >= 0 ? '+' : ''}{e.roi}%</span>
            : <span className="text-xs text-gray-300">—</span>}
        </td>
        <td className="px-4 py-3"><span className="text-xs text-yellow-500 font-semibold">{e.pending}</span></td>
        <td className="px-4 py-3">
          {e.streak > 0
            ? <span className={`text-xs font-semibold ${e.streak_type === 'win' ? 'text-green-600 dark:text-green-400' : 'text-red-500'}`}>
                {e.streak_type === 'win' ? '▲' : '▼'}{e.streak}
              </span>
            : <span className="text-xs text-gray-300">—</span>}
        </td>
      </tr>

      {expanded && (
        <tr className="bg-gray-50 dark:bg-gray-800/30">
          <td colSpan={9} className="px-6 py-4">
            <div className="grid md:grid-cols-2 gap-6">
              {/* Sport breakdown */}
              <div>
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">By Sport</p>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(e.by_sport).map(([sport, s]) => {
                    const total = s.wins + s.losses + s.pushes + s.pending
                    if (!total) return null
                    return (
                      <div key={sport} className="bg-white dark:bg-gray-900 rounded-lg border border-gray-100 dark:border-gray-800 p-2.5 text-center min-w-[70px]">
                        <div className="flex items-center justify-center gap-1 mb-1">
                          <span className={`w-2 h-2 rounded-full ${SPORT_COLOR[sport] || SPORT_COLOR.Other}`} />
                          <span className="text-xs font-bold text-gray-700 dark:text-gray-300">{sport}</span>
                        </div>
                        <p className="text-sm font-bold text-gray-900 dark:text-white">{s.wins}-{s.losses}</p>
                        <p className="text-[10px] text-gray-400">{s.pending} pend</p>
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Recent picks */}
              <div>
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Last 10 Picks</p>
                <div className="flex flex-col gap-1.5">
                  {e.recent.map(p => (
                    <div key={p.id} className="flex items-center gap-2 text-xs">
                      <span className={`w-3 h-3 rounded-full shrink-0 ${RESULT_DOT[p.result] || RESULT_DOT.pending}`} />
                      <span className="text-gray-500 shrink-0">{p.posted_at || '—'}</span>
                      {p.sport && <span className={`text-white text-[9px] font-bold px-1 py-0.5 rounded shrink-0 ${SPORT_COLOR[p.sport] || SPORT_COLOR.Other}`}>{p.sport}</span>}
                      <span className="text-gray-700 dark:text-gray-300 truncate">{p.pick}</span>
                      {p.odds && <span className="font-mono text-gray-500 shrink-0">{p.odds}</span>}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

export default function TrackerPage({ creds, picks, followed = [], admin = false }) {
  const [data,     setData]     = useState(null)
  const [loading,  setLoading]  = useState(true)
  const [sortKey,  setSortKey]  = useState('graded')
  const [sortDir,  setSortDir]  = useState('desc')
  const [expanded, setExpanded] = useState(null)
  const [sport,    setSport]    = useState('')

  useEffect(() => {
    setLoading(true)
    fetchTracker(creds, sport)
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [picks, creds, sport])

  const allSports = useMemo(() => {
    if (!data?.experts) return []
    const s = new Set()
    data.experts.forEach(e => Object.keys(e.by_sport).forEach(sp => s.add(sp)))
    return [...s].sort()
  }, [data])

  const sorted = useMemo(() => {
    if (!data?.experts) return []
    const experts = (!admin && followed.length > 0)
      ? data.experts.filter(e => followed.includes(e.expert))
      : data.experts
    return [...experts].sort((a, b) => {
      const av = a[sortKey] ?? 0, bv = b[sortKey] ?? 0
      const cmp = typeof av === 'string' ? av.localeCompare(bv) : av - bv
      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [data, sortKey, sortDir])

  const onSort = (col) => {
    if (sortKey === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(col); setSortDir('desc') }
  }

  const overall = data?.overall

  const sel = 'text-xs border border-gray-200 dark:border-gray-700 rounded-lg px-2.5 py-1.5 bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500'

  if (loading) return (
    <div className="flex items-center justify-center py-20 text-gray-400">
      <div className="animate-spin w-5 h-5 border-2 border-indigo-500 border-t-transparent rounded-full mr-2" />
      Loading tracker…
    </div>
  )

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="font-bold text-gray-900 dark:text-white text-lg">Tracker</h1>
          <p className="text-xs text-gray-400">{sorted.length} expert{sorted.length !== 1 ? 's' : ''} · click a row to expand</p>
        </div>
        <select value={sport} onChange={e => setSport(e.target.value)} className={sel}>
          <option value="">All sports</option>
          {allSports.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {/* Overall */}
      {overall && overall.graded > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: 'Overall Record', value: `${overall.wins}-${overall.losses}-${overall.pushes}`, sub: `${overall.graded} graded` },
            { label: 'Win Rate', value: overall.graded > 0 ? `${overall.win_rate}%` : '—', cls: overall.win_rate >= 50 ? 'text-green-600 dark:text-green-400' : 'text-red-500' },
            { label: 'Pending', value: overall.pending, cls: 'text-yellow-500 dark:text-yellow-400' },
            { label: 'Total Picks', value: overall.total },
          ].map(c => (
            <div key={c.label} className="bg-white dark:bg-gray-900 rounded-xl border border-gray-100 dark:border-gray-800 p-3 text-center">
              <p className={`text-2xl font-extrabold ${c.cls || 'text-gray-900 dark:text-white'}`}>{c.value}</p>
              {c.sub && <p className="text-[10px] text-gray-400 mt-0.5">{c.sub}</p>}
              <p className="text-[10px] text-gray-400 uppercase tracking-wide mt-0.5">{c.label}</p>
            </div>
          ))}
        </div>
      )}

      {sorted.length === 0 ? (
        <div className="text-center py-20 text-gray-400">
          <Trophy size={32} className="mx-auto mb-3 opacity-30" />
          <p className="font-semibold">No data yet</p>
          <p className="text-sm mt-1">
            {!admin && followed.length === 0
              ? 'No experts followed — ask an admin to follow some experts for you'
              : 'Grade picks in the Feed to see results here'}
          </p>
        </div>
      ) : (
        <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-x-auto">
          <table className="w-full text-sm min-w-[700px]">
            <thead>
              <tr className="border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/50">
                <SortTh col="expert"    label="Expert"    sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                <th className="text-left text-xs font-semibold text-gray-400 uppercase tracking-wide px-4 py-3">Total</th>
                <SortTh col="graded"    label="Graded"    sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                <th className="text-left text-xs font-semibold text-gray-400 uppercase tracking-wide px-4 py-3">Record</th>
                <SortTh col="win_rate"  label="Win %"     sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                <SortTh col="net_units" label="Net Units" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                <SortTh col="roi"       label="ROI"       sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                <SortTh col="pending"   label="Pending"   sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                <SortTh col="streak"    label="Streak"    sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
              </tr>
            </thead>
            <tbody>
              {sorted.map(e => (
                <ExpertRow key={e.expert} e={e}
                  expanded={expanded === e.expert}
                  onToggle={() => setExpanded(x => x === e.expert ? null : e.expert)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
