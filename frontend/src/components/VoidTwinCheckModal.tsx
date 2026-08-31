import { useState } from 'react'
import { Ban, X } from 'lucide-react'

interface VoidTwinCheckModalProps {
  twinCheck: string
  isPending?: boolean
  onConfirm: (reason: string) => void
  onClose: () => void
}

export default function VoidTwinCheckModal({ twinCheck, isPending = false, onConfirm, onClose }: VoidTwinCheckModalProps) {
  const [reason, setReason] = useState('')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      <div className="relative w-full max-w-md bg-[#111] border border-[#2a2a2a] rounded-xl p-6 shadow-2xl">
        <div className="flex items-start justify-between mb-1">
          <div className="flex items-center gap-2">
            <Ban size={16} className="text-red-400" />
            <h2 className="text-white text-base font-semibold">Void twin check</h2>
          </div>
          <button onClick={onClose} className="text-[#555] hover:text-white transition-colors">
            <X size={16} />
          </button>
        </div>

        <p className="text-[#666] text-xs mb-5">
          <span className="font-mono text-[#888]">{twinCheck}</span> will be burned — it is never
          reissued, even after the sequence wraps. The roll is reset so it can be reallocated or
          retyped.
        </p>

        <p className="text-[#555] text-xs uppercase tracking-wider mb-2">Reason</p>
        <textarea
          value={reason}
          onChange={e => setReason(e.target.value)}
          placeholder="e.g. misprint, wrong roll picked up…"
          rows={2}
          autoFocus
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
            onClick={() => reason.trim() && onConfirm(reason.trim())}
            disabled={!reason.trim() || isPending}
            className="px-4 py-2 bg-red-500/10 border border-red-500/40 hover:bg-red-500/20 text-red-300 rounded-lg text-sm font-medium transition-all disabled:opacity-40"
          >
            {isPending ? 'Voiding…' : 'Void twin check'}
          </button>
        </div>
      </div>
    </div>
  )
}
