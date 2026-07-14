import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { ordersApi, rollsApi, emailsApi, driveApi, DiscardReason } from '../lib/api'
import { useState } from 'react'
import { ArrowLeft, FilmIcon, ExternalLink, AlertTriangle, ChevronDown, RefreshCw, CheckCircle, XCircle, Loader2, Mail, Pencil, Phone, Trash2 } from 'lucide-react'
import { format } from 'date-fns'
import clsx from 'clsx'
import {
  NEXT_STATUSES, ACTIVE_STATUSES, OrderStatus, statusLabel, statusStyle,
  displayRollStatus, rollStatusStyle,
} from '../lib/status'
import DiscardModal, { DISCARD_REASON_LABELS } from '../components/DiscardModal'
import RefundBanner from '../components/RefundBanner'

// Twin editing allowed on all statuses — collision check enforced on the backend

function getNotifyButtonLabel(order: any): string | null {
  if (order.status === 'delivered') return null
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
  const [editingTwin, setEditingTwin] = useState<string | null>(null)
  const [twinValue, setTwinValue] = useState('')
  const [twinError, setTwinError] = useState('')
  const [showDiscardModal, setShowDiscardModal] = useState(false)

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
    queryFn: () => driveApi.logForOrder(id!),
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
    setTimeout(() => setEmailToast(null), 5000)
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
    mutationFn: () => ordersApi.retryBorder(id!),
    onSuccess: invalidate,
  })

  const resetTwinsMutation = useMutation({
    mutationFn: () => ordersApi.resetTwins(id!),
    onSuccess: invalidate,
  })

  const discardMutation = useMutation({
    mutationFn: ({ reason, notes }: { reason: DiscardReason; notes?: string }) =>
      ordersApi.discard(id!, reason, notes),
    onSuccess: () => {
      setShowDiscardModal(false)
      showToast('success', 'Order discarded — twin checks released')
      invalidate()
    },
    onError: (err: any) =>
      showToast('error', err?.response?.data?.detail || 'Failed to discard order'),
  })

  const sendEmailMutation = useMutation({
    mutationFn: () => emailsApi.send(id!),
    onSuccess: async () => {
      try {
        await ordersApi.updateStatus(id!, 'delivered')
      } catch { /* non-fatal */ }
      showToast('success', 'Customer notified — order marked as delivered')
      invalidate()
    },
    onError: () => showToast('error', 'Failed to send email — check the activity log'),
  })

  const resendEmailMutation = useMutation({
    mutationFn: () => emailsApi.resend(id!),
    onSuccess: () => { showToast('success', 'Email resent successfully'); invalidate() },
    onError: () => showToast('error', 'Failed to resend email — check the activity log'),
  })

  const approveRescanMutation = useMutation({
    mutationFn: (folderId: string) => driveApi.clearLogEntry(folderId),
    onSuccess: () => { showToast('success', 'Rescan approved — watcher will reprocess on next cycle'); invalidate() },
    onError: () => showToast('error', 'Failed to approve rescan'),
  })

  const twinMutation = useMutation({
    mutationFn: ({ rollId, twin }: { rollId: string; twin: string }) =>
      rollsApi.updateTwinCheck(rollId, twin),
    onSuccess: () => {
      setEditingTwin(null)
      setTwinValue('')
      setTwinError('')
      showToast('success', 'Twin updated. If a scan folder is already in the Inbox under the old twin, rename it manually.')
      invalidate()
    },
    onError: (err: any) => {
      showToast('error', err?.response?.data?.detail || 'Failed to update twin check')
    },
  })

  if (isLoading) return <div className="p-8 text-[#444] text-sm">Loading…</div>
  if (!order) return <div className="p-8 text-[#ff4444] text-sm">Order not found</div>

  const nextStatuses = NEXT_STATUSES[order.status as OrderStatus] || []
  const turnaround = order.date_delivered && order.created_at
    ? ((new Date(order.date_delivered).getTime() - new Date(order.created_at).getTime()) / 3600000).toFixed(1)
    : null

  const borderStatus = order.border_scan_status as string | null
  const hasBorderScan = order.border_scan === true
  const hasArchivedTwins = order.rolls?.some((r: any) => r.status === 'archived')

  const notifyButtonLabel = getNotifyButtonLabel(order)
  const isDelivered = order.status === 'delivered'
  const emailFailed = order.email_status === 'failed'
  const isDiscarded = order.status === 'discarded'
  const canDiscard = ACTIVE_STATUSES.includes(order.status)

  return (
    <div className="p-6 lg:p-8 max-w-5xl mx-auto">

      {/* Toast */}
      {emailToast && (
        <div className={clsx(
          'fixed top-6 right-6 z-50 max-w-sm px-4 py-3 rounded-xl border text-sm font-medium shadow-lg',
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

          {/* Refund warning (set by Pronto sync) */}
          {order.refund_status && (
            <RefundBanner refundStatus={order.refund_status} refundAmount={order.refund_amount} />
          )}

          {/* Discarded banner */}
          {isDiscarded && (
            <div className="bg-red-500/5 border border-red-500/25 rounded-xl p-4 flex items-start gap-3">
              <Trash2 size={15} className="text-red-400 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-red-400 text-sm font-medium">
                  Order discarded
                  {order.discard_reason && (
                    <span className="ml-2 text-red-300/80 font-normal">
                      — {DISCARD_REASON_LABELS[order.discard_reason as DiscardReason] ?? order.discard_reason}
                    </span>
                  )}
                </p>
                <p className="text-[#666] text-xs mt-0.5">
                  {order.discarded_by && <>By {order.discarded_by}</>}
                  {order.discarded_at && <> · {format(new Date(order.discarded_at), 'd MMM yyyy, HH:mm')}</>}
                </p>
                {order.discard_notes && (
                  <p className="text-[#888] text-xs mt-1.5">{order.discard_notes}</p>
                )}
              </div>
            </div>
          )}

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

            {/* Top row: order number chip + status */}
            <div className="flex items-center justify-between gap-4 mb-4">
              <div className="flex items-center gap-2">
                <span className="px-2.5 py-1 rounded-lg bg-[#1a1a1a] border border-[#2a2a2a] text-[#666] text-xs font-mono">
                  #{order.order_number}
                </span>
                {order.manual_entry && (
                  <span className="px-2 py-0.5 rounded text-[11px] font-medium text-orange-300 border border-orange-500/30" style={{ backgroundColor: '#431a00' }}>
                    Manual
                  </span>
                )}
              </div>
              <span className={clsx(
                'px-3 py-1 rounded-full text-xs font-medium border',
                statusStyle(order.status)
              )}>
                {statusLabel(order.status)}
              </span>
            </div>

            {/* Customer name — dominant heading */}
            <h1 className="text-white text-3xl font-bold mb-1">{order.customer_name}</h1>

            {/* Account — secondary chip */}
            {order.account ? (
              <div className="mb-5">
                <span className="inline-block px-2.5 py-0.5 rounded-full bg-[#1f0e00] border border-[#ff6600]/25 text-[#ff6600] text-xs font-medium">
                  {order.account}
                </span>
              </div>
            ) : (
              <div className="mb-5" />
            )}

            {/* Details grid */}
            <div className="grid grid-cols-2 gap-x-6 gap-y-4 text-sm">
              <div>
                <p className="text-[#444] text-xs mb-0.5">Email</p>
                <p className="text-[#888]">{order.customer_email || '—'}</p>
              </div>
              <div>
                <p className="text-[#444] text-xs mb-0.5">Phone</p>
                {order.phone_number ? (
                  <a
                    href={`tel:${order.phone_number}`}
                    className="flex items-center gap-1.5 text-[#888] hover:text-white transition-colors"
                  >
                    <Phone size={12} className="text-[#555]" />
                    {order.phone_number}
                  </a>
                ) : (
                  <p className="text-[#444]">—</p>
                )}
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
            </div>

            {/* Drive link */}
            {order.drive_order_folder_url ? (
              <a href={order.drive_order_folder_url} target="_blank" rel="noopener noreferrer"
                className="mt-5 flex items-center gap-2 text-[#ff6600] hover:text-[#ff8833] text-sm transition-colors">
                <ExternalLink size={14} /> Open Drive folder
              </a>
            ) : (
              <div className="mt-5">
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
              {order.rolls?.map((roll: any) => {
                const isEditable = true
                const isEditing = editingTwin === roll.id
                return (
                  <div key={roll.id} className={clsx('flex items-center gap-3 px-5 py-3', roll.is_blank && 'bg-red-500/5')}>
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

                    {/* Twin check — inline edit or static */}
                    {isEditing ? (
                      <div className="flex items-center gap-1.5 flex-shrink-0">
                        <input
                          type="text"
                          maxLength={4}
                          value={twinValue}
                          onChange={e => { setTwinValue(e.target.value); setTwinError('') }}
                          className={clsx(
                            'w-14 font-mono text-sm bg-[#0f0f0f] border rounded px-2 py-0.5 focus:outline-none',
                            twinError ? 'border-red-500 text-red-400' : 'border-[#ff6600] text-white'
                          )}
                          autoFocus
                          onKeyDown={e => {
                            if (e.key === 'Escape') { setEditingTwin(null); setTwinValue(''); setTwinError('') }
                            if (e.key === 'Enter') {
                              if (!/^\d{4}$/.test(twinValue)) { setTwinError('4 digits required'); return }
                              twinMutation.mutate({ rollId: roll.id, twin: twinValue })
                            }
                          }}
                        />
                        <button
                          onClick={() => {
                            if (!/^\d{4}$/.test(twinValue)) { setTwinError('4 digits required'); return }
                            twinMutation.mutate({ rollId: roll.id, twin: twinValue })
                          }}
                          disabled={twinMutation.isPending}
                          className="text-[#ff6600] hover:text-white text-xs px-2 py-0.5 border border-[#ff6600]/30 rounded transition-colors disabled:opacity-40"
                        >
                          {twinMutation.isPending ? '…' : 'Save'}
                        </button>
                        <button
                          onClick={() => { setEditingTwin(null); setTwinValue(''); setTwinError('') }}
                          className="text-[#444] hover:text-white text-xs"
                        >
                          Cancel
                        </button>
                        {twinError && <span className="text-red-400 text-[11px]">{twinError}</span>}
                      </div>
                    ) : (
                      <div className="flex items-center gap-1 flex-shrink-0 w-16">
                        <span className="font-mono text-white text-sm">{roll.twin_check}</span>
                        {isEditable && (
                          <button
                            onClick={() => { setEditingTwin(roll.id); setTwinValue(roll.twin_check); setTwinError('') }}
                            className="text-[#2a2a2a] hover:text-[#ff6600] transition-colors ml-0.5"
                            title="Edit twin check"
                          >
                            <Pencil size={11} />
                          </button>
                        )}
                      </div>
                    )}

                    <span className="text-[#555] text-xs flex-1">{roll.service_type}</span>
                    {roll.is_blank && (
                      <span className="px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 border border-red-500/20 text-[11px]">Blank</span>
                    )}
                    <span className={clsx('px-2 py-0.5 rounded-full text-[11px] border', rollStatusStyle(roll.status))}>
                      {displayRollStatus(roll.status)}
                    </span>
                  </div>
                )
              })}
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
                    <span>{statusLabel(s)}</span>
                    <ChevronDown size={14} className="rotate-[-90deg]" />
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Email Actions */}
          <div className="bg-[#111] border border-[#1e1e1e] rounded-xl p-5 space-y-3">
            <p className="text-[#555] text-xs uppercase tracking-wider">Email</p>

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

          {/* Discard — remove a mis-entered order from the pipeline */}
          {canDiscard && (
            <div className="bg-[#111] border border-[#1e1e1e] rounded-xl p-5">
              <p className="text-[#555] text-xs uppercase tracking-wider mb-2">Discard</p>
              <p className="text-[#444] text-xs mb-3">
                Remove this order from the pipeline if it should never have been created — e.g. a
                charge correction or duplicate sale. Twin checks are released.
              </p>
              <button
                onClick={() => setShowDiscardModal(true)}
                className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-[#0f0f0f] border border-[#2a2a2a] hover:border-red-500/40 text-[#555] hover:text-red-400 rounded-lg text-xs transition-all"
              >
                <Trash2 size={12} /> Discard Order
              </button>
            </div>
          )}

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

      {/* Discard modal */}
      {showDiscardModal && (
        <DiscardModal
          orderNumber={order.order_number}
          isPending={discardMutation.isPending}
          onConfirm={(reason, notes) => discardMutation.mutate({ reason, notes })}
          onClose={() => setShowDiscardModal(false)}
        />
      )}
    </div>
  )
}
