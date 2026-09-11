import type { Metadata } from 'next'
import './globals.css'
import Sidebar from '@/components/layout/Sidebar'
import AgentFeed from '@/components/agents/AgentFeed'

export const metadata: Metadata = {
  title: 'JobForge',
  description: 'AI-powered job search & application assistant',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        {/* Sidebar (fixed, 220px) */}
        <Sidebar />

        {/* Main content — offset by sidebar width */}
        <main className="ml-[220px] min-h-screen flex flex-col">
          <div className="flex-1 flex">
            {/* Page content */}
            <div className="flex-1 px-6 py-6 overflow-y-auto">
              {children}
            </div>

            {/* Agent Feed panel (fixed width, dark) */}
            <aside className="w-[300px] shrink-0 bg-slate-900 border-l border-slate-800 sticky top-0 h-screen overflow-hidden">
              <AgentFeed />
            </aside>
          </div>
        </main>
      </body>
    </html>
  )
}
