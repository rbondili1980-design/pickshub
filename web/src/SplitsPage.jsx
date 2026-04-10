import { useState, useEffect, useMemo } from 'react'
import { RefreshCw, Filter, AlertCircle } from 'lucide-react'
import { fetchSplits } from './api'

const SPORT_COLOR = { MLB:'bg-red-500', NBA:'bg-orange-500', NHL:'bg-blue-500', NFL:'bg-green-500', CBB:'bg-purple-500', CFB:'bg-yellow-500', MLS:'bg-teal-500' }
const TYPE_BADGE  = { total:'bg-sky-100 text-sky-700 dark:bg-sky-900/50 dark:text-sky-300', spread:'bg-violet-100 text-violet-700 dark:bg-violet-900/50 dark:text-violet-300', moneyline:'bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300', props:'bg-pink-100 text-pink-700 dark:bg-pink-900/50 dark:text-pink-300', parlay:'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300' }
const TYPE_LABEL  = { total:'Total', spread:'Sprd', moneyline:'ML', props:'Prop', parlay:'Parlay' }

function localDate(offset = 0) {
  const d = new Date(Date.now() + offset * 86400000)
  return d.toLocaleDateString('en-CA')
}

function matchPicks(matchup, date, sport, picks) {
  if (!matchup || !picks.length) return []
  const ml = matchup.toLowerCase()
  const words = ml.split(/[\s\-\/\.@]+/).map(w => w.replace(/[^a-z]/g,'')).filter(w => w.length >= 3 && w !== 'vs' && w !== 'at')
  const seen = new Set()
  return picks.filter(p => {
    if (p.pick_type === 'parlay') return false
    if (date && p.posted_at !== date) return false
    if (p.sport && sport && p.sport !== sport) return false
    const hay = ((p.game && p.game !== '-') ? p.game : p.pick || '').toLowerCase()
    if (!hay) return false
    const hit = words.some(w => hay.includes(w) || ml.includes(w))
    if (!hit) return false
    if (seen.has(p.id)) return false
    seen.add(p.id)
    return true
  })
}

function PctBar({ label, pct, color }) {
  const n = pct ? Math.min(parseInt(pct), 100) : null
  return (
    <div className="flex items-center gap-1">
      <span className="text-[8px] text-gray-400 w-5 shrink-0">{label}</span>
      {n != null ? (
        <>
          <div className={`w-6 h-1 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden shrink-0`}>
            <div className={`h-full rounded-full ${color}`} style={{ width: `${n}%` }} />
          </div>
          <span className="text-[9px] text-gray-500 font-semibold w-6">{pct}</span>
        </>
      ) : <span className="text-[9px] text-gray-400">NA</span>}
    </div>
  )
}

function SplitCol({ line, handle, bets, lineColor = 'text-gray-700 dark:text-gray-300', barColor = 'bg-indigo-400' }) {
  return (
    <div className="flex flex-col gap-0.5 min-w-0">
      <span className={`text-[10px] font-mono font-bold leading-none ${line ? lineColor : 'text-gray-400'}`}>{line || 'NA'}</span>
      <PctBar label="hdl"  pct={handle} color={barColor} />
      <PctBar label="bts"  pct={bets}   color={barColor} />
    </div>
  )
}

function GameCard({ game, matched }) {
  const hasPicks = matched.length > 0
  return (
    <div className={`bg-white dark:bg-gray-900 rounded-xl border overflow-hidden ${hasPicks ? 'border-indigo-200 dark:border-indigo-800' : 'border-gray-200 dark:border-gray-800'}`}>
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 dark:bg-gray-950 border-b border-gray-100 dark:border-gray-800">
        {game.sport && <span className={`text-[9px] font-bold text-white px-1.5 py-0.5 rounded-full shrink-0 ${SPORT_COLOR[game.sport] || 'bg-gray-500'}`}>{game.sport}</span>}
        <span className="text-xs font-bold text-gray-800 dark:text-gray-200 flex-1 truncate">{game.matchup}</span>
        {hasPicks && <span className="text-[9px] font-bold bg-indigo-100 text-indigo-700 dark:bg-indigo-900/50 dark:text-indigo-300 px-1.5 py-0.5 rounded-full shrink-0">{matched.length} pick{matched.length !== 1 ? 's' : ''}</span>}
      </div>

      {/* Splits grid */}
      <div className="px-3 pt-2 pb-2.5">
        <div className="grid gap-x-2 mb-1 text-[9px] font-bold uppercase tracking-wider" style={{ gridTemplateColumns: '5rem 1fr 1fr 1fr' }}>
          <div />
          <span className="text-violet-500">Spread</span>
          <span className="text-sky-500">Total</span>
          <span className="text-amber-500">ML</span>
        </div>
        <div className="border-t border-gray-100 dark:border-gray-800 mb-0.5" />
        {[
          { side: game.away, isOver: true },
          { side: game.home, isOver: false },
        ].map(({ side, isOver }) => {
          if (!side) return null
          const totalLabel = game.total_line ? (isOver ? `O${game.total_line}` : `U${game.total_line}`) : null
          const mlVal = parseFloat((side.ml||'').replace(',',''))
          const mlColor = isNaN(mlVal) ? 'text-gray-700 dark:text-gray-300' : mlVal > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400'
          return (
            <div key={side.team} className={`grid items-start gap-x-2 py-1.5 ${side.is_sharp ? 'border-l-2 border-indigo-500 pl-2 -ml-2' : ''}`} style={{ gridTemplateColumns: '5rem 1fr 1fr 1fr' }}>
              <div className="flex items-center gap-1 min-w-0">
                {side.is_sharp && <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 shrink-0" />}
                <span className={`text-[11px] font-bold truncate ${side.is_sharp ? 'text-indigo-700 dark:text-indigo-400' : 'text-gray-800 dark:text-gray-200'}`}>{side.team}</span>
              </div>
              <SplitCol line={side.spread_line} handle={side.spread_handle} bets={side.spread_bets} barColor="bg-violet-400" />
              <SplitCol line={totalLabel}        handle={side.total_handle}  bets={side.total_bets}  barColor="bg-sky-400" />
              <SplitCol line={side.ml}           handle={side.ml_handle}     bets={side.ml_bets}     barColor="bg-amber-400" lineColor={mlColor} />
            </div>
          )
        })}
      </div>

      {/* Matched picks */}
      {hasPicks && (
        <div className="px-3 pb-2.5 border-t border-dashed border-indigo-100 dark:border-indigo-900/50">
          <p className="text-[9px] font-bold text-indigo-600 dark:text-indigo-400 uppercase tracking-wider pt-2 mb-1.5">PicksHub picks</p>
          <div className="flex flex-wrap gap-1.5">
            {matched.map(p => (
              <div key={p.id} className="flex items-center gap-1.5 bg-indigo-50 dark:bg-indigo-950/40 border border-indigo-100 dark:border-indigo-900/50 rounded-lg px-2 py-1">
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 shrink-0" />
                <span className="text-[11px] font-semibold text-gray-800 dark:text-gray-200 max-w-[160px] truncate">{p.pick}</span>
                {p.pick_type && <span className={`text-[9px] font-bold px-1 py-0.5 rounded shrink-0 ${TYPE_BADGE[p.pick_type] || ''}`}>{TYPE_LABEL[p.pick_type] || p.pick_type}</span>}
                {p.odds && <span className={`font-mono text-[9px] font-bold shrink-0 ${parseFloat(p.odds) > 0 ? 'text-green-600' : 'text-red-500'}`}>{p.odds}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function SplitsPage({ picks, creds }) {
  const TODAY     = localDate(0)
  const TOMORROW  = localDate(1)
  const YESTERDAY = localDate(-1)

  const TABS = [
    { id: YESTERDAY, label: 'Yesterday' },
    { id: TODAY,     label: 'Today'     },
    { id: TOMORROW,  label: 'Tomorrow'  },
  ]

  const [date,       setDate]       = useState(TODAY)
  const [games,      setGames]      = useState([])
  const [loading,    setLoading]    = useState(false)
  const [error,      setError]      = useState(null)
  const [refreshedAt, setRefreshedAt] = useState(null)
  const [sportFilter, setSport]     = useState(null)
  const [picksOnly,   setPicksOnly] = useState(false)

  const load = async (d, silent = false) => {
    if (!silent) setLoading(true)
    setError(null)
    try {
      const res = await fetchSplits(creds, d)
      setGames(Array.isArray(res.games) ? res.games : [])
      if (res.refreshed_at) setRefreshedAt(res.refreshed_at)
    } catch (err) {
      if (!silent) setError(err.message)
    }
    if (!silent) setLoading(false)
  }

  useEffect(() => { setSport(null); setPicksOnly(false); load(date) }, [date])
  useEffect(() => {
    const t = setInterval(() => load(date, true), 5 * 60 * 1000)
    return () => clearInterval(t)
  }, [date])

  const gamesWithPicks = useMemo(() =>
    games.map(g => ({ ...g, _matched: matchPicks(g.matchup, g.date, g.sport, picks) })),
    [games, picks]
  )

  const sports = useMemo(() => [...new Set(gamesWithPicks.map(g => g.sport).filter(Boolean))].sort(), [gamesWithPicks])

  const visible = useMemo(() =>
    gamesWithPicks
      .filter(g => !sportFilter || g.sport === sportFilter)
      .filter(g => !picksOnly   || g._matched.length > 0),
    [gamesWithPicks, sportFilter, picksOnly]
  )

  const withPicks = gamesWithPicks.filter(g => g._matched.length > 0)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-white">Betting Splits</h1>
          <p className="text-xs text-gray-400 mt-0.5">
            Circa Sports via VSiN · auto-refreshes every 5 min
            {refreshedAt && ` · updated ${refreshedAt}`}
          </p>
        </div>
        <button onClick={() => load(date)} disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 text-xs font-semibold hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50 transition-colors">
          <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {/* Date tabs */}
      <div className="flex gap-1 bg-gray-100 dark:bg-gray-900 p-1 rounded-xl self-start">
        {TABS.map(({ id, label }) => (
          <button key={id} onClick={() => setDate(id)}
            className={`px-4 py-1.5 rounded-lg text-sm font-semibold transition-colors ${
              date === id ? 'bg-white dark:bg-gray-800 text-gray-900 dark:text-white shadow-sm' : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}>
            {label}
          </button>
        ))}
      </div>

      {error && (
        <div className="flex items-center gap-2 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-xl px-4 py-3 text-sm">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {/* Filter chips */}
      {!loading && !error && games.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <Filter size={12} className="text-gray-400 shrink-0" />
          <Chip label={`PicksHub picks (${withPicks.length})`} active={picksOnly} onClick={() => setPicksOnly(v => !v)} color="indigo" />
          {sports.map(s => (
            <Chip key={s} label={s} active={sportFilter === s} onClick={() => setSport(f => f === s ? null : s)} />
          ))}
          {(sportFilter || picksOnly) && (
            <button onClick={() => { setSport(null); setPicksOnly(false) }} className="text-xs text-gray-400 hover:text-gray-600 transition-colors">Clear</button>
          )}
          <span className="ml-auto text-xs text-gray-400">{visible.length}/{games.length} games</span>
        </div>
      )}

      {/* Empty */}
      {!loading && !error && games.length === 0 && (
        <div className="rounded-2xl border-2 border-dashed border-gray-200 dark:border-gray-800 py-16 text-center text-gray-400">
          <p className="text-3xl mb-3">📊</p>
          <p className="font-semibold text-sm">No splits data for this date</p>
          <p className="text-xs mt-1.5">Circa Sports lines not posted yet</p>
        </div>
      )}

      {!loading && !error && games.length > 0 && visible.length === 0 && (
        <div className="rounded-2xl border-2 border-dashed border-gray-200 dark:border-gray-800 py-10 text-center text-gray-400">
          <p className="text-sm font-semibold">No games match filters</p>
          <button onClick={() => { setSport(null); setPicksOnly(false) }} className="mt-2 text-xs text-indigo-600 dark:text-indigo-400 hover:underline">Clear filters</button>
        </div>
      )}

      {!loading && visible.length > 0 && (
        <div className="flex flex-col gap-2.5">
          {visible.map((g, i) => <GameCard key={`${g.date}-${g.matchup}-${i}`} game={g} matched={g._matched} />)}
        </div>
      )}

      {loading && (
        <div className="flex flex-col gap-2.5">
          {[1,2,3,4,5].map(n => <div key={n} className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 h-24 animate-pulse" />)}
        </div>
      )}
    </div>
  )
}

function Chip({ label, active, onClick, color = 'gray' }) {
  return (
    <button onClick={onClick}
      className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border transition-colors ${
        active
          ? color === 'indigo'
            ? 'bg-indigo-500 text-white border-indigo-500'
            : 'bg-gray-800 text-white border-gray-800 dark:bg-gray-200 dark:text-gray-900 dark:border-gray-200'
          : 'bg-white dark:bg-gray-900 text-gray-500 border-gray-200 dark:border-gray-700 hover:text-gray-700'
      }`}>
      {label}
    </button>
  )
}
