import { LucideIcon } from 'lucide-react'
import { cn } from '../../lib/cn'

interface MetricCardProps {
  label: string
  value: string | number
  icon: LucideIcon
  accent?: boolean
  sub?: string
  className?: string
}

export default function MetricCard({ label, value, icon: Icon, accent = false, sub, className }: MetricCardProps) {
  return (
    <div className={cn(
      'rounded-xl border p-5 flex items-start gap-4',
      accent ? 'bg-[#ff6600]/5 border-[#ff6600]/20' : 'bg-[#111] border-[#1e1e1e]',
      className,
    )}>
      <div className={cn(
        'w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0',
        accent ? 'bg-[#ff6600]/20' : 'bg-[#1a1a1a]',
      )}>
        <Icon size={18} className={accent ? 'text-[#ff6600]' : 'text-[#555]'} />
      </div>
      <div className="min-w-0">
        <p className="text-[#555] text-xs uppercase tracking-wider font-medium truncate">{label}</p>
        <p className="text-white text-2xl font-bold mt-0.5">{value}</p>
        {sub && <p className="text-[#444] text-xs mt-0.5">{sub}</p>}
      </div>
    </div>
  )
}
