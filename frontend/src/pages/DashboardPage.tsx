import { useQuery } from '@tanstack/react-query'
import { dashboardApi, ordersApi, storesApi } from '../lib/api'
import { useAuth } from '../hooks/useAuth'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  TrendingUp, Clock, AlertTriangle, CheckCircle,
  FilmIcon, Package, ChevronRight, RefreshCw
} from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'

const STATUS_STYLES: Record<string, string> = {
  booked:      'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
  processing:  'bg-blue-500/10 text-blue-400 border-blue-500/20',
  scanned:     'bg-purple-500/10 text-purple-400 border-purple-500/20',
  delivered:   'bg-green-500/10 text-green-400 border-green-500/20',
  blank:       'bg-red-500/10 text-red-400 border-red-500/20',
  print_ready: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
}

function StatCard({ label, value, icon: Icon, accent = false, sub }: {
  label: string
  value: string | number
  icon: any
  accent?: boolean
  sub?: string
}) {
  return (
    <div className={clsx(
      'rounded-xl border p-5 flex items-start gap-4',
      accent
        ? 'bg-[#ff6600]/5 border-[#ff6600]/20'
        : 'bg-[#111] border-[#1e1e1e]'
    )}>
      <div className={clsx(
        'w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0',
        accent ? 'bg-[#ff6600]/20' : 'bg-[#1a1a1a]'
      )}>
        <Icon size={18} className={accent ? 'text-[#ff6600]' : 'text-[#555]'} />
      </div>
      <div>
        <p className="text-[#555] text-xs uppercase tracking-wider font-medium">{label}</p>
        <p className={clsx('text-2xl font-bold mt-0.5', accent ? 'text-white' : 'text-white')}>
          {value}
        </p>
        {sub && <p className="text-[#444] text-xs mt-0.5">{sub}</p>}
      </div>
    </div>
  )
}

export default function DashboardPage() {
  const { user } = useAuth()
  const [storeFilter, setStoreFilter] = useState<string>(user?.store_id || '')

  const { data: stores = [] } = useQuery({
    queryKey: ['stores'],
    queryFn: storesApi.list,
  })

  const { data: stats, isLoading: statsLoading, refetch } = useQuery({
    queryKey: ['dashboard-stats', storeFilter],
    queryFn: () => dashboardApi.stats(storeFilter || undefined),
  })

  const { data: orders = [], isLoading: ordersLoading } = useQuery({
    queryKey: ['orders-recent', storeFilter],
    queryFn: () => ordersApi.list({
      store_id: storeFilter || undefined,
      limit: 20,
    }),
  })

  const avgHours = stats?.avg_turnaround_hours
  const avgDisplay = avgHours != null
    ? avgHours < 24 ? `${avgHours.toFixed(1)}h` : `${(avgHours / 24).toFixed(1)}d`
    : '—'

  return (
    <div className="p-6 lg:p-8 max-w-7xl mx-auto">

      {/* Header */}
      <div className="flex items-start justify-between mb-8 flex-wrap gap-4">
        <div>
          <h1 className="text-white text-2xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-[#555] text-sm mt-1">
            {new Date().toLocaleDateString('en-AU', { weekday: 'long', day: 'numeric', month: 'long' })}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {user?.role === 'master_admin' && stores.length > 0 && (
            <select
              value={storeFilter}
              onChange={e => setStoreFilter(e.target.value)}
              className="bg-[#111] border border-[#2a2a2a] text-[#aaa] text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-[#ff6600]"
            >
              <option value="">All Stores</option>
              {stores.map((s: any) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          )}
          <button
            onClick={() => refetch()}
            className="p-2 rounded-lg bg-[#111] border border-[#2a2a2a] text-[#555] hover:text-white transition-colors"
          >
            <RefreshCw size={15} />
          </button>
        </div>
      </div>

      {/* Today highlight */}
      <div className="bg-[#111] border border-[#1e1e1e] rounded-xl px-6 py-4 mb-6 flex items-center gap-6 flex-wrap">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-[#ff6600] animate-pulse" />
          <span className="text-[#888] text-sm">Today</span>
        </div>
        <div className="flex items-center gap-6 text-sm">
          <span className="text-white font-semibold">
            {statsLoading ? '…' : stats?.orders_today ?? 0}
            <span className="text-[#555] font-normal ml-1.5">orders</span>
          </span>
          <span className="text-white font-semibold">
            {statsLoading ? '…' : stats?.rolls_today ?? 0}
            <span className="text-[#555] font-normal ml-1.5">rolls</span>
          </span>
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          label="Orders (30d)"
          value={statsLoading ? '…' : stats?.total_orders ?? 0}
          icon={FilmIcon}
          accent
        />
        <StatCard
          label="Delivered"
          value={statsLoading ? '…' : stats?.delivered_orders ?? 0}
          icon={CheckCircle}
        />
        <StatCard
          label="Pending"
          value={statsLoading ? '…' : stats?.pending_orders ?? 0}
          icon={Clock}
          sub="Booked or scanned"
        />
        <StatCard
          label={stats?.overdue_orders ? '⚠ Overdue' : 'Overdue'}
          value={statsLoading ? '…' : stats?.overdue_orders ?? 0}
          icon={AlertTriangle}
        />
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          label="Avg Turnaround"
          value={statsLoading ? '…' : avgDisplay}
          icon={TrendingUp}
          sub="Booking → delivery"
        />
        <StatCard
          label="Blank Rolls"
          value={statsLoading ? '…' : stats?.blank_orders ?? 0}
          icon={Package}
        />
      </div>

      {/* Recent orders */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-white font-semibold">Recent Orders</h2>
          <Link to="/orders" className="text-[#ff6600] text-sm hover:text-[#ff8833] flex items-center gap-1">
            View all <ChevronRight size={14} />
          </Link>
        </div>

        <div className="bg-[#111] border border-[#1e1e1e] rounded-xl overflow-hidden">
          {ordersLoading ? (
            <div className="px-6 py-8 text-center text-[#444] text-sm">Loading…</div>
          ) : orders.length === 0 ? (
            <div className="px-6 py-8 text-center text-[#444] text-sm">No orders yet</div>
          ) : (
            <div className="divide-y divide-[#1a1a1a]">
              {orders.slice(0, 10).map((order: any) => (
                <Link
                  key={order.id}
                  to={`/orders/${order.id}`}
                  className="flex items-center gap-4 px-5 py-4 hover:bg-[#161616] transition-colors group"
                >
                  {/* Order number */}
                  <div className="flex-shrink-0 w-32">
                    <p className="text-white text-sm font-mono font-medium truncate">
                      {order.order_number}
                    </p>
                    <p className="text-[#444] text-xs mt-0.5 truncate">{order.customer_name}</p>
                  </div>

                  {/* Store */}
                  <div className="hidden md:block text-[#555] text-xs flex-shrink-0 w-20">
                    {order.store_name}
                  </div>

                  {/* Status */}
                  <span className={clsx(
                    'px-2 py-0.5 rounded-full text-[11px] font-medium border flex-shrink-0',
                    STATUS_STYLES[order.status] || 'bg-[#1a1a1a] text-[#666] border-[#2a2a2a]'
                  )}>
                    {order.status.replace('_', ' ')}
                  </span>

                  {/* Rolls */}
                  <div className="hidden sm:flex items-center gap-1 text-[#555] text-xs flex-shrink-0">
                    <FilmIcon size={11} />
                    <span>{order.rolls?.length ?? 0} roll{order.rolls?.length !== 1 ? 's' : ''}</span>
                  </div>

                  {/* Time */}
                  <div className="ml-auto text-[#444] text-xs flex-shrink-0">
                    {formatDistanceToNow(new Date(order.created_at), { addSuffix: true })}
                  </div>

                  <ChevronRight size={14} className="text-[#333] group-hover:text-[#555] flex-shrink-0" />
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
