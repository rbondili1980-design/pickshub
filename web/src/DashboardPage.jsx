import { useState, useEffect, useMemo } from 'react'
import { Target, Layers, Users, TrendingUp, Star } from 'lucide-react'
import { fetchStats } from './api'

const SPORT_COLOR = {
  MLB: '#ef4444', NBA: '#f97316', NHL: '#3b82f6',
  NFL: '#22c55e', CBB: '#a855f7', CFB: '#eab308', MLS: '#14b8a6',
}

const TYPE_LABEL = { total: 'Total (O/U)', spread: 'Spread', moneyline: 'Moneyline', props: 'Props', parlay: 'Parlay' }

function StatCard({ icon: Icon, label, value, color = 'indigo', sub }) {
  const colors = {
    indigo: 'bg-indigo-50 dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-400',
    blue:   'bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400',
    purple: 'bg-purple-50 dark:bg-purple-950/40 text-purple-600 dark:text-purple-400',
    teal:   'bg-teal-50 dark:bg-teal-950/40 text-teal-600 dark:text-teal-400',
  }
  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-5 flex items-start gap-4">
      <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 ${colors[color]}`}>
        <Icon size={18} />
      </div>
      <div>
        <p className="text-2xl font-bold text-gray-900 dark:text-white leading-none">{value}</p>
        <p className="text-xs text-gray-500 mt-1">{label}</p>
        {sub && <p className="text-[10px] text-gray-400 mt-0.5">{sub}</p>}
      </div>
    </div>
  )
}

function BarRow({ label, value, max, color = '#6366f1', right }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs font-semibold w-24 truncate text-gray-600 dark:text-gray-400 shrink-0">{label}</span>
      <div className="flex-1 bg-gray-100 dark:bg-gray-800 rounded-full h-2 overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${Math.max(4, (value / max) * 100)}%`, backgroundColor: color }} />
      </div>
      <span className="text-xs text-gray-500 shrink-0 w-16 text-right">{right}</span>
    </div>
  )
}

export default function DashboardPage({ picks, creds, followed }) {
  const [stats, setStats] = useState(null)

  const isFiltered = followed && followed.length > 0

  // Base picks — filtered to followed experts if any are selected
  const basePicks = useMemo(() =>
    isFiltered ? picks.filter(p => followed.includes(p.expert)) : picks,
    [picks, followed, isFiltered]
  )

  const today = new Date().toLocaleDateString('en-CA')
  const todayPicks = useMemo(() => basePicks.filter(p => p.posted_at === today), [basePicks, today])

  useEffect(() => {
    fetchStats(creds).then(setStats).catch(() => {})
  }, [picks, creds])

  // When filtered, compute stats from picks directly; otherwise use backend stats
  const totalPicks  = isFiltered ? basePicks.length : (stats?.total_picks ?? picks.length)
  const todayCount  = isFiltered ? todayPicks.length : (stats?.today_count ?? todayPicks.length)
  const expertCount = isFiltered ? followed.length : (stats?.experts ?? new Set(picks.map(p => p.expert).filter(Boolean)).size)

  const avgOdds = useMemo(() => {
    const src = todayPicks.filter(p => p.odds)
    if (!src.length) return '—'
    const avg = src.reduce((s, p) => s + parseFloat(p.odds), 0) / src.length
    return avg > 0 ? `+${Math.round(avg)}` : `${Math.round(avg)}`
  }, [todayPicks])

  // By sport
  const bySport = useMemo(() => {
    const map = {}
    basePicks.forEach(p => { if (p.sport) map[p.sport] = (map[p.sport] || 0) + 1 })
    const entries = Object.entries(map).sort((a, b) => b[1] - a[1])
    return entries.length ? entries : null
  }, [basePicks])

  // By type
  const byType = useMemo(() => {
    const map = {}
    basePicks.forEach(p => { if (p.pick_type) map[p.pick_type] = (map[p.pick_type] || 0) + 1 })
    const entries = Object.entries(map).sort((a, b) => b[1] - a[1])
    return entries.length ? entries : null
  }, [basePicks])

  // By expert — bets + wins (show followed or all)
  const byExpert = useMemo(() => {
    const expertList = isFiltered
      ? followed
      : [...new Set(picks.map(p => p.expert).filter(Boolean))]
    return expertList
      .map(name => {
        const ep = picks.filter(p => p.expert === name)
        const graded = ep.filter(p => p.result && p.result !== 'pending' && p.result !== 'void')
        const wins   = graded.filter(p => p.result === 'win').length
        const losses = graded.filter(p => p.result === 'loss').length
        const wr     = graded.length > 0 ? Math.round((wins / graded.length) * 100) : null
        return { name, total: ep.length, graded: graded.length, wins, losses, wr }
      })
      .filter(e => e.total > 0)
      .sort((a, b) => b.total - a.total)
  }, [picks, followed, isFiltered])

  const dateLabel = new Date().toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })

  return (
    <div className="flex flex-col gap-6">

      {/* Header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-white">{dateLabel}</h1>
          <p className="text-sm text-gray-400 mt-0.5">{todayPicks.length} picks today</p>
        </div>
        {isFiltered && (
          <div className="flex items-center gap-1.5 bg-indigo-50 dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-400 text-xs font-semibold px-3 py-1.5 rounded-full border border-indigo-200 dark:border-indigo-800">
            <Star size={11} fill="currentColor" />
            {followed.length} followed expert{followed.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard icon={Target}     label={isFiltered ? 'Picks (followed)' : 'Total picks'}     value={totalPicks}  color="indigo" />
        <StatCard icon={Layers}     label="Today's picks"                                        value={todayCount}  color="blue"   />
        <StatCard icon={Users}      label={isFiltered ? 'Following' : 'Experts tracked'}         value={expertCount} color="purple" />
        <StatCard icon={TrendingUp} label="Avg odds (today)"                                     value={avgOdds}     color="teal"   />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

        {/* By Sport */}
        <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-5">
          <h2 className="text-sm font-bold text-gray-900 dark:text-white mb-4">By Sport</h2>
          {bySport ? (
            <div className="flex flex-col gap-2.5">
              {bySport.map(([sport, count]) => (
                <BarRow key={sport} label={sport} value={count} max={bySport[0][1]}
                  color={SPORT_COLOR[sport] || '#6b7280'} right={`${count} picks`} />
              ))}
            </div>
          ) : <p className="text-xs text-gray-400">No data yet</p>}
        </div>

        {/* By Bet Type */}
        <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-5">
          <h2 className="text-sm font-bold text-gray-900 dark:text-white mb-4">By Bet Type</h2>
          {byType ? (
            <div className="flex flex-col gap-2.5">
              {byType.map(([type_, count]) => (
                <BarRow key={type_} label={TYPE_LABEL[type_] || type_} value={count} max={byType[0][1]}
                  color="#6366f1" right={`${count} picks`} />
              ))}
            </div>
          ) : <p className="text-xs text-gray-400">No data yet</p>}
        </div>
      </div>

      {/* By Expert — Bets & Wins */}
      {byExpert.length > 0 && (
        <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-5">
          <div className="flex items-center gap-2 mb-4">
            <h2 className="text-sm font-bold text-gray-900 dark:text-white">
              {isFiltered ? 'Followed Experts — Bets & Wins' : 'All Experts — Bets & Wins'}
            </h2>
            {!isFiltered && (
              <span className="text-[10px] text-gray-400 bg-gray-50 dark:bg-gray-800 px-2 py-0.5 rounded-full">
                follow experts in Experts tab to filter
              </span>
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px]">
              <thead>
                <tr className="border-b border-gray-100 dark:border-gray-800">
                  {['Expert', 'Bets', 'Graded', 'Wins', 'Losses', 'Win %', 'W/L Bar'].map(h => (
                    <th key={h} className="text-left text-[10px] font-semibold text-gray-400 uppercase tracking-wide pb-2.5 pr-4 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {byExpert.map(({ name, total, graded, wins, losses, wr }) => {
                  const barPct = graded > 0 ? Math.round((wins / graded) * 100) : 0
                  return (
                    <tr key={name} className="border-b border-gray-50 dark:border-gray-800/40 last:border-0 group">
                      <td className="py-3 pr-4">
                        <div className="flex items-center gap-1.5">
                          {isFiltered && <Star size={10} className="text-indigo-400 shrink-0" fill="currentColor" />}
                          <span className="text-xs font-semibold text-gray-900 dark:text-white">{name}</span>
                        </div>
                      </td>
                      <td className="py-3 pr-4 text-xs font-mono text-gray-600 dark:text-gray-400">{total}</td>
                      <td className="py-3 pr-4 text-xs font-mono text-gray-500">{graded}</td>
                      <td className="py-3 pr-4 text-xs font-bold font-mono text-green-600 dark:text-green-400">{wins}</td>
                      <td className="py-3 pr-4 text-xs font-bold font-mono text-red-500">{losses}</td>
                      <td className="py-3 pr-4">
                        {wr !== null
                          ? <span className={`text-xs font-bold ${wr >= 55 ? 'text-green-600' : wr >= 50 ? 'text-emerald-600' : 'text-red-500'}`}>
                              {wr}%
                            </span>
                          : <span className="text-xs text-gray-300">—</span>}
                      </td>
                      <td className="py-3 w-32">
                        {graded > 0 ? (
                          <div className="flex h-2 rounded-full overflow-hidden bg-gray-100 dark:bg-gray-800">
                            <div className="bg-green-500 h-full transition-all" style={{ width: `${barPct}%` }} title={`${wins} wins`} />
                            <div className="bg-red-400 h-full transition-all" style={{ width: `${100 - barPct}%` }} title={`${losses} losses`} />
                          </div>
                        ) : (
                          <div className="h-2 bg-gray-100 dark:bg-gray-800 rounded-full" />
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Today's picks */}
      {todayPicks.length > 0 && (
        <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-5">
          <h2 className="text-sm font-bold text-gray-900 dark:text-white mb-4">Today's Picks</h2>
          <div className="flex flex-col divide-y divide-gray-50 dark:divide-gray-800">
            {todayPicks.slice(0, 10).map(p => (
              <div key={p.id} className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
                {p.sport && <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: SPORT_COLOR[p.sport] || '#9ca3af' }} />}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-gray-900 dark:text-white truncate">{p.pick}</p>
                  <p className="text-xs text-gray-400 truncate">{p.expert}{p.game ? ` · ${p.game}` : ''}</p>
                </div>
                {p.odds && (
                  <span className={`font-mono text-xs font-bold px-2 py-0.5 rounded-full shrink-0 ${
                    parseFloat(p.odds) > 0 ? 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300' : 'bg-red-100 text-red-600 dark:bg-red-900/50 dark:text-red-400'
                  }`}>{p.odds}</span>
                )}
                <span className={`text-xs font-bold px-1.5 py-0.5 rounded-full shrink-0 ${
                  p.result === 'win'  ? 'bg-green-100 text-green-700' :
                  p.result === 'loss' ? 'bg-red-100 text-red-600' :
                  p.result === 'push' ? 'bg-gray-100 text-gray-500' :
                  'bg-yellow-50 text-yellow-600'
                }`}>
                  {p.result === 'win' ? 'W' : p.result === 'loss' ? 'L' : p.result === 'push' ? 'P' : '?'}
                </span>
              </div>
            ))}
            {todayPicks.length > 10 && (
              <p className="text-xs text-gray-400 text-center pt-3">+{todayPicks.length - 10} more — see Feed tab</p>
            )}
          </div>
        </div>
      )}

      {todayPicks.length === 0 && basePicks.length === 0 && (
        <div className="rounded-2xl border-2 border-dashed border-gray-200 dark:border-gray-800 py-24 text-center text-gray-400">
          <p className="text-4xl mb-3">{isFiltered ? '⭐' : '📡'}</p>
          <p className="font-semibold">
            {isFiltered
              ? `No picks from your ${followed.length} followed expert${followed.length !== 1 ? 's' : ''} yet`
              : 'No picks yet — hit Scrape to fetch'}
          </p>
          {isFiltered && <p className="text-sm mt-1 text-gray-400">Go to Experts tab to adjust who you follow</p>}
        </div>
      )}
    </div>
  )
}
