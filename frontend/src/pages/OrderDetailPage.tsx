import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { ordersApi } from '../lib/api'
import { useState } from 'react'
import { ArrowLeft, FilmIcon, ExternalLink, AlertTriangle, ChevronDown, RefreshCw, CheckCircle, XCircle, Loader2, Mail } from 'lucide-react'
import { format } from 'date-fns'
import clsx from 'clsx'

const STATUS_STYLES: Record<string, string> = {
  booked:      'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
  processing:  'bg-blue-500/10 text-blue-400 border-blue-500/20',
  scanned:     'bg-purple-500/10 text-purple-400 border-purple-500/20',
  delivered:   'bg-green-500/10 text-green-400 border-green-500/20',
  blank:       'bg-red-500/10 text-red-400 border-red-500/20',
  print_ready: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
  archived:    'bg-green-500/10 text-green-400 border-green-500/20',
}

const NEXT_STATUSES: Record<string, string[]> = {
  booked:      ['processing', 'scanned', 'delivered', 'cancelled'],
  processing:  ['scanned', 'delivered', 'cancelled'],
  scanned:     ['delivered', 'print_ready', 'cancelled'],
  print_ready: ['delivered'],
}

function displayRollStatus(status: string): string {
  if (status === 'archived') return 'delivered'
  return status
}

// Determine manual notify button label for Dev only / Print only orders
function getNotifyButtonLabel(order: any): string | null {
  if (order.status === 'delivered') return null  // already delivered — use resend instead
  const rolls = order.rolls || []
  const serviceTypes = [...new Set(rolls.map((r: any) => r.service_type))] as string[]
  const isDevOnly = serviceTypes.length > 0 && serviceTypes.every(s => s === 'Dev only')
  const isPrintOnly = order.is_print_only || (serviceTypes.length > 0 && serviceTypes.every(s => s === 'Print only'))
  if (isDevOnly) return 'Notify: Negatives Ready'
  if (isPrintOnly) return 'Notify: Prints Ready'
  return null
}

export default function OrderDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [driveLink, setDriveLink] = useState('')
  const [showDriveInput, setShowDriveInput] = useState(false)
  const [selectedRolls, setSelectedRolls] = useState<Set<string>>(new Set())
  const [emailToast, setEmailToast] = useState<{ type: 'success' | 'error', message: string } | null>(null)

  const { data: order, isLoading } = useQuery({
    queryKey: ['order', id],
    queryFn: () => ordersApi.get(id!),
    enabled: !!id,
    refetchInterval: (data: any) =>
      data?.border_scan_status === 'processing' ? 10000 : false,
  })

  const { data: events = [] } = useQuery({
    queryKey: ['order-events', id],
    queryFn: () => ordersApi.events(id!),
    enabled: !!id,
  })

  const { data: rescanData } = useQuery({
    queryKey: ['order-rescans', id],
    queryFn: () => fetch(`/api/drive/log/order/${id}`).then(r => r.json()),
    enabled: !!id,
  })
  const rescans = rescanData?.rescans || []

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['order', id] })
    qc.invalidateQueries({ queryKey: ['order-events', id] })
    qc.invalidateQueries({ queryKey: ['orders-recent'] })
    qc.invalidateQueries({ queryKey: ['order-rescans', id] })
  }

  const showToast = (type: 'success' | 'error', message: string) => {
    setEmailToast({ type, message })
    setTimeout(() => setEmailToast(null), 4000)
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

  const retryBorderMutation = useMutation({
    mutationFn: () => fetch(`/api/orders/${id}/retry-border`, { method: 'POST' }).then(r => {
      if (!r.ok) throw new Error('Retry failed')
      return r.json()
    }),
    onSuccess: invalidate,
  })

  const resetTwinsMutation = useMutation({
    mutationFn: () => fetch(`/api/orders/${id}/reset-twins`, { method: 'POST' }).then(r => {
      if (!r.ok) throw new Error('Reset failed')
      return r.json()
    }),
    onSuccess: invalidate,
  })

  // Send manual notification email (Dev only / Print only)
  // On success: also mark order as delivered
  const sendEmailMutation = useMutation({
    mutationFn: () => fetch(`/api/emails/send/${id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    }).then(r => {
      if (!r.ok) throw new Error('Email failed to send')
      return r.json()
    }),
    onSuccess: async () => {
      // Auto-deliver the order when notification is sent
      try {
        await ordersApi.updateStatus(id!, 'delivered')
      } catch { /* non-fatal */ }
      showToast('success', 'Customer notified — order marked as delivered')
      invalidate()
    },
    onError: () => showToast('error', 'Failed to send email — check the activity log'),
  })

  const resendEmailMutation = useMutation({
    mutationFn: () => fetch(`/api/emails/resend/${id}`, { method: 'POST' }).then(r => {
      if (!r.ok) throw new Error('Resend failed')
      return r.json()
    }),
    onSuccess: () => { showToast('success', 'Email resent successfully'); invalidate() },
    onError: () => showToast('error', 'Failed to resend email — check the activity log'),
  })

  const approveRescanMutation = useMutation({
    mutationFn: (folderId: string) => fetch(`/api/drive/log/${folderId}`, { method: 'DELETE' }).then(r => {
      if (!r.ok) throw new Error('Approval failed')
      return r.json()
    }),
    onSuccess: () => { showToast('success', 'Rescan approved — watcher will reprocess on next cycle'); invalidate() },
    onError: () => showToast('error', 'Failed to approve rescan'),
  })

  if (isLoading) return <div className="p-8 text-[#444] text-sm">Loading…</div>
  if (!order) return <div className="p-8 text-[#ff4444] text-sm">Order not found</div>

  const nextStatuses = NEXT_STATUSES[order.status] || []
  const turnaround = order.date_delivered && order.created_at
    ? ((new Date(order.date_delivered).getTime() - new Date(order.created_at).getTime()) / 3600000).toFixed(1)
    : null

  const borderStatus = order.border_scan_status as string | null
  const hasBorderScan = order.border_scan === true
  const hasArchivedTwins = order.rolls?.some((r: any) => r.status === 'archived')

  // Email button logic
  const notifyButtonLabel = getNotifyButtonLabel(order)
  const isDelivered = order.status === 'delivered'
  const emailFailed = order.email_status === 'failed'

  return (
    <div className="p-6 lg:p-8 max-w-5xl mx-auto">

      {/* Toast */}
      {emailToast && (
        <div className={clsx(
          'fixed top-6 right-6 z-50 px-4 py-3 rounded-xl border text-sm font-medium shadow-lg',
          emailToast.type === 'success'
            ? 'bg-green-500/10 border-green-500/30 text-green-400'
            : 'bg-red-500/10 border-red-500/30 text-red-400'
        )}>
          {emailToast.message}
        </div>
      )}

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

          {/* Rescan alert cards */}
          {rescans.map((rescan: any) => (
            <div key={rescan.id} className="bg-yellow-500/5 border border-yellow-500/20 rounded-xl p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3">
                  <AlertTriangle size={15} className="text-yellow-400 mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="text-yellow-400 text-sm font-medium mb-1">Rescan detected</p>
                    <p className="text-[#666] text-xs">
                      Folder <span className="font-mono text-[#888]">{rescan.folder_name || rescan.folder_id}</span> was
                      detected in the Inbox again. Approve to allow the watcher to reprocess it on the next cycle.
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => approveRescanMutation.mutate(rescan.folder_id)}
                  disabled={approveRescanMutation.isPending}
                  className="flex-shrink-0 px-3 py-1.5 bg-yellow-500/10 border border-yellow-500/30 hover:border-yellow-500/60 text-yellow-400 hover:text-yellow-300 rounded-lg text-xs transition-all disabled:opacity-40"
                >
                  {approveRescanMutation.isPending ? 'Approving…' : 'Approve'}
                </button>
              </div>
            </div>
          ))}

          {/* Order header card */}
          <div className="bg-[#111] border border-[#1e1e1e] rounded-xl p-6">
            <div className="flex items-start justify-between gap-4 mb-4">
              <div>
                <p className="text-[#555] text-xs uppercase tracking-wider mb-1">Order</p>
                <div className="flex items-center gap-2">
                  <h1 className="text-white text-xl font-bold font-mono">{order.order_number}</h1>
                  {order.manual_entry && (
                    <span className="px-2 py-0.5 rounded text-[11px] font-medium text-orange-300 border border-orange-500/30" style={{ backgroundColor: '#431a00' }}>
                      Manual
                    </span>
                  )}
                </div>
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
              <a href={order.drive_order_folder_url} target="_blank" rel="noopener noreferrer"
                className="mt-4 flex items-center gap-2 text-[#ff6600] hover:text-[#ff8833] text-sm transition-colors">
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
                    <button onClick={() => driveLink && driveMutation.mutate(driveLink)} disabled={!driveLink || driveMutation.isPending}
                      className="px-3 py-2 bg-[#ff6600] text-white rounded-lg text-sm disabled:opacity-40">Save</button>
                    <button onClick={() => setShowDriveInput(false)} className="px-3 py-2 text-[#555] hover:text-white text-sm">Cancel</button>
                  </div>
                ) : (
                  <button onClick={() => setShowDriveInput(true)} className="text-[#444] hover:text-[#888] text-sm transition-colors">
                    + Add Drive folder link
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Border Scan Card */}
          {hasBorderScan && (
            <div className={clsx(
              'border rounded-xl p-5',
              borderStatus === 'failed' ? 'bg-red-500/5 border-red-500/20'
                : borderStatus === 'complete' ? 'bg-[#111] border-green-500/20'
                : 'bg-[#111] border-[#1e1e1e]'
            )}>
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  {borderStatus === 'complete'   && <CheckCircle size={15} className="text-green-400" />}
                  {borderStatus === 'failed'     && <XCircle size={15} className="text-red-400" />}
                  {borderStatus === 'processing' && <Loader2 size={15} className="text-blue-400 animate-spin" />}
                  {!borderStatus                 && <RefreshCw size={15} className="text-[#555]" />}
                  <p className="text-white text-sm font-medium">Border Scans</p>
                </div>
                <span className={clsx(
                  'px-2.5 py-0.5 rounded-full text-[11px] font-medium border',
                  borderStatus === 'complete'   && 'bg-green-500/10 text-green-400 border-green-500/20',
                  borderStatus === 'processing' && 'bg-blue-500/10 text-blue-400 border-blue-500/20',
                  borderStatus === 'failed'     && 'bg-red-500/10 text-red-400 border-red-500/20',
                  !borderStatus                 && 'bg-[#1a1a1a] text-[#555] border-[#2a2a2a]',
                )}>
                  {borderStatus ?? 'pending'}
                </span>
              </div>
              {borderStatus === 'processing' && (
                <p className="text-[#555] text-xs mb-3">Applying film borders — usually 1–3 minutes.</p>
              )}
              {borderStatus === 'complete' && order.bordered_scans_drive_url && (
                <a href={order.bordered_scans_drive_url} target="_blank" rel="noopener noreferrer"
                  className="flex items-center gap-2 text-[#ff6600] hover:text-[#ff8833] text-sm transition-colors">
                  <ExternalLink size={14} /> Open Bordered Scans folder
                </a>
              )}
              {borderStatus === 'failed' && (
                <div className="flex items-center justify-between">
                  <p className="text-red-400 text-xs">Border processing failed. Check the activity log.</p>
                  <button
                    onClick={() => retryBorderMutation.mutate()}
                    disabled={retryBorderMutation.isPending}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-[#1a1a1a] border border-[#2a2a2a] hover:border-[#ff6600]/50 text-[#888] hover:text-white rounded-lg text-xs transition-all disabled:opacity-40"
                  >
                    <RefreshCw size={12} className={retryBorderMutation.isPending ? 'animate-spin' : ''} />
                    Retry
                  </button>
                </div>
              )}
            </div>
          )}

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
                <div key={roll.id} className={clsx('flex items-center gap-4 px-5 py-3', roll.is_blank && 'bg-red-500/5')}>
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
                    <span className="px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 border border-red-500/20 text-[11px]">Blank</span>
                  )}
                  <span className={clsx('px-2 py-0.5 rounded-full text-[11px] border', STATUS_STYLES[roll.status] || 'bg-[#1a1a1a] text-[#555] border-[#2a2a2a]')}>
                    {displayRollStatus(roll.status)}
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
                      <p className="text-[#444] text-[11px] mt-0.5">{ev.actor_label} · {format(new Date(ev.created_at), 'd MMM HH:mm')}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Sidebar */}
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

          {/* Email Actions */}
          <div className="bg-[#111] border border-[#1e1e1e] rounded-xl p-5 space-y-3">
            <p className="text-[#555] text-xs uppercase tracking-wider">Email</p>

            {/* Notify button — Dev only / Print only, not yet delivered */}
            {notifyButtonLabel && (
              <button
                onClick={() => sendEmailMutation.mutate()}
                disabled={sendEmailMutation.isPending}
                className="w-full flex items-center justify-between px-3 py-2.5 bg-[#0f0f0f] border border-[#2a2a2a] hover:border-[#ff6600]/50 text-[#888] hover:text-white rounded-lg text-sm transition-all disabled:opacity-40"
              >
                <span className="flex items-center gap-2">
                  <Mail size={13} />
                  {sendEmailMutation.isPending ? 'Sending…' : notifyButtonLabel}
                </span>
                <ChevronDown size={14} className="rotate-[-90deg]" />
              </button>
            )}

            {/* Failed email — resend (red) */}
            {emailFailed && (
              <button
                onClick={() => resendEmailMutation.mutate()}
                disabled={resendEmailMutation.isPending}
                className="w-full flex items-center justify-between px-3 py-2.5 bg-red-500/5 border border-red-500/20 hover:border-red-500/40 text-red-400 hover:text-red-300 rounded-lg text-sm transition-all disabled:opacity-40"
              >
                <span className="flex items-center gap-2">
                  <Mail size={13} />
                  {resendEmailMutation.isPending ? 'Resending…' : 'Resend Email'}
                </span>
                <ChevronDown size={14} className="rotate-[-90deg]" />
              </button>
            )}

            {/* Resend — always shown for delivered orders */}
            {isDelivered && !emailFailed && (
              <button
                onClick={() => resendEmailMutation.mutate()}
                disabled={resendEmailMutation.isPending}
                className="w-full flex items-center justify-between px-3 py-2.5 bg-[#0f0f0f] border border-[#2a2a2a] hover:border-[#ff6600]/50 text-[#555] hover:text-[#888] rounded-lg text-sm transition-all disabled:opacity-40"
              >
                <span className="flex items-center gap-2">
                  <Mail size={13} />
                  {resendEmailMutation.isPending ? 'Resending…' : 'Resend Email'}
                </span>
                <ChevronDown size={14} className="rotate-[-90deg]" />
              </button>
            )}

            {/* Email status rows */}
            <div className="space-y-2 text-xs pt-1 border-t border-[#1a1a1a]">
              <div className="flex items-center justify-between">
                <span className="text-[#555]">Delivery</span>
                <span className={emailFailed ? 'text-red-400' : order.email_status ? 'text-green-400' : 'text-[#444]'}>
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

          {/* Admin — Reset Twin Checks */}
          {hasArchivedTwins && (
            <div className="bg-[#111] border border-[#2a2a2a] rounded-xl p-5">
              <p className="text-[#555] text-xs uppercase tracking-wider mb-2">Admin</p>
              <p className="text-[#444] text-xs mb-3">
                Twin checks on this order have been released. Use this only if they need to be re-locked — e.g. if the order was marked delivered by mistake.
              </p>
              <button
                onClick={() => {
                  if (window.confirm('Reset twin checks on this order? This will re-lock the twin numbers and prevent them from being reused until this order is delivered again.')) {
                    resetTwinsMutation.mutate()
                  }
                }}
                disabled={resetTwinsMutation.isPending}
                className="w-full px-3 py-2 bg-[#0f0f0f] border border-[#2a2a2a] hover:border-red-500/30 text-[#555] hover:text-red-400 rounded-lg text-xs transition-all disabled:opacity-40"
              >
                {resetTwinsMutation.isPending ? 'Resetting…' : 'Reset Twin Checks'}
              </button>
            </div>
          )}

        </div>
      </div>
    </div>
  )
}
