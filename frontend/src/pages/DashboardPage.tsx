import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ordersApi, driveApi } from '../lib/api'
import { useDashboard } from '../hooks/useDashboard'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  Search, Package, Clock, CheckCircle, Inbox, ChevronRight, RefreshCw,
  AlertTriangle, Mail, Timer, TrendingUp, FilmIcon, Hourglass, Truck,
  BookOpenCheck, Loader2,
} from 'lucide-react'
import clsx from 'clsx'
import MetricCard from '../components/ui/MetricCard'
import AlertItem from '../components/ui/AlertItem'
import StatusPill from '../components/ui/StatusPill'
import { formatRelative, formatDays } from '../lib/format'
import { cn } from '../lib/cn'

type SearchMode = 'customer' | 'order' | 'twin'

const PIPELINE_COLORS: Record<string, string> = {
  inbound:   'bg-yellow-500',
  booked_in: 'bg-blue-500',
  scanning:  'bg-purple-500',
  delivered: 'bg-green-500',
}

function StatTile({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="p-3 rounded-lg bg-[#0f0f0f]">
      <p className="text-[#555] text-xs mb-1">{label}</p>
      <p className="text-white text-xl font-bold">{value}</p>
      {sub && <p className="text-[#444] text-xs mt-0.5">{sub}</p>}
    </div>
  )
}

export default function DashboardPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()

  const [searchQuery, setSearchQuery] = useState('')
  const [searchMode, setSearchMode] = useState<SearchMode>('customer')
  const [watcherToast, setWatcherToast] = useState<{ type: 'success' | 'info' | 'error', message: string } | null>(null)

  const { counts, needsAttention, todayActivity, performance, workload } = useDashboard()

  const showWatcherToast = (type: 'success' | 'info' | 'error', message: string) => {
    setWatcherToast({ type, message })
    setTimeout(() => setWatcherToast(null), 5000)
  }

  const runWatcherMutation = useMutation({
    mutationFn: () => driveApi.sync(),
    onSuccess: (data) => {
      if (data.status === 'already_running') {
        showWatcherToast('info', 'Watcher is already running — try again shortly')
      } else {
        showWatcherToast('success', 'Watcher run complete')
        qc.invalidateQueries({ queryKey: ['dashboard'] })
        qc.invalidateQueries({ queryKey: ['orders-recent'] })
      }
    },
    onError: () => showWatcherToast('error', 'Failed to run watcher — check the backend log'),
  })

  const { data: orders = [], isLoading: ordersLoading } = useQuery({
    queryKey: ['orders-recent'],
    queryFn: () => ordersApi.list({ limit: 8 }),
  })

  const runSearch = () => {
    const q = searchQuery.trim()
    if (!q) return
    if (searchMode === 'twin') {
      navigate(`/orders?twin=${encodeURIComponent(q)}`)
    } else {
      navigate(`/orders?q=${encodeURIComponent(q)}`)
    }
  }

  const v = (q: { isLoading: boolean }, val: string | number | undefined | null) =>
    q.isLoading ? '…' : val ?? 0

  // Pipeline strip: inbound / booked_in / scanning from aggregators
  // (scanning = pending − inbound − booked), delivered is today's count.
  const inboundCount = counts.data?.inbound_orders ?? 0
  const bookedCount = counts.data?.booked_orders ?? 0
  const scanningCount = Math.max(0, (performance.data?.pending_orders ?? 0) - inboundCount - bookedCount)
  const pipeline = [
    { key: 'inbound',   label: 'Inbound',         count: inboundCount },
    { key: 'booked_in', label: 'Booked In',       count: bookedCount },
    { key: 'scanning',  label: 'Scanning',        count: scanningCount },
    { key: 'delivered', label: 'Delivered Today', count: todayActivity.data?.orders_delivered ?? 0 },
  ]
  const pipelineMax = Math.max(1, ...pipeline.map(s => s.count))

  const attention = needsAttention.data
  const goToOrders = () => navigate('/orders')

  return (
    <div className="p-6 lg:p-8 max-w-7xl mx-auto">

      {/* Toast */}
      {watcherToast && (
        <div className={clsx(
          'fixed top-6 right-6 z-50 max-w-sm px-4 py-3 rounded-xl border text-sm font-medium shadow-lg',
          watcherToast.type === 'success' && 'bg-green-500/10 border-green-500/30 text-green-400',
          watcherToast.type === 'info' && 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400',
          watcherToast.type === 'error' && 'bg-red-500/10 border-red-500/30 text-red-400',
        )}>
          {watcherToast.message}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-white text-2xl font-bold tracking-tight mb-1">RollCall Dashboard</h1>
          <p className="text-[#555] text-sm">
            {new Date().toLocaleDateString('en-AU', { weekday: 'long', day: 'numeric', month: 'long' })} · film lab operations overview
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => runWatcherMutation.mutate()}
            disabled={runWatcherMutation.isPending}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[#111] border border-[#2a2a2a] text-[#aaa] text-sm font-medium hover:text-white hover:border-[#3a3a3a] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            title="Force a Drive watcher cycle now, instead of waiting for the 5-minute schedule"
          >
            {runWatcherMutation.isPending ? (
              <>
                <Loader2 size={14} className="animate-spin" /> Running…
              </>
            ) : (
              <>
                <FilmIcon size={14} /> Run watcher now
              </>
            )}
          </button>
          <button
            onClick={() => qc.invalidateQueries({ queryKey: ['dashboard'] })}
            className="p-2 rounded-lg bg-[#111] border border-[#2a2a2a] text-[#555] hover:text-white transition-colors"
            title="Refresh metrics"
          >
            <RefreshCw size={15} />
          </button>
        </div>
      </div>

      {/* Search bar — Customer / Order # / Twin, navigates to Orders results */}
      <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-[#111] border border-[#2a2a2a] focus-within:border-[#ff6600] mb-6 transition-colors">
        <Search size={17} className="text-[#444]" />
        <input
          type="text"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && runSearch()}
          placeholder={
            searchMode === 'customer' ? 'Search by customer name…'
            : searchMode === 'order' ? 'Search by order number…'
            : 'Search by twin check (e.g. 0042)…'
          }
          className="flex-1 bg-transparent outline-none text-white text-sm placeholder:text-[#333]"
        />
        <select
          value={searchMode}
          onChange={e => setSearchMode(e.target.value as SearchMode)}
          className="px-3 py-1.5 rounded-lg bg-[#0f0f0f] border border-[#2a2a2a] text-[#aaa] text-sm focus:outline-none"
        >
          <option value="customer">Customer</option>
          <option value="order">Order #</option>
          <option value="twin">Twin Check</option>
        </select>
        <button
          onClick={runSearch}
          disabled={!searchQuery.trim()}
          className="px-4 py-1.5 rounded-lg bg-[#ff6600] hover:bg-[#ff7720] text-white text-sm font-semibold transition-colors disabled:opacity-40"
        >
          Search
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* ── Main column ─────────────────────────────────── */}
        <div className="lg:col-span-2 space-y-6">

          {/* 4 metric cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard
              label="Inbound Orders"
              value={v(counts, counts.data?.inbound_orders)}
              icon={Inbox}
              accent
              sub="Awaiting booking in"
            />
            <MetricCard
              label="Booked Orders"
              value={v(counts, counts.data?.booked_orders)}
              icon={BookOpenCheck}
              sub="In the lab"
            />
            <MetricCard
              label="Inbound Rolls"
              value={v(counts, counts.data?.inbound_rolls)}
              icon={FilmIcon}
              sub="From inbound orders"
            />
            <MetricCard
              label="Booked Rolls"
              value={v(counts, counts.data?.booked_rolls)}
              icon={Package}
              sub="Being processed"
            />
          </div>

          {/* Status Pipeline strip */}
          <div className="rounded-xl p-5 bg-[#111] border border-[#1e1e1e]">
            <h2 className="text-white text-base font-bold mb-4">Status Pipeline</h2>
            <div className="space-y-3">
              {pipeline.map(stage => (
                <div key={stage.key}>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[#aaa] text-sm font-medium">{stage.label}</span>
                    <span className="text-white text-sm font-bold">
                      {counts.isLoading || performance.isLoading ? '…' : stage.count}
                    </span>
                  </div>
                  <div className="w-full h-3 rounded-full overflow-hidden bg-[#0f0f0f]">
                    <div
                      className={cn('h-full transition-all duration-500', PIPELINE_COLORS[stage.key])}
                      style={{ width: `${Math.max(5, (stage.count / pipelineMax) * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Performance Metrics */}
          <div className="rounded-xl p-5 bg-[#111] border border-[#1e1e1e]">
            <h2 className="text-white text-base font-bold mb-4">Performance Metrics</h2>
            <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
              <StatTile
                label="Avg Turnaround"
                value={performance.isLoading ? '…' : formatDays(performance.data?.avg_turnaround_days)}
                sub="Last 30 days"
              />
              <StatTile label="Rolls Today" value={v(performance, performance.data?.rolls_today)} sub="Delivered" />
              <StatTile label="Pending Rolls" value={v(performance, performance.data?.pending_rolls)} />
              <StatTile label="Pending Orders" value={v(performance, performance.data?.pending_orders)} />
              <StatTile label="Overdue" value={v(performance, performance.data?.overdue_count)} sub="48h+ booked in" />
            </div>
          </div>

          {/* Embedded orders list */}
          <div className="rounded-xl bg-[#111] border border-[#1e1e1e] overflow-hidden">
            <div className="flex items-center justify-between px-5 py-4 border-b border-[#1e1e1e]">
              <h2 className="text-white text-base font-bold">
                Orders
                {performance.data != null && (
                  <span className="ml-2 px-2 py-0.5 rounded-full bg-[#1a1a1a] border border-[#2a2a2a] text-[#888] text-xs font-medium align-middle">
                    {performance.data.pending_orders} active
                  </span>
                )}
              </h2>
              <Link to="/orders" className="text-[#ff6600] text-sm hover:text-[#ff8833] flex items-center gap-1">
                View all <ChevronRight size={14} />
              </Link>
            </div>
            {ordersLoading ? (
              <div className="px-5 py-8 text-center text-[#444] text-sm">Loading…</div>
            ) : orders.length === 0 ? (
              <div className="px-5 py-8 text-center text-[#444] text-sm">No orders yet</div>
            ) : (
              <div className="divide-y divide-[#1a1a1a]">
                {orders.map((order: any) => (
                  <Link
                    key={order.id}
                    to={`/orders/${order.id}`}
                    className="flex items-center gap-3 px-5 py-3 hover:bg-[#161616] transition-colors"
                  >
                    <div className="w-8 h-8 rounded-lg bg-[#1a1a1a] flex items-center justify-center flex-shrink-0">
                      <Package size={14} className="text-[#ff6600]" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-white text-sm font-semibold truncate">{order.customer_name}</p>
                      <p className="text-[#555] text-xs truncate">
                        Order #{order.order_number} · {order.rolls?.length ?? 0} roll{order.rolls?.length !== 1 ? 's' : ''} · {formatRelative(order.created_at)}
                      </p>
                    </div>
                    <StatusPill status={order.status} className="flex-shrink-0" />
                    <ChevronRight size={15} className="text-[#333] flex-shrink-0" />
                  </Link>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ── Right sidebar ───────────────────────────────── */}
        <div className="space-y-6">

          {/* Needs Attention */}
          <div className="rounded-xl p-5 bg-[#111] border border-[#1e1e1e]">
            <h2 className="text-white text-base font-bold mb-4">Needs Attention</h2>
            {needsAttention.isLoading ? (
              <p className="text-[#444] text-sm">Loading…</p>
            ) : (
              <div className="space-y-3">
                <AlertItem
                  icon={AlertTriangle}
                  title="Overdue Orders"
                  sub="Booked in 48h+ ago"
                  count={attention?.overdue_count ?? 0}
                  severity="critical"
                  onClick={goToOrders}
                />
                <AlertItem
                  icon={Clock}
                  title="Stuck in Scanning"
                  sub="Scanning for 24h+"
                  count={attention?.stuck_in_scanning_count ?? 0}
                  severity="warning"
                  onClick={goToOrders}
                />
                <AlertItem
                  icon={Mail}
                  title="Missing Email"
                  sub="Delivered, no contact"
                  count={attention?.missing_email_count ?? 0}
                  severity="info"
                  onClick={goToOrders}
                />
                <AlertItem
                  icon={Hourglass}
                  title="Aging Inbound"
                  sub="Sold 24h+ ago, not booked"
                  count={attention?.inbound_aging_count ?? 0}
                  severity="warning"
                  onClick={goToOrders}
                />
              </div>
            )}
          </div>

          {/* Today's Activity */}
          <div className="rounded-xl p-5 bg-[#111] border border-[#1e1e1e]">
            <h2 className="text-white text-base font-bold mb-4">Today's Activity</h2>
            <div className="space-y-3">
              <div className="flex items-center justify-between p-3 rounded-lg bg-[#0f0f0f]">
                <span className="flex items-center gap-2 text-[#888] text-sm"><Inbox size={14} className="text-yellow-400" /> Received</span>
                <span className="text-white font-bold">{v(todayActivity, todayActivity.data?.orders_received)}</span>
              </div>
              <div className="flex items-center justify-between p-3 rounded-lg bg-[#0f0f0f]">
                <span className="flex items-center gap-2 text-[#888] text-sm"><CheckCircle size={14} className="text-blue-400" /> Booked In</span>
                <span className="text-white font-bold">{v(todayActivity, todayActivity.data?.orders_booked_in)}</span>
              </div>
              <div className="flex items-center justify-between p-3 rounded-lg bg-[#0f0f0f]">
                <span className="flex items-center gap-2 text-[#888] text-sm"><Truck size={14} className="text-green-400" /> Delivered</span>
                <span className="text-white font-bold">{v(todayActivity, todayActivity.data?.orders_delivered)}</span>
              </div>
            </div>
          </div>

          {/* Workload Insights */}
          <div className="rounded-xl p-5 bg-[#111] border border-[#1e1e1e]">
            <h2 className="text-white text-base font-bold mb-4">Workload Insights</h2>
            <div className="space-y-3">
              <div className="flex items-center justify-between p-3 rounded-lg bg-[#0f0f0f]">
                <span className="flex items-center gap-2 text-[#888] text-sm"><Timer size={14} className="text-[#ff6600]" /> Avg Pending Age</span>
                <span className="text-white font-bold">{workload.isLoading ? '…' : formatDays(workload.data?.avg_pending_age_days)}</span>
              </div>
              <div className="flex items-center justify-between p-3 rounded-lg bg-[#0f0f0f]">
                <span className="flex items-center gap-2 text-[#888] text-sm"><TrendingUp size={14} className="text-[#ff6600]" /> Oldest Pending</span>
                <span className="text-white font-bold">{workload.isLoading ? '…' : formatDays(workload.data?.oldest_pending_days)}</span>
              </div>
              <div className="flex items-center justify-between p-3 rounded-lg bg-[#0f0f0f]">
                <span className="flex items-center gap-2 text-[#888] text-sm"><Mail size={14} className="text-[#ff6600]" /> Missing Email</span>
                <span className="text-white font-bold">{v(workload, workload.data?.missing_email_count)}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
