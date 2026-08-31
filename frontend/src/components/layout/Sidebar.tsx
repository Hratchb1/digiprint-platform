import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, FilmIcon, PackagePlus, LogOut,
  ChevronRight, Store, Sun, Moon, PanelLeftClose, PanelLeftOpen, Zap,
} from 'lucide-react'
import { useAuth } from '../../hooks/useAuth'
import { useTheme } from '../../hooks/useTheme'
import { cn } from '../../lib/cn'

const NAV = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/orders', icon: FilmIcon, label: 'Orders' },
  { to: '/intake', icon: PackagePlus, label: 'Film Intake' },
]

// Admin-only — twin check auto-allocation toggle (store_admin/master_admin).
const ADMIN_NAV = { to: '/admin/twin-checks', icon: Zap, label: 'Twin Checks' }

interface SidebarProps {
  mobile?: boolean
  collapsed?: boolean
  onNavigate?: () => void
  onToggleCollapse?: () => void
}

export default function Sidebar({ mobile = false, collapsed = false, onNavigate, onToggleCollapse }: SidebarProps) {
  const { user, logout } = useAuth()
  const { theme, toggleTheme } = useTheme()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const slim = collapsed && !mobile

  return (
    <aside className={cn(
      'flex flex-col h-full bg-[#0f0f0f] border-r border-[#1e1e1e] transition-all',
      mobile ? 'w-full' : slim ? 'w-16' : 'w-60',
    )}>
      {/* Logo */}
      <div className={cn('py-5 border-b border-[#1e1e1e]', slim ? 'px-3' : 'px-6')}>
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-[#ff6600] flex items-center justify-center flex-shrink-0">
            <FilmIcon size={16} className="text-white" />
          </div>
          {!slim && (
            <div>
              <p className="text-white font-semibold text-sm leading-none tracking-wide">digiPrint</p>
              <p className="text-[#555] text-[10px] mt-0.5 uppercase tracking-widest">Operations</p>
            </div>
          )}
        </div>
      </div>

      {/* Store badge */}
      {user?.store_id && !slim && (
        <div className="px-4 pt-4">
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[#1a1a1a] border border-[#2a2a2a]">
            <Store size={13} className="text-[#ff6600]" />
            <span className="text-[#aaa] text-xs font-medium">
              {/* Would resolve store name from store_id in a real app */}
              Store View
            </span>
          </div>
        </div>
      )}

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {!slim && (
          <p className="text-[#444] text-[10px] uppercase tracking-widest font-medium px-3 mb-2">Menu</p>
        )}
        {[...NAV, ...(user?.role === 'store_admin' || user?.role === 'master_admin' ? [ADMIN_NAV] : [])].map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            onClick={onNavigate}
            title={slim ? label : undefined}
            className={({ isActive }) => cn(
              'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all group',
              isActive
                ? 'bg-[#ff6600] text-white font-medium'
                : 'text-[#888] hover:text-white hover:bg-[#1a1a1a]',
              slim && 'justify-center px-0',
            )}
          >
            {({ isActive }) => (
              <>
                <Icon size={16} className={isActive ? 'text-white' : 'text-[#555] group-hover:text-[#888]'} />
                {!slim && <span className="flex-1">{label}</span>}
                {!slim && isActive && <ChevronRight size={14} />}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Theme + collapse controls */}
      <div className={cn('px-3 pb-2 flex gap-1', slim ? 'flex-col items-center' : 'items-center')}>
        <button
          onClick={toggleTheme}
          title={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          className="p-2 rounded-lg text-[#555] hover:text-white hover:bg-[#1a1a1a] transition-all"
        >
          {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
        </button>
        {!mobile && onToggleCollapse && (
          <button
            onClick={onToggleCollapse}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className={cn('p-2 rounded-lg text-[#555] hover:text-white hover:bg-[#1a1a1a] transition-all', !slim && 'ml-auto')}
          >
            {collapsed ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}
          </button>
        )}
      </div>

      {/* User footer */}
      <div className="px-3 pb-4 border-t border-[#1e1e1e] pt-3">
        <div className={cn('flex items-center gap-3 px-3 py-2 mb-1', slim && 'justify-center px-0')}>
          <div className="w-7 h-7 rounded-full bg-[#ff6600]/20 border border-[#ff6600]/30 flex items-center justify-center flex-shrink-0">
            <span className="text-[#ff6600] text-[11px] font-bold uppercase">
              {user?.initials || user?.full_name?.[0] || '?'}
            </span>
          </div>
          {!slim && (
            <div className="flex-1 min-w-0">
              <p className="text-white text-xs font-medium truncate">{user?.full_name}</p>
              <p className="text-[#555] text-[10px] capitalize">{user?.role?.replace('_', ' ')}</p>
            </div>
          )}
        </div>
        <button
          onClick={handleLogout}
          title={slim ? 'Sign out' : undefined}
          className={cn(
            'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-[#666] hover:text-[#ff4444] hover:bg-[#1a1a1a] text-sm transition-all',
            slim && 'justify-center px-0',
          )}
        >
          <LogOut size={14} />
          {!slim && <span>Sign out</span>}
        </button>
      </div>
    </aside>
  )
}
