import { useState } from 'react'
import { Trash2, X } from 'lucide-react'
import { DiscardReason } from '../lib/api'
import { cn } from '../lib/cn'

export const DISCARD_REASON_LABELS: Record<DiscardReason, string> = {
  charge_correction: 'Charge correction',
  add_on_existing:   'Add-on to an existing order',
  not_film_related:  'Not film related',
  duplicate_sale:    'Duplicate sale',
  other:             'Other',
}

interface DiscardModalProps {
  orderNumber: string
  isPending?: boolean
  onConfirm: (reason: DiscardReason, notes?: string) => void
  onClose: () => void
}

export default function DiscardModal({ orderNumber, isPending = false, onConfirm, onClose }: DiscardModalProps) {
  const [reason, setReason] = useState<DiscardReason | ''>('')
  const [notes, setNotes] = useState('')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      <div className="relative w-full max-w-md bg-[#111] border border-[#2a2a2a] rounded-xl p-6 shadow-2xl">
        <div className="flex items-start justify-between mb-1">
          <div className="flex items-center gap-2">
            <Trash2 size={16} className="text-red-400" />
            <h2 className="text-white text-base font-semibold">Discard order</h2>
          </div>
          <button onClick={onClose} className="text-[#555] hover:text-white transition-colors">
            <X size={16} />
          </button>
        </div>

        <p className="text-[#666] text-xs mb-5">
          <span className="font-mono text-[#888]">#{orderNumber}</span> will be removed from the
          pipeline and its twin checks released. This can't be undone from the UI.
        </p>

        <p className="text-[#555] text-xs uppercase tracking-wider mb-2">Reason</p>
        <div className="space-y-1.5 mb-4">
          {(Object.keys(DISCARD_REASON_LABELS) as DiscardReason[]).map(r => (
            <button
              key={r}
              onClick={() => setReason(r)}
              className={cn(
                'w-full text-left px-3 py-2 rounded-lg border text-sm transition-all',
                reason === r
                  ? 'bg-red-500/10 border-red-500/40 text-red-300'
                  : 'bg-[#0f0f0f] border-[#2a2a2a] text-[#888] hover:text-white hover:border-[#444]',
              )}
            >
              {DISCARD_REASON_LABELS[r]}
            </button>
          ))}
        </div>

        <textarea
          value={notes}
          onChange={e => setNotes(e.target.value)}
          placeholder="Notes (optional)…"
          rows={2}
          className="w-full bg-[#0f0f0f] border border-[#2a2a2a] text-white text-sm rounded-lg px-3 py-2 mb-5 focus:outline-none focus:border-[#ff6600] placeholder:text-[#333] resize-none"
        />

        <div className="flex gap-2 justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-[#888] hover:text-white text-sm transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => reason && onConfirm(reason, notes.trim() || undefined)}
            disabled={!reason || isPending}
            className="px-4 py-2 bg-red-500/10 border border-red-500/40 hover:bg-red-500/20 text-red-300 rounded-lg text-sm font-medium transition-all disabled:opacity-40"
          >
            {isPending ? 'Discarding…' : 'Discard order'}
          </button>
        </div>
      </div>
    </div>
  )
}
