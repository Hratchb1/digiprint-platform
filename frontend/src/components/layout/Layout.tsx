import { Outlet } from 'react-router-dom'
import { FilmIcon, Menu, X } from 'lucide-react'
import { useState } from 'react'
import Sidebar from './Sidebar'
import RefundWarningsTray from '../RefundWarningsTray'

const COLLAPSE_KEY = 'rollcall-sidebar-collapsed'

export default function Layout() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === '1')

  const toggleCollapse = () => {
    setCollapsed(c => {
      localStorage.setItem(COLLAPSE_KEY, c ? '0' : '1')
      return !c
    })
  }

  return (
    <div className="flex h-screen bg-[#0a0a0a] overflow-hidden">
      {/* Desktop sidebar */}
      <div className="hidden lg:flex flex-shrink-0">
        <Sidebar collapsed={collapsed} onToggleCollapse={toggleCollapse} />
      </div>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          <div className="w-60 h-full">
            <Sidebar mobile onNavigate={() => setMobileOpen(false)} />
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

      {/* Unmatched refunds — floats above all pages */}
      <RefundWarningsTray />
    </div>
  )
}
