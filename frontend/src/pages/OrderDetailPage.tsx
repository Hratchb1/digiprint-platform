import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { ordersApi } from '../lib/api'
import { useState } from 'react'
import { ArrowLeft, FilmIcon, ExternalLink, Check, AlertTriangle, Clock, ChevronDown } from 'lucide-react'
import { format } from 'date-fns'
import clsx from 'clsx'

const STATUS_STYLES: Record<string, string> = {
  booked:      'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
  processing:  'bg-blue-500/10 text-blue-400 border-blue-500/20',
  scanned:     'bg-purple-500/10 text-purple-400 border-purple-500/20',
  delivered:   'bg-green-500/10 text-green-400 border-green-500/20',
  blank:       'bg-red-500/10 text-red-400 border-red-500/20',
  print_ready: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
}

const NEXT_STATUSES: Record<string, string[]> = {
  booked:      ['processing', 'scanned', 'delivered', 'cancelled'],
  processing:  ['scanned', 'delivered', 'cancelled'],
  scanned:     ['delivered', 'print_ready', 'cancelled'],
  print_ready: ['delivered'],
  delivered:   ['archived'],
}

export default function OrderDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [driveLink, setDriveLink] = useState('')
  const [showDriveInput, setShowDriveInput] = useState(false)
  const [selectedRolls, setSelectedRolls] = useState<Set<string>>(new Set())

  const { data: order, isLoading } = useQuery({
    queryKey: ['order', id],
    queryFn: () => ordersApi.get(id!),
    enabled: !!id,
  })

  const { data: events = [] } = useQuery({
    queryKey: ['order-events', id],
    queryFn: () => ordersApi.events(id!),
    enabled: !!id,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['order', id] })
    qc.invalidateQueries({ queryKey: ['order-events', id] })
    qc.invalidateQueries({ queryKey: ['orders-recent'] })
  }

  const statusMutation = useMutation({
    mutationFn: (status: string) => ordersApi.updateStatus(id!, status),
    onSuccess: invalidate,
  })

  const driveMutation = useMutation({
    mutationFn: (url: string) => ordersApi.setDriveLink(id!, url),
    onSuccess: () => { setShowDriveInput(false); setDriveLink(''); invalidate() },
  })

  const blankMutation = useMutation({
    mutationFn: () => ordersApi.markBlank(id!, [...selectedRolls]),
    onSuccess: () => { setSelectedRolls(new Set()); invalidate() },
  })

  if (isLoading) return (
    <div className="p-8 text-[#444] text-sm">Loading…</div>
  )

  if (!order) return (
    <div className="p-8 text-[#ff4444] text-sm">Order not found</div>
  )

  const nextStatuses = NEXT_STATUSES[order.status] || []
  const turnaround = order.date_delivered && order.created_at
    ? ((new Date(order.date_delivered).getTime() - new Date(order.created_at).getTime()) / 3600000).toFixed(1)
    : null

  return (
    <div className="p-6 lg:p-8 max-w-5xl mx-auto">

      {/* Back */}
      <button
        onClick={() => navigate('/orders')}
        className="flex items-center gap-2 text-[#555] hover:text-white text-sm mb-6 transition-colors"
      >
        <ArrowLeft size={15} /> Back to orders
      </button>

      <div className="grid lg:grid-cols-3 gap-6">

        {/* Main column */}
        <div className="lg:col-span-2 space-y-5">

          {/* Order header card */}
          <div className="bg-[#111] border border-[#1e1e1e] rounded-xl p-6">
            <div className="flex items-start justify-between gap-4 mb-4">
              <div>
                <p className="text-[#555] text-xs uppercase tracking-wider mb-1">Order</p>
                <h1 className="text-white text-xl font-bold font-mono">{order.order_number}</h1>
              </div>
              <span className={clsx(
                'px-3 py-1 rounded-full text-xs font-medium border',
                STATUS_STYLES[order.status] || 'bg-[#1a1a1a] text-[#555] border-[#2a2a2a]'
              )}>
                {order.status.replace('_', ' ')}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <p className="text-[#444] text-xs mb-0.5">Customer</p>
                <p className="text-white">{order.customer_name}</p>
              </div>
              <div>
                <p className="text-[#444] text-xs mb-0.5">Email</p>
                <p className="text-[#888]">{order.customer_email || '—'}</p>
              </div>
              <div>
                <p className="text-[#444] text-xs mb-0.5">Store</p>
                <p className="text-white">{order.store_name}</p>
              </div>
              <div>
                <p className="text-[#444] text-xs mb-0.5">Operator</p>
                <p className="text-white">{order.operator_initials || '—'}</p>
              </div>
              <div>
                <p className="text-[#444] text-xs mb-0.5">Booked</p>
                <p className="text-white">{format(new Date(order.created_at), 'd MMM yyyy, HH:mm')}</p>
              </div>
              {order.date_delivered && (
                <div>
                  <p className="text-[#444] text-xs mb-0.5">Delivered</p>
                  <p className="text-green-400">{format(new Date(order.date_delivered), 'd MMM yyyy, HH:mm')}</p>
                </div>
              )}
              {turnaround && (
                <div>
                  <p className="text-[#444] text-xs mb-0.5">Turnaround</p>
                  <p className="text-white">{Number(turnaround) < 24 ? `${turnaround}h` : `${(Number(turnaround)/24).toFixed(1)}d`}</p>
                </div>
              )}
              {order.account && (
                <div>
                  <p className="text-[#444] text-xs mb-0.5">Account</p>
                  <p className="text-[#ff6600]">{order.account}</p>
                </div>
              )}
            </div>

            {/* Drive link */}
            {order.drive_order_folder_url ? (
              <a
                href={order.drive_order_folder_url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-4 flex items-center gap-2 text-[#ff6600] hover:text-[#ff8833] text-sm transition-colors"
              >
                <ExternalLink size={14} /> Open Drive folder
              </a>
            ) : (
              <div className="mt-4">
                {showDriveInput ? (
                  <div className="flex gap-2">
                    <input
                      value={driveLink}
                      onChange={e => setDriveLink(e.target.value)}
                      placeholder="Paste Google Drive URL…"
                      className="flex-1 bg-[#0f0f0f] border border-[#2a2a2a] text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-[#ff6600]"
                    />
                    <button
                      onClick={() => driveLink && driveMutation.mutate(driveLink)}
                      disabled={!driveLink || driveMutation.isPending}
                      className="px-3 py-2 bg-[#ff6600] text-white rounded-lg text-sm disabled:opacity-40"
                    >
                      Save
                    </button>
                    <button onClick={() => setShowDriveInput(false)} className="px-3 py-2 text-[#555] hover:text-white text-sm">
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setShowDriveInput(true)}
                    className="text-[#444] hover:text-[#888] text-sm transition-colors"
                  >
                    + Add Drive folder link
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Rolls */}
          <div className="bg-[#111] border border-[#1e1e1e] rounded-xl overflow-hidden">
            <div className="px-5 py-3 border-b border-[#1e1e1e] flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FilmIcon size={14} className="text-[#ff6600]" />
                <p className="text-white text-sm font-medium">{order.rolls?.length ?? 0} Rolls</p>
              </div>
              {selectedRolls.size > 0 && (
                <button
                  onClick={() => blankMutation.mutate()}
                  disabled={blankMutation.isPending}
                  className="flex items-center gap-1.5 text-[#ff4444] hover:text-red-300 text-xs border border-red-500/20 bg-red-500/5 px-3 py-1.5 rounded-lg transition-colors"
                >
                  <AlertTriangle size={12} /> Mark {selectedRolls.size} blank
                </button>
              )}
            </div>
            <div className="divide-y divide-[#171717]">
              {order.rolls?.map((roll: any) => (
                <div
                  key={roll.id}
                  className={clsx(
                    'flex items-center gap-4 px-5 py-3',
                    roll.is_blank && 'bg-red-500/5'
                  )}
                >
                  <input
                    type="checkbox"
                    checked={selectedRolls.has(roll.id)}
                    onChange={e => {
                      const s = new Set(selectedRolls)
                      e.target.checked ? s.add(roll.id) : s.delete(roll.id)
                      setSelectedRolls(s)
                    }}
                    className="accent-[#ff6600]"
                  />
                  <span className="font-mono text-white text-sm w-12">{roll.twin_check}</span>
                  <span className="text-[#555] text-xs flex-1">{roll.service_type}</span>
                  {roll.is_blank && (
                    <span className="px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 border border-red-500/20 text-[11px]">
                      Blank
                    </span>
                  )}
                  <span className={clsx(
                    'px-2 py-0.5 rounded-full text-[11px] border',
                    STATUS_STYLES[roll.status] || 'bg-[#1a1a1a] text-[#555] border-[#2a2a2a]'
                  )}>
                    {roll.status}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Event log */}
          {events.length > 0 && (
            <div className="bg-[#111] border border-[#1e1e1e] rounded-xl overflow-hidden">
              <div className="px-5 py-3 border-b border-[#1e1e1e]">
                <p className="text-white text-sm font-medium">Activity</p>
              </div>
              <div className="divide-y divide-[#171717]">
                {events.map((ev: any) => (
                  <div key={ev.id} className="flex items-start gap-3 px-5 py-3">
                    <div className="w-1.5 h-1.5 rounded-full bg-[#333] mt-1.5 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-[#888] text-xs">{ev.description}</p>
                      <p className="text-[#444] text-[11px] mt-0.5">
                        {ev.actor_label} · {format(new Date(ev.created_at), 'd MMM HH:mm')}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Sidebar actions */}
        <div className="space-y-4">
          {/* Status actions */}
          {nextStatuses.length > 0 && (
            <div className="bg-[#111] border border-[#1e1e1e] rounded-xl p-5">
              <p className="text-[#555] text-xs uppercase tracking-wider mb-3">Update Status</p>
              <div className="space-y-2">
                {nextStatuses.map(s => (
                  <button
                    key={s}
                    onClick={() => statusMutation.mutate(s)}
                    disabled={statusMutation.isPending}
                    className="w-full flex items-center justify-between px-3 py-2.5 bg-[#0f0f0f] border border-[#2a2a2a] hover:border-[#ff6600]/50 text-[#888] hover:text-white rounded-lg text-sm transition-all"
                  >
                    <span className="capitalize">{s.replace('_', ' ')}</span>
                    <ChevronDown size={14} className="rotate-[-90deg]" />
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Email status */}
          <div className="bg-[#111] border border-[#1e1e1e] rounded-xl p-5 space-y-3">
            <p className="text-[#555] text-xs uppercase tracking-wider">Email Status</p>
            <div className="space-y-2 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-[#555]">Delivery</span>
                <span className={order.email_status ? 'text-green-400' : 'text-[#444]'}>
                  {order.email_status || 'Not sent'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[#555]">Blank notice</span>
                <span className={order.blank_email_status ? 'text-green-400' : 'text-[#444]'}>
                  {order.blank_email_status || 'Not sent'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[#555]">Print ready</span>
                <span className={order.print_ready_email_status ? 'text-green-400' : 'text-[#444]'}>
                  {order.print_ready_email_status || 'Not sent'}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
