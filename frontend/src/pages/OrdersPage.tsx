import { useQuery } from '@tanstack/react-query'
import { storesApi } from '../lib/api'
import { useOrders } from '../hooks/useOrders'
import { useAuth } from '../hooks/useAuth'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Search, FilmIcon, ChevronRight, X } from 'lucide-react'
import { cn } from '../lib/cn'
import { ACTIVE_STATUSES, ORDER_STATUSES, isTerminal, statusLabel } from '../lib/status'
import { formatDate } from '../lib/format'
import StatusPill from '../components/ui/StatusPill'
import { filmTypeMeta, filmTypeBorder } from '../lib/filmType'

export default function OrdersPage() {
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const urlSearch = params.get('q') || ''
  const urlTwin = params.get('twin') || ''

  const [search, setSearch] = useState(urlSearch)
  const [status, setStatus] = useState('')          // explicit single-status filter
  // Deep-linked searches (from the dashboard) look across every status so a
  // delivered/cancelled order can't silently vanish from the results.
  const [showAll, setShowAll] = useState(!!(urlSearch || urlTwin))
  const [storeFilter, setStoreFilter] = useState(user?.store_id || '')

  const { data: stores = [] } = useQuery({ queryKey: ['stores'], queryFn: storesApi.list })

  // Explicit status filter wins; otherwise active pipeline only, unless "Show all"
  const statuses = status ? [status] : showAll ? undefined : ACTIVE_STATUSES

  const clearTwin = () => {
    params.delete('twin')
    setParams(params, { replace: true })
  }

  const { data: orders = [], isLoading, isError, error, refetch } = useOrders({
    storeId: storeFilter || undefined,
    statuses,
    search: search || undefined,
    twin: urlTwin || undefined,
  })

  return (
    <div className="p-6 lg:p-8 max-w-7xl mx-auto">

      {/* Header */}
      <div className="flex items-start justify-between mb-6 flex-wrap gap-4">
        <div>
          <h1 className="text-white text-2xl font-bold tracking-tight">Orders</h1>
          <p className="text-[#555] text-sm mt-1">
            {orders.length} orders{!status && !showAll && ' · active only'}
          </p>
        </div>
        <Link
          to="/intake"
          className="flex items-center gap-2 bg-[#ff6600] hover:bg-[#ff7720] text-white font-semibold px-4 py-2.5 rounded-lg text-sm transition-colors"
        >
          <FilmIcon size={15} /> New Intake
        </Link>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-5">
        {urlTwin && (
          <span className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-[#1f0e00] border border-[#ff6600]/25 text-[#ff6600] text-sm font-mono">
            Twin {urlTwin.padStart(4, '0')}
            <button onClick={clearTwin} className="text-[#ff6600]/60 hover:text-[#ff6600]" title="Clear twin filter">
              <X size={13} />
            </button>
          </span>
        )}
        <div className="relative flex-1 min-w-48">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#444]" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search order, customer…"
            className="w-full bg-[#111] border border-[#2a2a2a] text-white text-sm rounded-lg pl-9 pr-4 py-2.5 focus:outline-none focus:border-[#ff6600] placeholder:text-[#333]"
          />
        </div>

        <select
          value={status}
          onChange={e => setStatus(e.target.value)}
          className="bg-[#111] border border-[#2a2a2a] text-[#aaa] text-sm rounded-lg px-3 py-2.5 focus:outline-none focus:border-[#ff6600]"
        >
          <option value="">All statuses</option>
          {ORDER_STATUSES.map(s => (
            <option key={s} value={s}>{statusLabel(s)}</option>
          ))}
        </select>

        {user?.role === 'master_admin' && (
          <select
            value={storeFilter}
            onChange={e => setStoreFilter(e.target.value)}
            className="bg-[#111] border border-[#2a2a2a] text-[#aaa] text-sm rounded-lg px-3 py-2.5 focus:outline-none focus:border-[#ff6600]"
          >
            <option value="">All stores</option>
            {stores.map((s: any) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        )}

        {/* Show all — include delivered/cancelled/discarded (ignored while a
            specific status is selected) */}
        <button
          onClick={() => setShowAll(a => !a)}
          disabled={!!status}
          className={cn(
            'px-3 py-2.5 rounded-lg text-sm border transition-colors disabled:opacity-40',
            showAll
              ? 'bg-[#ff6600]/10 border-[#ff6600]/40 text-[#ff6600]'
              : 'bg-[#111] border-[#2a2a2a] text-[#aaa] hover:text-white',
          )}
        >
          Show all
        </button>
      </div>

      {/* Table */}
      <div className="bg-[#111] border border-[#1e1e1e] rounded-xl overflow-hidden">
        {/* Header row */}
        <div className="hidden md:grid grid-cols-[1fr_1fr_120px_80px_60px_120px_120px_32px] gap-4 px-5 py-3 border-b border-[#1e1e1e]">
          {['Order', 'Customer', 'Status', 'Store', 'Rolls', 'Sale date', 'Booked in', ''].map(h => (
            <p key={h} className="text-[#444] text-xs uppercase tracking-wider font-medium">{h}</p>
          ))}
        </div>

        {isError ? (
          <div className="px-5 py-10 text-center text-sm">
            <p className="text-red-400 mb-2">
              Couldn't load orders — {(error as any)?.response?.data?.detail || (error as any)?.message || 'request failed'}
            </p>
            <button onClick={() => refetch()} className="text-[#ff6600] hover:text-[#ff8833] text-xs">
              Retry
            </button>
          </div>
        ) : isLoading ? (
          <div className="px-5 py-10 text-center text-[#444] text-sm">Loading…</div>
        ) : orders.length === 0 ? (
          <div className="px-5 py-10 text-center text-[#444] text-sm">No orders found</div>
        ) : (
          <div className="divide-y divide-[#171717]">
            {orders.map((order: any) => {
              const terminal = isTerminal(order.status)
              const film = filmTypeMeta(order.film_type)
              return (
                <Link
                  key={order.id}
                  to={`/orders/${order.id}`}
                  className={cn(
                    'flex md:grid md:grid-cols-[1fr_1fr_120px_80px_60px_120px_120px_32px] items-center gap-4 px-5 py-3.5 hover:bg-[#161616] transition-colors group border-l-2',
                    filmTypeBorder(order.film_type),
                    terminal && 'opacity-60',
                  )}
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <p className={cn('text-white text-sm font-mono font-medium truncate', terminal && 'line-through text-[#666]')}>
                        {order.order_number}
                      </p>
                      {film && (
                        <span className={cn('inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border shrink-0', film.dot)}>
                          {film.label}
                        </span>
                      )}
                    </div>
                    <p className="text-[#444] text-xs truncate md:hidden">{order.customer_name}</p>
                  </div>
                  <p className={cn('text-[#888] text-sm truncate hidden md:block', terminal && 'line-through text-[#555]')}>
                    {order.customer_name}
                  </p>
                  <div>
                    <StatusPill status={order.status} />
                  </div>
                  <p className="text-[#555] text-xs hidden md:block">{order.store_name}</p>
                  <div className="hidden md:flex items-center gap-1 text-[#555] text-xs">
                    <FilmIcon size={11} />
                    <span>{order.rolls?.length ?? 0}</span>
                  </div>
                  {/* Sale date — from Pronto order_date if available */}
                  <p className="text-[#444] text-xs hidden md:block">
                    {order.order_date ? formatDate(order.order_date) : '—'}
                  </p>
                  {/* Booked in — when staff entered the order into RollCall */}
                  <p className="text-[#444] text-xs hidden md:block">
                    {formatDate(order.created_at)}
                  </p>
                  <ChevronRight size={14} className="text-[#333] group-hover:text-[#555] hidden md:block" />
                </Link>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
