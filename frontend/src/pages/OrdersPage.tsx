import { useQuery } from '@tanstack/react-query'
import { ordersApi, storesApi } from '../lib/api'
import { useAuth } from '../hooks/useAuth'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Search, FilmIcon, ChevronRight, Filter } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'

const STATUS_STYLES: Record<string, string> = {
  booked:      'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
  processing:  'bg-blue-500/10 text-blue-400 border-blue-500/20',
  scanned:     'bg-purple-500/10 text-purple-400 border-purple-500/20',
  delivered:   'bg-green-500/10 text-green-400 border-green-500/20',
  blank:       'bg-red-500/10 text-red-400 border-red-500/20',
  print_ready: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
  archived:    'bg-[#1a1a1a] text-[#555] border-[#2a2a2a]',
}

const STATUSES = ['', 'booked', 'scanned', 'delivered', 'blank', 'print_ready', 'archived']

export default function OrdersPage() {
  const { user } = useAuth()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [storeFilter, setStoreFilter] = useState(user?.store_id || '')

  const { data: stores = [] } = useQuery({ queryKey: ['stores'], queryFn: storesApi.list })

  const { data: orders = [], isLoading } = useQuery({
    queryKey: ['orders', search, status, storeFilter],
    queryFn: () => ordersApi.list({
      store_id: storeFilter || undefined,
      status: status || undefined,
      search: search || undefined,
      limit: 200,
    }),
    placeholderData: prev => prev,
  })

  return (
    <div className="p-6 lg:p-8 max-w-7xl mx-auto">

      {/* Header */}
      <div className="flex items-start justify-between mb-6 flex-wrap gap-4">
        <div>
          <h1 className="text-white text-2xl font-bold tracking-tight">Orders</h1>
          <p className="text-[#555] text-sm mt-1">{orders.length} orders</p>
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
          {STATUSES.filter(Boolean).map(s => (
            <option key={s} value={s}>{s.replace('_', ' ')}</option>
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
      </div>

      {/* Table */}
      <div className="bg-[#111] border border-[#1e1e1e] rounded-xl overflow-hidden">
        {/* Header row */}
        <div className="hidden md:grid grid-cols-[1fr_1fr_120px_80px_80px_100px_32px] gap-4 px-5 py-3 border-b border-[#1e1e1e]">
          {['Order', 'Customer', 'Status', 'Store', 'Rolls', 'Created', ''].map(h => (
            <p key={h} className="text-[#444] text-xs uppercase tracking-wider font-medium">{h}</p>
          ))}
        </div>

        {isLoading ? (
          <div className="px-5 py-10 text-center text-[#444] text-sm">Loading…</div>
        ) : orders.length === 0 ? (
          <div className="px-5 py-10 text-center text-[#444] text-sm">No orders found</div>
        ) : (
          <div className="divide-y divide-[#171717]">
            {orders.map((order: any) => (
              <Link
                key={order.id}
                to={`/orders/${order.id}`}
                className="flex md:grid md:grid-cols-[1fr_1fr_120px_80px_80px_100px_32px] items-center gap-4 px-5 py-3.5 hover:bg-[#161616] transition-colors group"
              >
                <div>
                  <p className="text-white text-sm font-mono font-medium truncate">{order.order_number}</p>
                  <p className="text-[#444] text-xs truncate md:hidden">{order.customer_name}</p>
                </div>
                <p className="text-[#888] text-sm truncate hidden md:block">{order.customer_name}</p>
                <div>
                  <span className={clsx(
                    'px-2 py-0.5 rounded-full text-[11px] font-medium border',
                    STATUS_STYLES[order.status] || 'bg-[#1a1a1a] text-[#555] border-[#2a2a2a]'
                  )}>
                    {order.status.replace('_', ' ')}
                  </span>
                </div>
                <p className="text-[#555] text-xs hidden md:block">{order.store_name}</p>
                <div className="hidden md:flex items-center gap-1 text-[#555] text-xs">
                  <FilmIcon size={11} />
                  <span>{order.rolls?.length ?? 0}</span>
                </div>
                <p className="text-[#444] text-xs hidden md:block">
                  {formatDistanceToNow(new Date(order.created_at), { addSuffix: true })}
                </p>
                <ChevronRight size={14} className="text-[#333] group-hover:text-[#555] hidden md:block" />
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
