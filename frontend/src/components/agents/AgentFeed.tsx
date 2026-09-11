'use client'

import { useAgentFeed } from '@/hooks/useAgentFeed'
import clsx from 'clsx'

const STATUS_COLORS: Record<string, string> = {
  started:  'text-blue-400',
  thinking: 'text-yellow-400',
  done:     'text-green-400',
  error:    'text-red-400',
}

const STATUS_ICON: Record<string, string> = {
  started:  '▶',
  thinking: '…',
  done:     '✓',
  error:    '✗',
}

export default function AgentFeed() {
  const { events, connected, clear, agentIcon } = useAgentFeed()

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700 shrink-0">
        <div className="flex items-center gap-2">
          <span
            className={clsx(
              'inline-block w-2 h-2 rounded-full',
              connected ? 'bg-green-400 pulse-dot' : 'bg-slate-500'
            )}
          />
          <span className="text-slate-300 text-xs font-semibold uppercase tracking-wider">
            Agent Feed
          </span>
        </div>
        {events.length > 0 && (
          <button
            onClick={clear}
            className="text-slate-500 hover:text-slate-300 text-xs transition-colors"
          >
            Clear
          </button>
        )}
      </div>

      {/* Events list */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1 font-mono text-xs">
        {events.length === 0 && (
          <p className="text-slate-600 text-center pt-6">
            {connected ? 'Waiting for agent events…' : 'Connecting…'}
          </p>
        )}
        {events.map((evt) => (
          <div
            key={evt.id}
            className="flex gap-2 items-start py-1 border-b border-slate-800"
          >
            <span className="text-base leading-none mt-0.5 w-5 shrink-0">
              {agentIcon[evt.agent] ?? '⚙️'}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className={clsx('font-bold', STATUS_COLORS[evt.status] ?? 'text-slate-300')}>
                  {STATUS_ICON[evt.status]}
                </span>
                <span className="text-slate-300 capitalize">{evt.agent}</span>
                <span className="text-slate-600">
                  {evt.timestamp.toLocaleTimeString()}
                </span>
              </div>
              <p className="text-slate-400 truncate">{evt.message}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
