import { useState, useRef, useEffect, KeyboardEvent } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ordersApi, storesApi } from '../lib/api'
import { useAuth } from '../hooks/useAuth'
import { FilmIcon, Check, AlertTriangle, Plus, X, ChevronRight, Loader2 } from 'lucide-react'
import clsx from 'clsx'

type Roll = { twin: string; service: string }

const SERVICES = ['Dev only', 'Dev+Scan', 'Dev+Scan+Print', 'Dev+Print', 'Scan only']

function beep(freq = 880, ms = 100) {
  try {
    const ctx = new (window.AudioContext || (window as any).webkitAudioContext)()
    const o = ctx.createOscillator()
    const g = ctx.createGain()
    o.type = 'sine'
    o.frequency.value = freq
    o.connect(g)
    g.connect(ctx.destination)
    const t = ctx.currentTime
    g.gain.setValueAtTime(0.0001, t)
    g.gain.exponentialRampToValueAtTime(0.3, t + 0.01)
    g.gain.exponentialRampToValueAtTime(0.0001, t + ms / 1000)
    o.start(t)
    o.stop(t + ms / 1000)
  } catch {}
}

function pad4(s: string) {
  const d = s.replace(/\D/g, '')
  return d.padStart(4, '0')
}

export default function IntakePage() {
  const { user } = useAuth()
  const qc = useQueryClient()

  // Step 1: Order details
  const [orderNumber, setOrderNumber] = useState('')
  const [customerName, setCustomerName] = useState('')
  const [customerEmail, setCustomerEmail] = useState('')
  const [storeId, setStoreId] = useState(user?.store_id || '')
  const [operator, setOperator] = useState(() => localStorage.getItem('pref_operator') || user?.initials || '')
  const [defaultService, setDefaultService] = useState(() => localStorage.getItem('pref_service') || 'Dev+Scan')
  const [locked, setLocked] = useState(false)

  // Step 2: Rolls
  const [rolls, setRolls] = useState<Roll[]>([])
  const [twinInput, setTwinInput] = useState('')
  const [twinError, setTwinError] = useState('')
  const [rangeFirst, setRangeFirst] = useState('')
  const [rangeLast, setRangeLast] = useState('')

  // Result
  const [submitted, setSubmitted] = useState<any>(null)

  const twinRef = useRef<HTMLInputElement>(null)
  const orderRef = useRef<HTMLInputElement>(null)

  const { data: stores = [] } = useQuery({ queryKey: ['stores'], queryFn: storesApi.list })

  const { mutate: submit, isPending } = useMutation({
    mutationFn: (payload: any) => ordersApi.create(payload),
    onSuccess: (data) => {
      beep(880, 150)
      setSubmitted(data)
      qc.invalidateQueries({ queryKey: ['orders-recent'] })
    },
    onError: (err: any) => {
      beep(300, 200)
      alert(err.response?.data?.detail || 'Failed to save order')
    }
  })

  useEffect(() => {
    if (locked) twinRef.current?.focus()
    else orderRef.current?.focus()
  }, [locked])

  const lockOrder = () => {
    if (!orderNumber.trim() || !customerName.trim()) {
      beep(300, 150)
      return
    }
    localStorage.setItem('pref_operator', operator)
    localStorage.setItem('pref_service', defaultService)
    setLocked(true)
    beep(600, 100)
  }

  const addTwin = () => {
    const raw = twinInput.trim()
    setTwinError('')
    if (!raw) return

    // Multi-scan: space or comma separated
    const parts = raw.split(/[\s,]+/).filter(Boolean)
    const toAdd: Roll[] = []
    const dups: string[] = []

    for (const p of parts) {
      if (!/^\d{1,4}$/.test(p)) {
        setTwinError(`"${p}" is not a valid twin (1–4 digits)`)
        beep(300, 150)
        return
      }
      const padded = pad4(p)
      if (rolls.find(r => r.twin === padded)) {
        dups.push(padded)
      } else {
        toAdd.push({ twin: padded, service: defaultService })
      }
    }

    if (dups.length && !window.confirm(`Twin(s) already in list: ${dups.join(', ')}\nAdd anyway?`)) return
    if (toAdd.length) {
      setRolls(prev => [...prev, ...toAdd])
      beep(880, 80)
    }
    setTwinInput('')
  }

  const addRange = () => {
    const a = parseInt(rangeFirst, 10)
    const b = parseInt(rangeLast, 10)
    if (isNaN(a) || isNaN(b)) return
    const lo = Math.min(a, b)
    const hi = Math.max(a, b)
    if (hi - lo > 199) { alert('Range too large (max 200)'); return }
    const toAdd: Roll[] = []
    for (let i = lo; i <= hi; i++) {
      const padded = pad4(String(i))
      if (!rolls.find(r => r.twin === padded)) {
        toAdd.push({ twin: padded, service: defaultService })
      }
    }
    setRolls(prev => [...prev, ...toAdd])
    beep(880, 100)
    setRangeFirst('')
    setRangeLast('')
  }

  const removeRoll = (twin: string) => setRolls(prev => prev.filter(r => r.twin !== twin))

  const handleTwinKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') addTwin()
    if (e.key === 'Escape') resetForm()
  }

  const handleRangeLastKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') addRange()
  }

  const submitOrder = () => {
    if (!rolls.length) { alert('Add at least one roll'); return }
    submit({
      order_number: orderNumber.trim().replace(/\s/g, ''),
      store_id: storeId,
      customer_name: customerName.trim(),
      customer_email: customerEmail.trim() || undefined,
      operator_initials: operator.trim(),
      rolls: rolls.map(r => ({ twin_check: r.twin, service_type: r.service })),
    })
  }

  const resetForm = () => {
    setOrderNumber('')
    setCustomerName('')
    setCustomerEmail('')
    setRolls([])
    setTwinInput('')
    setTwinError('')
    setRangeFirst('')
    setRangeLast('')
    setLocked(false)
    setSubmitted(null)
    setTimeout(() => orderRef.current?.focus(), 50)
  }

  // ── Success screen ─────────────────────────────────────────────────────
  if (submitted) {
    return (
      <div className="p-6 lg:p-8 max-w-2xl mx-auto">
        <div className="bg-[#111] border border-green-500/20 rounded-2xl p-8 text-center">
          <div className="w-16 h-16 rounded-full bg-green-500/10 border border-green-500/20 flex items-center justify-center mx-auto mb-4">
            <Check size={28} className="text-green-400" />
          </div>
          <h2 className="text-white font-bold text-xl mb-2">Order Booked In</h2>
          <p className="text-[#555] text-sm mb-6">
            {submitted.customer_name} · {submitted.order_number}
          </p>
          <div className="flex flex-wrap justify-center gap-2 mb-6">
            {submitted.rolls?.map((r: any) => (
              <span key={r.twin_check} className="px-3 py-1 rounded-full bg-[#1a1a1a] border border-[#2a2a2a] text-[#aaa] text-sm font-mono">
                {r.twin_check}
              </span>
            ))}
          </div>
          <button
            onClick={resetForm}
            className="bg-[#ff6600] hover:bg-[#ff7720] text-white font-semibold px-6 py-3 rounded-lg transition-colors"
          >
            Book next order
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 lg:p-8 max-w-2xl mx-auto">
      <div className="mb-6">
        <h1 className="text-white text-2xl font-bold tracking-tight">Film Intake</h1>
        <p className="text-[#555] text-sm mt-1">Book in film rolls for processing</p>
      </div>

      <div className="bg-[#111] border border-[#1e1e1e] rounded-2xl overflow-hidden">
        {/* Header bar */}
        <div className="px-6 py-4 border-b border-[#1e1e1e] flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-[#ff6600]/10 border border-[#ff6600]/20 flex items-center justify-center">
            <FilmIcon size={16} className="text-[#ff6600]" />
          </div>
          <div className="flex-1">
            <p className="text-white font-medium text-sm">
              {locked ? `Order: ${orderNumber}` : 'New Order'}
            </p>
            {locked && <p className="text-[#555] text-xs">{customerName}</p>}
          </div>
          {locked && (
            <span className="px-2 py-0.5 rounded-full bg-green-500/10 border border-green-500/20 text-green-400 text-xs">
              Locked
            </span>
          )}
        </div>

        <div className="p-6 space-y-5">

          {/* ── Step 1: Order details ── */}
          <div className={clsx('space-y-4', locked && 'opacity-40 pointer-events-none')}>
            <p className="text-[#666] text-xs uppercase tracking-widest font-medium">Order Details</p>

            <div className="grid grid-cols-2 gap-3">
              {/* Store */}
              <div className="col-span-2 sm:col-span-1">
                <label className="block text-[#666] text-xs mb-1.5">Store</label>
                <select
                  value={storeId}
                  onChange={e => setStoreId(e.target.value)}
                  disabled={locked || user?.role === 'staff'}
                  className="w-full bg-[#0f0f0f] border border-[#2a2a2a] text-white text-sm rounded-lg px-3 py-2.5 focus:outline-none focus:border-[#ff6600]"
                >
                  <option value="">Select store…</option>
                  {stores.map((s: any) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
              </div>

              {/* Operator */}
              <div className="col-span-2 sm:col-span-1">
                <label className="block text-[#666] text-xs mb-1.5">Operator</label>
                <input
                  value={operator}
                  onChange={e => setOperator(e.target.value)}
                  placeholder="Initials"
                  disabled={locked}
                  className="w-full bg-[#0f0f0f] border border-[#2a2a2a] text-white text-sm rounded-lg px-3 py-2.5 focus:outline-none focus:border-[#ff6600] placeholder:text-[#333]"
                />
              </div>

              {/* Order number */}
              <div className="col-span-2">
                <label className="block text-[#666] text-xs mb-1.5">Order Number</label>
                <input
                  ref={orderRef}
                  value={orderNumber}
                  onChange={e => setOrderNumber(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && lockOrder()}
                  placeholder="e.g. DD-2025-000123"
                  disabled={locked}
                  className="w-full bg-[#0f0f0f] border border-[#2a2a2a] text-white text-sm rounded-lg px-3 py-2.5 focus:outline-none focus:border-[#ff6600] placeholder:text-[#333] font-mono"
                />
              </div>

              {/* Customer name */}
              <div className="col-span-2 sm:col-span-1">
                <label className="block text-[#666] text-xs mb-1.5">Customer Name</label>
                <input
                  value={customerName}
                  onChange={e => setCustomerName(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && lockOrder()}
                  placeholder="First Last"
                  disabled={locked}
                  className="w-full bg-[#0f0f0f] border border-[#2a2a2a] text-white text-sm rounded-lg px-3 py-2.5 focus:outline-none focus:border-[#ff6600] placeholder:text-[#333]"
                />
              </div>

              {/* Customer email */}
              <div className="col-span-2 sm:col-span-1">
                <label className="block text-[#666] text-xs mb-1.5">
                  Email <span className="text-[#444]">(optional)</span>
                </label>
                <input
                  value={customerEmail}
                  onChange={e => setCustomerEmail(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && lockOrder()}
                  placeholder="name@example.com"
                  type="email"
                  disabled={locked}
                  className="w-full bg-[#0f0f0f] border border-[#2a2a2a] text-white text-sm rounded-lg px-3 py-2.5 focus:outline-none focus:border-[#ff6600] placeholder:text-[#333]"
                />
              </div>

              {/* Default service */}
              <div className="col-span-2">
                <label className="block text-[#666] text-xs mb-1.5">Default Service</label>
                <select
                  value={defaultService}
                  onChange={e => setDefaultService(e.target.value)}
                  disabled={locked}
                  className="w-full bg-[#0f0f0f] border border-[#2a2a2a] text-white text-sm rounded-lg px-3 py-2.5 focus:outline-none focus:border-[#ff6600]"
                >
                  {SERVICES.map(s => <option key={s}>{s}</option>)}
                </select>
              </div>
            </div>

            {!locked && (
              <button
                onClick={lockOrder}
                disabled={!orderNumber || !customerName || !storeId}
                className="w-full bg-[#ff6600] hover:bg-[#ff7720] disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-2.5 rounded-lg transition-colors text-sm"
              >
                Lock Order & Start Scanning
              </button>
            )}
          </div>

          {/* ── Step 2: Scan twins ── */}
          {locked && (
            <div className="space-y-4 pt-2 border-t border-[#1e1e1e]">
              <p className="text-[#666] text-xs uppercase tracking-widest font-medium">Scan Rolls</p>

              {/* Single twin input */}
              <div>
                <label className="block text-[#666] text-xs mb-1.5">
                  Twin Check
                  <span className="text-[#444] ml-1.5 normal-case tracking-normal">— scan or type, Enter to add</span>
                </label>
                <div className="flex gap-2">
                  <input
                    ref={twinRef}
                    value={twinInput}
                    onChange={e => { setTwinInput(e.target.value); setTwinError('') }}
                    onKeyDown={handleTwinKey}
                    placeholder="Scan 1–4 digits…"
                    className="flex-1 bg-[#0f0f0f] border border-[#2a2a2a] text-white text-sm rounded-lg px-3 py-2.5 focus:outline-none focus:border-[#ff6600] placeholder:text-[#333] font-mono"
                  />
                  <button
                    onClick={addTwin}
                    className="px-4 py-2.5 bg-[#1a1a1a] border border-[#2a2a2a] hover:border-[#ff6600] text-[#888] hover:text-white rounded-lg transition-all text-sm"
                  >
                    <Plus size={16} />
                  </button>
                </div>
                {twinError && (
                  <p className="text-[#ff4444] text-xs mt-1.5 flex items-center gap-1">
                    <AlertTriangle size={11} /> {twinError}
                  </p>
                )}
              </div>

              {/* Range input */}
              <div>
                <label className="block text-[#666] text-xs mb-1.5">Add Range</label>
                <div className="flex gap-2">
                  <input
                    value={rangeFirst}
                    onChange={e => setRangeFirst(e.target.value)}
                    placeholder="First"
                    className="w-24 bg-[#0f0f0f] border border-[#2a2a2a] text-white text-sm rounded-lg px-3 py-2.5 focus:outline-none focus:border-[#ff6600] placeholder:text-[#333] font-mono"
                  />
                  <span className="text-[#444] text-sm self-center">→</span>
                  <input
                    value={rangeLast}
                    onChange={e => setRangeLast(e.target.value)}
                    onKeyDown={handleRangeLastKey}
                    placeholder="Last"
                    className="w-24 bg-[#0f0f0f] border border-[#2a2a2a] text-white text-sm rounded-lg px-3 py-2.5 focus:outline-none focus:border-[#ff6600] placeholder:text-[#333] font-mono"
                  />
                  <button
                    onClick={addRange}
                    disabled={!rangeFirst || !rangeLast}
                    className="flex-1 px-4 py-2.5 bg-[#1a1a1a] border border-[#2a2a2a] hover:border-[#ff6600] disabled:opacity-40 text-[#888] hover:text-white rounded-lg transition-all text-sm"
                  >
                    Add Range
                  </button>
                </div>
              </div>

              {/* Roll list */}
              {rolls.length > 0 && (
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-[#666] text-xs">
                      {rolls.length} roll{rolls.length !== 1 ? 's' : ''} scanned
                    </p>
                    <button onClick={() => setRolls([])} className="text-[#444] hover:text-[#ff4444] text-xs transition-colors">
                      Clear all
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-2 max-h-40 overflow-auto p-3 bg-[#0f0f0f] rounded-lg border border-[#1e1e1e]">
                    {rolls.map(r => (
                      <span
                        key={r.twin}
                        className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[#1a1a1a] border border-[#2a2a2a] text-[#aaa] text-sm font-mono group"
                      >
                        {r.twin}
                        <button
                          onClick={() => removeRoll(r.twin)}
                          className="text-[#333] hover:text-[#ff4444] transition-colors opacity-0 group-hover:opacity-100"
                        >
                          <X size={11} />
                        </button>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Action buttons */}
              <div className="flex gap-3 pt-2">
                <button
                  onClick={resetForm}
                  className="px-4 py-2.5 bg-[#1a1a1a] border border-[#2a2a2a] hover:border-[#444] text-[#666] hover:text-white rounded-lg transition-all text-sm"
                >
                  Cancel
                </button>
                <button
                  onClick={submitOrder}
                  disabled={isPending || rolls.length === 0}
                  className="flex-1 flex items-center justify-center gap-2 bg-[#ff6600] hover:bg-[#ff7720] disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-2.5 rounded-lg transition-colors text-sm"
                >
                  {isPending ? (
                    <><Loader2 size={15} className="animate-spin" /> Saving…</>
                  ) : (
                    <>Save {rolls.length > 0 ? `${rolls.length} roll${rolls.length !== 1 ? 's' : ''}` : 'Order'} <ChevronRight size={15} /></>
                  )}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
