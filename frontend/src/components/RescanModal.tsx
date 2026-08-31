import { useState } from 'react'
import { RefreshCw, X } from 'lucide-react'

interface RescanRoll {
  id: string
  twin_check: string | null
  service_type: string
}

interface RescanModalProps {
  orderNumber: string
  rolls: RescanRoll[]
  isPending?: boolean
  onConfirm: (rollIds: string[]) => void
  onClose: () => void
}

export default function RescanModal({ orderNumber, rolls, isPending = false, onConfirm, onClose }: RescanModalProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const toggle = (id: string) => {
    const next = new Set(selected)
    next.has(id) ? next.delete(id) : next.add(id)
    setSelected(next)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      <div className="relative w-full max-w-md bg-[#111] border border-[#2a2a2a] rounded-xl p-6 shadow-2xl">
        <div className="flex items-start justify-between mb-1">
          <div className="flex items-center gap-2">
            <RefreshCw size={16} className="text-[#ff6600]" />
            <h2 className="text-white text-base font-semibold">Rescan</h2>
          </div>
          <button onClick={onClose} className="text-[#555] hover:text-white transition-colors">
            <X size={16} />
          </button>
        </div>

        <p className="text-[#666] text-xs mb-4">
          Select which rolls from <span className="font-mono text-[#888]">#{orderNumber}</span> need
          rescanning — the label goes on the sleeve, never the negative, and never passes through
          chemistry. This creates a new linked order with fresh twin checks; the originals are
          unchanged.
        </p>

        <div className="space-y-1.5 mb-5 max-h-56 overflow-y-auto">
          {rolls.map(roll => (
            <label
              key={roll.id}
              className="flex items-center gap-3 px-3 py-2 rounded-lg border border-[#2a2a2a] bg-[#0f0f0f] cursor-pointer hover:border-[#444] transition-colors"
            >
              <input
                type="checkbox"
                checked={selected.has(roll.id)}
                onChange={() => toggle(roll.id)}
                className="accent-[#ff6600]"
              />
              <span className="font-mono text-white text-sm">{roll.twin_check ?? '—'}</span>
              <span className="text-[#555] text-xs">{roll.service_type}</span>
            </label>
          ))}
          {rolls.length === 0 && (
            <p className="text-[#444] text-xs px-1">No rolls on this order to rescan.</p>
          )}
        </div>

        <div className="flex gap-2 justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-[#888] hover:text-white text-sm transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => selected.size > 0 && onConfirm([...selected])}
            disabled={selected.size === 0 || isPending}
            className="px-4 py-2 bg-[#ff6600]/10 border border-[#ff6600]/40 hover:bg-[#ff6600]/20 text-[#ff8833] rounded-lg text-sm font-medium transition-all disabled:opacity-40"
          >
            {isPending ? 'Creating…' : `Rescan ${selected.size || ''} roll${selected.size !== 1 ? 's' : ''}`}
          </button>
        </div>
      </div>
    </div>
  )
}
