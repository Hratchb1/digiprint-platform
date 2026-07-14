import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { refundWarningsApi, ordersApi, RefundWarning } from '../lib/api'
import { AlertTriangle, X, Search, EyeOff, Link2 } from 'lucide-react'
import { cn } from '../lib/cn'
import { formatRelative } from '../lib/format'
import StatusPill from './ui/StatusPill'

// Floating tray for unmatched Pronto refunds. The sync job parks refunds it
// can't auto-match in refund_warnings; staff either link them to the right
// order (applies the refund flow) or ignore them.
export default function RefundWarningsTray() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)

  const { data: warnings = [] } = useQuery({
    queryKey: ['refund-warnings'],
    queryFn: refundWarningsApi.list,
    refetchInterval: 60_000,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['refund-warnings'] })
    qc.invalidateQueries({ queryKey: ['orders'] })
    qc.invalidateQueries({ queryKey: ['dashboard'] })
  }

  if (warnings.length === 0) return null

  return (
    <>
      {/* Floating button */}
      <button
        onClick={() => setOpen(o => !o)}
        className="fixed bottom-5 right-5 z-40 flex items-center gap-2 px-4 py-2.5 rounded-full bg-[#1c1a0f] border border-yellow-500/40 text-yellow-400 text-sm font-medium shadow-lg hover:border-yellow-500/70 transition-all"
      >
        <AlertTriangle size={15} />
        {warnings.length} unmatched refund{warnings.length !== 1 ? 's' : ''}
      </button>

      {/* Tray panel */}
      {open && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <div className="relative w-full max-w-md h-full bg-[#0f0f0f] border-l border-[#2a2a2a] flex flex-col shadow-2xl">
            <div className="flex items-center justify-between px-5 py-4 border-b border-[#1e1e1e]">
              <div className="flex items-center gap-2">
                <AlertTriangle size={15} className="text-yellow-400" />
                <h2 className="text-white text-sm font-semibold">Unmatched refunds</h2>
                <span className="px-1.5 py-0.5 rounded bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 text-[11px] font-bold">
                  {warnings.length}
                </span>
              </div>
              <button onClick={() => setOpen(false)} className="text-[#555] hover:text-white transition-colors">
                <X size={16} />
              </button>
            </div>
            <p className="px-5 pt-3 text-[#555] text-xs">
              Pronto refunds that couldn't be matched to an order automatically.
              Link each one to the right order, or ignore it if it's not film-related.
            </p>
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {warnings.map(w => (
                <WarningCard key={w.id} warning={w} onDone={invalidate} />
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function WarningCard({ warning, onDone }: { warning: RefundWarning; onDone: () => void }) {
  const [mode, setMode] = useState<'idle' | 'resolve' | 'ignore'>('idle')
  const [search, setSearch] = useState('')
  const [notes, setNotes] = useState('')

  const { data: matches = [], isFetching: searching } = useQuery({
    queryKey: ['refund-warning-search', warning.id, search],
    queryFn: () => ordersApi.list({ search, limit: 5 }),
    enabled: mode === 'resolve' && search.trim().length >= 2,
  })

  const resolveMutation = useMutation({
    mutationFn: (orderId: string) =>
      refundWarningsApi.resolve(warning.id, orderId, notes.trim() || undefined),
    onSuccess: onDone,
  })

  const ignoreMutation = useMutation({
    mutationFn: () => refundWarningsApi.ignore(warning.id, notes.trim() || undefined),
    onSuccess: onDone,
  })

  const error = (resolveMutation.error || ignoreMutation.error) as any
  const lines = (warning.refund_lines as any[]) || []

  return (
    <div className="bg-[#111] border border-yellow-500/20 rounded-xl p-4">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div>
          <p className="text-white text-sm font-mono font-medium">
            #{warning.refund_pronto_order_number}
          </p>
          <p className="text-[#666] text-xs mt-0.5">
            {warning.pronto_account_number || 'Cash sale'}
            {warning.territory && <> · {warning.territory}</>}
            {' · '}{formatRelative(warning.created_at)}
          </p>
        </div>
        {warning.refund_amount != null && (
          <span className="text-red-400 text-sm font-mono font-medium flex-shrink-0">
            −${Math.abs(warning.refund_amount).toFixed(2)}
          </span>
        )}
      </div>

      {lines.length > 0 && (
        <div className="mb-3 space-y-0.5">
          {lines.slice(0, 3).map((l: any, i: number) => (
            <p key={i} className="text-[#555] text-xs truncate">
              {l.shipped_units != null && <span className="font-mono">{Math.abs(l.shipped_units)}× </span>}
              {l.product_name || l.sku_code}
            </p>
          ))}
          {lines.length > 3 && <p className="text-[#444] text-xs">+{lines.length - 3} more</p>}
        </div>
      )}

      {mode === 'idle' && (
        <div className="flex gap-2">
          <button
            onClick={() => setMode('resolve')}
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 bg-[#0f0f0f] border border-[#2a2a2a] hover:border-[#ff6600]/50 text-[#888] hover:text-white rounded-lg text-xs transition-all"
          >
            <Link2 size={12} /> Match to order
          </button>
          <button
            onClick={() => setMode('ignore')}
            className="flex items-center justify-center gap-1.5 px-3 py-1.5 bg-[#0f0f0f] border border-[#2a2a2a] hover:border-[#444] text-[#555] hover:text-[#888] rounded-lg text-xs transition-all"
          >
            <EyeOff size={12} /> Ignore
          </button>
        </div>
      )}

      {mode === 'resolve' && (
        <div className="space-y-2">
          <div className="relative">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#444]" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search order number or customer…"
              autoFocus
              className="w-full bg-[#0f0f0f] border border-[#2a2a2a] text-white text-xs rounded-lg pl-8 pr-3 py-2 focus:outline-none focus:border-[#ff6600] placeholder:text-[#333]"
            />
          </div>
          {searching && <p className="text-[#444] text-xs">Searching…</p>}
          {matches.map((o: any) => (
            <button
              key={o.id}
              onClick={() => resolveMutation.mutate(o.id)}
              disabled={resolveMutation.isPending}
              className="w-full flex items-center justify-between gap-2 px-3 py-2 bg-[#0f0f0f] border border-[#2a2a2a] hover:border-[#ff6600]/50 rounded-lg text-left transition-all disabled:opacity-40"
            >
              <div className="min-w-0">
                <p className="text-white text-xs font-mono truncate">#{o.order_number}</p>
                <p className="text-[#555] text-[11px] truncate">{o.customer_name}</p>
              </div>
              <StatusPill status={o.status} />
            </button>
          ))}
          {search.trim().length >= 2 && !searching && matches.length === 0 && (
            <p className="text-[#444] text-xs">No matching orders</p>
          )}
          <button onClick={() => setMode('idle')} className="text-[#555] hover:text-white text-xs transition-colors">
            Cancel
          </button>
        </div>
      )}

      {mode === 'ignore' && (
        <div className="space-y-2">
          <input
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="Why is this being ignored? (optional)"
            autoFocus
            className="w-full bg-[#0f0f0f] border border-[#2a2a2a] text-white text-xs rounded-lg px-3 py-2 focus:outline-none focus:border-[#ff6600] placeholder:text-[#333]"
          />
          <div className="flex gap-2">
            <button
              onClick={() => ignoreMutation.mutate()}
              disabled={ignoreMutation.isPending}
              className="flex-1 px-3 py-1.5 bg-[#1a1a1a] border border-[#2a2a2a] hover:border-[#444] text-[#888] hover:text-white rounded-lg text-xs transition-all disabled:opacity-40"
            >
              {ignoreMutation.isPending ? 'Ignoring…' : 'Confirm ignore'}
            </button>
            <button onClick={() => setMode('idle')} className="text-[#555] hover:text-white text-xs transition-colors px-2">
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && (
        <p className="text-red-400 text-xs mt-2">
          {error?.response?.data?.detail || 'Action failed — try again'}
        </p>
      )}
    </div>
  )
}
