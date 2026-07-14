import { cn } from '../../lib/cn'
import {
  statusLabel, statusStyle,
  displayRollStatus, rollStatusStyle,
} from '../../lib/status'

interface StatusPillProps {
  status: string
  kind?: 'order' | 'roll'   // rolls keep the old status vocabulary
  size?: 'sm' | 'md'
  className?: string
}

export default function StatusPill({ status, kind = 'order', size = 'sm', className }: StatusPillProps) {
  const style = kind === 'roll' ? rollStatusStyle(status) : statusStyle(status)
  const label = kind === 'roll' ? displayRollStatus(status) : statusLabel(status)
  return (
    <span className={cn(
      'inline-flex items-center rounded-full font-medium border whitespace-nowrap',
      size === 'sm' ? 'px-2 py-0.5 text-[11px]' : 'px-3 py-1 text-xs',
      style,
      className,
    )}>
      {label}
    </span>
  )
}
