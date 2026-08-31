// src/pages/TwinCheckAdminPage.tsx
//
// Admin-only: per-store auto_enabled toggle for twin check allocation, plus
// read-only visibility of current_value/cycle. Deliberately minimal — no
// history, no manual override of current_value from the UI (that's a SQL
// job for a real incident, not a button that invites mistakes).
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Zap, Loader2 } from 'lucide-react'
import { twinCheckSequencesApi, storesApi } from '../lib/api'
import { useAuth } from '../hooks/useAuth'

export default function TwinCheckAdminPage() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [toastMsg, setToastMsg] = useState<string | null>(null)

  const isAdmin = user?.role === 'store_admin' || user?.role === 'master_admin'

  const { data: sequences = [], isLoading } = useQuery({
    queryKey: ['twin-check-sequences'],
    queryFn: () => twinCheckSequencesApi.list(),
    enabled: isAdmin,
  })

  const { data: stores = [] } = useQuery({
    queryKey: ['stores'],
    queryFn: () => storesApi.list(),
    enabled: isAdmin,
  })
  const storeName = (storeId: string) => stores.find((s: any) => s.id === storeId)?.label
    || stores.find((s: any) => s.id === storeId)?.name
    || storeId

  const toggleMutation = useMutation({
    mutationFn: ({ storeId, autoEnabled }: { storeId: string; autoEnabled: boolean }) =>
      twinCheckSequencesApi.update(storeId, autoEnabled),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['twin-check-sequences'] })
      setToastMsg(`${vars.autoEnabled ? 'Enabled' : 'Disabled'} auto-allocation`)
      setTimeout(() => setToastMsg(null), 3000)
    },
  })

  if (!isAdmin) {
    return (
      <div className="p-8">
        <p className="text-[#666] text-sm">Admin access required.</p>
      </div>
    )
  }

  return (
    <div className="p-6 lg:p-8 max-w-3xl mx-auto space-y-5">
      <div className="flex items-center gap-2">
        <Zap size={18} className="text-[#ff6600]" />
        <h1 className="text-white text-xl font-bold">Twin Check Allocation</h1>
      </div>
      <p className="text-[#555] text-sm">
        Per-store toggle for automatic twin check allocation. Off means staff type the number by
        hand, exactly as before — manual entry always stays available regardless of this setting.
      </p>

      {toastMsg && (
        <div className="px-4 py-2.5 rounded-lg bg-green-500/10 border border-green-500/30 text-green-400 text-sm">
          {toastMsg}
        </div>
      )}

      {isLoading ? (
        <div className="flex items-center gap-2 text-[#555] text-sm">
          <Loader2 size={14} className="animate-spin" /> Loading…
        </div>
      ) : (
        <div className="bg-[#111] border border-[#1e1e1e] rounded-xl overflow-hidden divide-y divide-[#171717]">
          {sequences.map(seq => (
            <div key={seq.store_id} className="flex items-center gap-4 px-5 py-4">
              <div className="flex-1 min-w-0">
                <p className="text-white text-sm font-medium">{storeName(seq.store_id)}</p>
                <p className="text-[#555] text-xs mt-0.5 font-mono">
                  current: {String(seq.current_value).padStart(4, '0')} · cycle {seq.cycle}
                </p>
              </div>
              <button
                onClick={() => toggleMutation.mutate({ storeId: seq.store_id, autoEnabled: !seq.auto_enabled })}
                disabled={toggleMutation.isPending}
                role="switch"
                aria-checked={seq.auto_enabled}
                title={seq.auto_enabled ? 'Auto-allocation on — click to switch to manual' : 'Manual entry — click to enable auto-allocation'}
                className="relative w-11 h-6 rounded-full transition-colors disabled:opacity-40 flex-shrink-0"
                style={{ backgroundColor: seq.auto_enabled ? '#ff6600' : '#2a2a2a' }}
              >
                <span
                  className="absolute top-0.5 w-5 h-5 rounded-full bg-white transition-transform"
                  style={{ transform: seq.auto_enabled ? 'translateX(22px)' : 'translateX(2px)' }}
                />
              </button>
            </div>
          ))}
          {sequences.length === 0 && (
            <p className="text-[#444] text-xs px-5 py-4">
              No sequences configured — run migration 009_twin_check_allocation.sql.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
