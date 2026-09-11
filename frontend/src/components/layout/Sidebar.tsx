'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import clsx from 'clsx'

const NAV = [
  { href: '/jobs',    label: 'Jobs',          icon: '💼' },
  { href: '/search',  label: 'Search Config', icon: '🔍' },
  { href: '/profile', label: 'My Profile',    icon: '👤' },
]

export default function Sidebar() {
  const path = usePathname()

  return (
    <aside className="fixed top-0 left-0 h-screen w-[220px] bg-slate-900 flex flex-col z-10">

      {/* Logo */}
      <div className="px-5 py-5 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <span className="text-xl">🔨</span>
          <span className="text-white font-bold text-lg tracking-tight">JobForge</span>
        </div>
        <p className="text-slate-500 text-xs mt-0.5">Forge your next career move</p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={clsx(
              'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
              path.startsWith(item.href)
                ? 'bg-brand-600 text-white'
                : 'text-slate-400 hover:bg-slate-800 hover:text-white'
            )}
          >
            <span className="text-base">{item.icon}</span>
            {item.label}
          </Link>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-slate-800">
        <p className="text-slate-600 text-xs">Phase 4 MVP</p>
      </div>
    </aside>
  )
}
