import { LucideIcon } from 'lucide-react'
import { ChevronRight } from 'lucide-react'
import { cn } from '../../lib/cn'

type Severity = 'critical' | 'warning' | 'info'

const SEVERITY_STYLES: Record<Severity, string> = {
  critical: 'bg-red-500/10 border-red-500/30 text-red-400 hover:bg-red-500/20',
  warning:  'bg-amber-500/10 border-amber-500/30 text-amber-400 hover:bg-amber-500/20',
  info:     'bg-blue-500/10 border-blue-500/30 text-blue-400 hover:bg-blue-500/20',
}

interface AlertItemProps {
  icon: LucideIcon
  title: string
  count: number
  severity?: Severity
  sub?: string
  onClick?: () => void
  className?: string
}

// Pill-count alert row (Figma prototype style): icon · title · count pill · chevron
export default function AlertItem({ icon: Icon, title, count, severity = 'warning', sub, onClick, className }: AlertItemProps) {
  return (
    <button
      onClick={onClick}
      disabled={!onClick}
      className={cn(
        'w-full flex items-center gap-3 px-4 py-3 rounded-lg border transition-colors text-left',
        SEVERITY_STYLES[severity],
        !onClick && 'cursor-default',
        className,
      )}
    >
      <Icon size={16} className="flex-shrink-0" />
      <span className="flex-1 min-w-0">
        <span className="block text-sm font-medium truncate">{title}</span>
        {sub && <span className="block text-xs opacity-60 truncate">{sub}</span>}
      </span>
      {count > 0 && (
        <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-white/10 flex-shrink-0">
          {count}
        </span>
      )}
      {onClick && <ChevronRight size={14} className="flex-shrink-0" />}
    </button>
  )
}
