import { AlertTriangle } from 'lucide-react'
import { cn } from '../lib/cn'

interface RefundBannerProps {
  refundStatus: string          // 'full' | 'partial'
  refundAmount?: number | null
  className?: string
}

export default function RefundBanner({ refundStatus, refundAmount, className }: RefundBannerProps) {
  const full = refundStatus === 'full'
  return (
    <div className={cn(
      'rounded-xl border p-4 flex items-start gap-3',
      full ? 'bg-red-500/5 border-red-500/25' : 'bg-yellow-500/5 border-yellow-500/25',
      className,
    )}>
      <AlertTriangle size={15} className={cn('mt-0.5 flex-shrink-0', full ? 'text-red-400' : 'text-yellow-400')} />
      <div>
        <p className={cn('text-sm font-medium', full ? 'text-red-400' : 'text-yellow-400')}>
          {full ? 'Full refund processed in Pronto' : 'Partial refund processed in Pronto'}
          {refundAmount != null && (
            <span className="ml-2 font-mono">${Math.abs(refundAmount).toFixed(2)}</span>
          )}
        </p>
        <p className="text-[#666] text-xs mt-0.5">
          {full
            ? 'The sale was refunded in full — confirm with the customer before doing any further work.'
            : 'Part of this sale was refunded — check which items are still owed before processing.'}
        </p>
      </div>
    </div>
  )
}
