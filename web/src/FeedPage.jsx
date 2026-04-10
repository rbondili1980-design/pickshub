import { useState, useMemo, useCallback } from 'react'
import { Search, Filter, X, Eye, EyeOff, ChevronLeft, ChevronRight } from 'lucide-react'
import { gradePick, toggleHidden } from './api'

// ── Shared badge helpers ──────────────────────────────────────────────────────

const SPORT_CLS = {
  MLB: 'bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300',
  NBA: 'bg-orange-100 text-orange-700 dark:bg-orange-900/50 dark:text-orange-300',
  NHL: 'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300',
  NFL: 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300',
  CBB: 'bg-purple-100 text-purple-700 dark:bg-purple-900/50 dark:text-purple-300',
  CFB: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/50 dark:text-yellow-300',
  MLS: 'bg-teal-100 text-teal-700 dark:bg-teal-900/50 dark:text-teal-300',
}

const TYPE_CLS = {
  spread:    'bg-violet-100 text-violet-700 dark:bg-violet-900/50 dark:text-violet-300',
  total:     'bg-sky-100 text-sky-700 dark:bg-sky-900/50 dark:text-sky-300',
  moneyline: 'bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300',
  props:     'bg-pink-100 text-pink-700 dark:bg-pink-900/50 dark:text-pink-300',
  parlay:    'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300',
}
const TYPE_LABEL = { total: 'Total', spread: 'Spread', moneyline: 'ML', props: 'Prop', parlay: 'Parlay' }

const RESULT_CLS = {
  win:     'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300',
  loss:    'bg-red-100 text-red-600 dark:bg-red-900/50 dark:text-red-400',
  push:    'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400',
  void:    'bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500',
  pending: 'bg-yellow-50 text-yellow-600 dark:bg-yellow-950/50 dark:text-yellow-400',
}
const RESULT_LABEL = { win: 'W', loss: 'L', push: 'P', void: '—', pending: '?' }

const SOURCE_CLS = {
  winible:        'bg-purple-100 text-purple-700 dark:bg-purple-900/50 dark:text-purple-300',
  action_network: 'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300',
}

function fmtDate(s) {
  if (!s) return '—'
  if (s === 'futures') return 'Futures'
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString([], { month: 'short', day: 'numeric' })
}

const sel = 'text-xs border border-gray-200 dark:border-gray-700 rounded-lg px-2.5 py-1.5 bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500'

const PAGE_SIZE = 50

// ── Grade buttons ─────────────────────────────────────────────────────────────

function GradeCell({ pick, creds, onChange }) {
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
    <div className="flex items-center gap-1 flex-wrap">
      <span className={`text-xs font-bold px-1.5 py-0.5 rounded-full shrink-0 ${RESULT_CLS[result] || RESULT_CLS.pending}`}>
        {RESULT_LABEL[result] || '?'}
      </span>
      <div className="flex gap-0.5">
        {['win','loss','push','void'].map(r => (
          <button key={r} disabled={busy || pick.result === r} onClick={() => grade(r)}
            className={`text-[10px] font-bold px-1.5 py-0.5 rounded transition-colors disabled:opacity-40 ${
              pick.result === r ? RESULT_CLS[r] : 'bg-gray-100 dark:bg-gray-800 text-gray-500 hover:bg-gray-200 dark:hover:bg-gray-700'
            }`}>
            {r === 'win' ? 'W' : r === 'loss' ? 'L' : r === 'push' ? 'P' : '✕'}
          </button>
        ))}
      </div>
    </div>
  )
}

function VisCell({ pick, creds, onChange }) {
  const [busy, setBusy] = useState(false)
  const toggle = async () => {
    if (busy) return
    setBusy(true)
    try {
      await toggleHidden(creds, pick.id, !pick.hidden)
      onChange(pick.id, { hidden: !pick.hidden })
    } catch {}
    setBusy(false)
  }
  return (
    <button onClick={toggle} disabled={busy} title={pick.hidden ? 'Show' : 'Hide'}
      className={`p-1.5 rounded-lg transition-colors disabled:opacity-40 ${
        pick.hidden
          ? 'text-red-400 bg-red-50 dark:bg-red-950/40 hover:bg-red-100'
          : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800'
      }`}>
      {pick.hidden ? <EyeOff size={13} /> : <Eye size={13} />}
    </button>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function FeedPage({ picks, setPicks, creds }) {
  const [search,       setSearch]       = useState('')
  const [sportFilter,  setSport]        = useState('')
  const [typeFilter,   setType]         = useState('')
  const [resultFilter, setResult]       = useState('')
  const [expertFilter, setExpert]       = useState('')
  const [sourceFilter, setSource]       = useState('')
  const [showHidden,   setShowHidden]   = useState(true)
  const [page,         setPage]         = useState(1)

  const onChange = useCallback((id, patch) => {
    setPicks(prev => prev.map(p => p.id === id ? { ...p, ...patch } : p))
  }, [setPicks])

  const uniq = (arr) => [...new Set(arr.filter(Boolean))].sort()
  const dates   = useMemo(() => uniq(picks.map(p => p.posted_at)).reverse(), [picks])
  const sports  = useMemo(() => uniq(picks.map(p => p.sport)), [picks])
  const types   = useMemo(() => uniq(picks.map(p => p.pick_type)), [picks])
  const experts = useMemo(() => uniq(picks.map(p => p.expert)), [picks])

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return picks
      .filter(p => showHidden || !p.hidden)
      .filter(p => !sportFilter  || p.sport     === sportFilter)
      .filter(p => !typeFilter   || p.pick_type === typeFilter)
      .filter(p => !resultFilter || (p.result || 'pending') === resultFilter)
      .filter(p => !expertFilter || p.expert    === expertFilter)
      .filter(p => !sourceFilter || p.source    === sourceFilter)
      .filter(p => !q || p.pick.toLowerCase().includes(q) || (p.expert||'').toLowerCase().includes(q) || (p.game||'').toLowerCase().includes(q))
      .sort((a, b) => {
        const d = (b.posted_at||'').localeCompare(a.posted_at||'')
        return d !== 0 ? d : b.id - a.id
      })
  }, [picks, search, sportFilter, typeFilter, resultFilter, expertFilter, sourceFilter, showHidden])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage   = Math.min(page, totalPages)
  const displayed  = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)
  const hiddenCount = picks.filter(p => p.hidden).length
  const hasFilter  = search || sportFilter || typeFilter || resultFilter || expertFilter || sourceFilter

  const clearFilters = () => { setSearch(''); setSport(''); setType(''); setResult(''); setExpert(''); setSource('') }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-gray-900 dark:text-white">Pick Feed</h1>
          <p className="text-xs text-gray-400">{filtered.length} of {picks.length} picks</p>
        </div>
      </div>

      {/* Search */}
      <div className="relative">
        <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
        <input value={search} onChange={e => { setSearch(e.target.value); setPage(1) }}
          placeholder="Search expert, pick, game…"
          className="w-full pl-8 pr-8 py-2 text-sm bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500 text-gray-800 dark:text-gray-200 placeholder-gray-400" />
        {search && <button onClick={() => setSearch('')} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"><X size={13} /></button>}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <Filter size={13} className="text-gray-400 shrink-0" />

        <select value={sportFilter}  onChange={e => { setSport(e.target.value);  setPage(1) }} className={sel}>
          <option value="">All sports</option>
          {sports.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={typeFilter}   onChange={e => { setType(e.target.value);   setPage(1) }} className={sel}>
          <option value="">All types</option>
          {types.map(t => <option key={t} value={t}>{TYPE_LABEL[t] || t}</option>)}
        </select>
        <select value={resultFilter} onChange={e => { setResult(e.target.value); setPage(1) }} className={sel}>
          <option value="">All results</option>
          {['pending','win','loss','push','void'].map(r => <option key={r} value={r}>{r.charAt(0).toUpperCase()+r.slice(1)}</option>)}
        </select>
        <select value={expertFilter} onChange={e => { setExpert(e.target.value); setPage(1) }} className={sel}>
          <option value="">All experts</option>
          {experts.map(e => <option key={e} value={e}>{e}</option>)}
        </select>
        <select value={sourceFilter} onChange={e => { setSource(e.target.value); setPage(1) }} className={sel}>
          <option value="">All sources</option>
          <option value="winible">Winible</option>
          <option value="action_network">Action Network</option>
        </select>

        {hiddenCount > 0 && (
          <button onClick={() => setShowHidden(v => !v)}
            className={`flex items-center gap-1 text-xs font-medium px-2.5 py-1.5 rounded-lg border transition-colors ${
              showHidden
                ? 'border-gray-200 dark:border-gray-700 text-gray-500 hover:text-gray-700'
                : 'border-red-300 bg-red-50 text-red-600 dark:bg-red-950/40 dark:text-red-400 dark:border-red-800'
            }`}>
            {showHidden ? <Eye size={12} /> : <EyeOff size={12} />}
            {hiddenCount} hidden
          </button>
        )}

        {hasFilter && (
          <button onClick={clearFilters} className="flex items-center gap-1 text-xs text-gray-400 hover:text-red-500 transition-colors">
            <X size={12} /> Clear
          </button>
        )}
      </div>

      {/* Table */}
      {filtered.length === 0 ? (
        <div className="text-center py-20 text-gray-400">
          <p className="text-4xl mb-3">📭</p>
          <p className="font-semibold">{picks.length === 0 ? 'No picks yet' : 'No picks match filters'}</p>
        </div>
      ) : (
        <>
          <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-x-auto">
            <table className="w-full text-sm min-w-[700px]">
              <thead>
                <tr className="border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/50">
                  {['Date','Expert','Pick','Game','Sport','Type','Odds','Units','Result','Vis'].map(h => (
                    <th key={h} className="text-left text-xs font-semibold text-gray-400 uppercase tracking-wide px-4 py-3 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {displayed.map(p => (
                  <tr key={p.id} className={`border-b border-gray-50 dark:border-gray-800/40 last:border-0 transition-colors ${
                    p.hidden ? 'opacity-40 bg-red-50/20 dark:bg-red-950/10' : 'hover:bg-indigo-50/30 dark:hover:bg-indigo-950/10'
                  }`}>
                    <td className="px-4 py-3 whitespace-nowrap text-xs text-gray-600 dark:text-gray-400">{fmtDate(p.posted_at)}</td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs font-semibold text-indigo-600 dark:text-indigo-400">{p.expert || '—'}</span>
                        {p.source && (
                          <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${SOURCE_CLS[p.source] || 'bg-gray-100 text-gray-500'}`}>
                            {p.source === 'action_network' ? 'AN' : 'WIN'}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 max-w-[200px]">
                      <p className={`text-xs font-semibold leading-snug line-clamp-2 ${p.hidden ? 'line-through text-gray-400' : 'text-gray-900 dark:text-white'}`}>{p.pick}</p>
                    </td>
                    <td className="px-4 py-3 max-w-[140px]">
                      <p className="text-xs text-gray-500 truncate">{p.game || '—'}</p>
                    </td>
                    <td className="px-4 py-3">
                      {p.sport
                        ? <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${SPORT_CLS[p.sport] || 'bg-gray-100 text-gray-500'}`}>{p.sport}</span>
                        : <span className="text-xs text-gray-300 dark:text-gray-700">—</span>}
                    </td>
                    <td className="px-4 py-3">
                      {p.pick_type
                        ? <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${TYPE_CLS[p.pick_type] || 'bg-gray-100 text-gray-500'}`}>{TYPE_LABEL[p.pick_type] || p.pick_type}</span>
                        : <span className="text-xs text-gray-300 dark:text-gray-700">—</span>}
                    </td>
                    <td className="px-4 py-3">
                      {p.odds
                        ? <span className={`font-mono text-xs font-bold px-2 py-0.5 rounded-full ${parseFloat(p.odds) > 0 ? 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300' : 'bg-red-100 text-red-600 dark:bg-red-900/50 dark:text-red-400'}`}>{p.odds}</span>
                        : <span className="text-xs text-gray-300 dark:text-gray-700">—</span>}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500">{p.units || '—'}</td>
                    <td className="px-4 py-3">
                      <GradeCell pick={p} creds={creds} onChange={onChange} />
                    </td>
                    <td className="px-4 py-3">
                      <VisCell pick={p} creds={creds} onChange={onChange} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between px-1">
              <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={safePage === 1}
                className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-40 transition-colors">
                <ChevronLeft size={15} /> Prev
              </button>
              <span className="text-xs text-gray-500">Page {safePage} of {totalPages}</span>
              <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={safePage === totalPages}
                className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-40 transition-colors">
                Next <ChevronRight size={15} />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
