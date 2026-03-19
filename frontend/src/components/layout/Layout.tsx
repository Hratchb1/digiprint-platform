import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth'
import {
  LayoutDashboard, FilmIcon, PackagePlus, LogOut,
  ChevronRight, Store, Menu, X
} from 'lucide-react'
import { useState } from 'react'
import clsx from 'clsx'

const NAV = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/orders', icon: FilmIcon, label: 'Orders' },
  { to: '/intake', icon: PackagePlus, label: 'Film Intake' },
]

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [mobileOpen, setMobileOpen] = useState(false)

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const Sidebar = ({ mobile = false }: { mobile?: boolean }) => (
    <aside className={clsx(
      'flex flex-col h-full bg-[#0f0f0f] border-r border-[#1e1e1e]',
      mobile ? 'w-full' : 'w-60'
    )}>
      {/* Logo */}
      <div className="px-6 py-5 border-b border-[#1e1e1e]">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-[#ff6600] flex items-center justify-center flex-shrink-0">
            <FilmIcon size={16} className="text-white" />
          </div>
          <div>
            <p className="text-white font-semibold text-sm leading-none tracking-wide">digiPrint</p>
            <p className="text-[#555] text-[10px] mt-0.5 uppercase tracking-widest">Operations</p>
          </div>
        </div>
      </div>

      {/* Store badge */}
      {user?.store_id && (
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
        <p className="text-[#444] text-[10px] uppercase tracking-widest font-medium px-3 mb-2">Menu</p>
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            onClick={() => setMobileOpen(false)}
            className={({ isActive }) => clsx(
              'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all group',
              isActive
                ? 'bg-[#ff6600] text-white font-medium'
                : 'text-[#888] hover:text-white hover:bg-[#1a1a1a]'
            )}
          >
            {({ isActive }) => (
              <>
                <Icon size={16} className={isActive ? 'text-white' : 'text-[#555] group-hover:text-[#888]'} />
                <span className="flex-1">{label}</span>
                {isActive && <ChevronRight size={14} />}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {/* User footer */}
      <div className="px-3 pb-4 border-t border-[#1e1e1e] pt-3">
        <div className="flex items-center gap-3 px-3 py-2 mb-1">
          <div className="w-7 h-7 rounded-full bg-[#ff6600]/20 border border-[#ff6600]/30 flex items-center justify-center flex-shrink-0">
            <span className="text-[#ff6600] text-[11px] font-bold uppercase">
              {user?.initials || user?.full_name?.[0] || '?'}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-white text-xs font-medium truncate">{user?.full_name}</p>
            <p className="text-[#555] text-[10px] capitalize">{user?.role?.replace('_', ' ')}</p>
          </div>
        </div>
        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-[#666] hover:text-[#ff4444] hover:bg-[#1a1a1a] text-sm transition-all"
        >
          <LogOut size={14} />
          <span>Sign out</span>
        </button>
      </div>
    </aside>
  )

  return (
    <div className="flex h-screen bg-[#0a0a0a] overflow-hidden">
      {/* Desktop sidebar */}
      <div className="hidden lg:flex flex-shrink-0">
        <Sidebar />
      </div>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          <div className="w-60 h-full">
            <Sidebar mobile />
          </div>
          <div
            className="flex-1 bg-black/60 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
          />
        </div>
      )}

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Mobile topbar */}
        <div className="lg:hidden flex items-center gap-4 px-4 py-3 bg-[#0f0f0f] border-b border-[#1e1e1e]">
          <button
            onClick={() => setMobileOpen(!mobileOpen)}
            className="text-[#888] hover:text-white p-1"
          >
            {mobileOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-[#ff6600] flex items-center justify-center">
              <FilmIcon size={12} className="text-white" />
            </div>
            <span className="text-white font-medium text-sm">digiPrint</span>
          </div>
        </div>

        {/* Page content */}
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
