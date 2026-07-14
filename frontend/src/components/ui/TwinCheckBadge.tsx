import { cn } from '../../lib/cn'

interface TwinCheckBadgeProps {
  twin: string
  released?: boolean   // twin freed for reuse (roll archived)
  className?: string
}

export default function TwinCheckBadge({ twin, released = false, className }: TwinCheckBadgeProps) {
  return (
    <span className={cn(
      'inline-flex items-center px-2 py-0.5 rounded-md border font-mono text-sm tracking-wider',
      released
        ? 'bg-[#1a1a1a] border-[#2a2a2a] text-[#555] line-through'
        : 'bg-[#1f0e00] border-[#ff6600]/25 text-[#ff6600]',
      className,
    )}>
      {twin}
    </span>
  )
}
