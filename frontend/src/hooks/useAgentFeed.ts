'use client'

import { useEffect, useRef, useState } from 'react'
import { WS_URL, AgentEventData, api } from '@/lib/api'
import { utcDate } from '@/lib/applications'

export interface AgentEvent {
  id: string
  agent: string
  status: 'started' | 'thinking' | 'done' | 'error'
  message: string
  extra: Record<string, unknown>
  timestamp: Date
}

const AGENT_ICONS: Record<string, string> = {
  search:      '🔍',
  rank:        '📊',
  docgen:      '📄',
  apply:       '✉️',
  research:    '🔬',
  coordinator: '🧠',
  pipeline:    '⚙️',
}

const MAX_EVENTS = 50

export function useAgentFeed() {
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const clearedBefore = useRef(0)

  useEffect(() => {
    let stopped = false
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined
    let pingTimer: ReturnType<typeof setInterval> | undefined

    function ingest(incoming: AgentEventData[]) {
      if (stopped) return
      setEvents(previous => {
        const merged = new Map(previous.map(event => [event.id, event]))
        incoming.forEach(data => {
          const timestamp = data.created_at ? utcDate(data.created_at) : new Date()
          if (timestamp.getTime() >= clearedBefore.current) {
            const event = { ...data, id: data.id || `${Date.now()}-${Math.random()}`, timestamp }
            merged.set(event.id, event)
          }
        })
        return [...merged.values()].sort((first, second) => second.timestamp.getTime() - first.timestamp.getTime()).slice(0, MAX_EVENTS)
      })
    }

    async function restore() {
      const history = await api.runs.events().catch(() => null)
      if (history) ingest(history.events)
    }

    function connect() {
      if (stopped) return
      const ws = new WebSocket(`${WS_URL}/ws`)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        void restore()
        pingTimer = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send('ping')
        }, 25_000)
      }

      ws.onmessage = (e) => {
        if (e.data === 'pong') return
        try {
          const payload = JSON.parse(e.data)
          if (payload.event === 'agent_event') {
            ingest([payload.data as AgentEventData])
          }
        } catch { /* ignore malformed */ }
      }

      ws.onerror = () => ws.close()

      ws.onclose = () => {
        clearInterval(pingTimer)
        if (stopped) return
        setConnected(false)
        // Reconnect after 3 seconds
        reconnectTimer = setTimeout(connect, 3_000)
      }
    }

    connect()
    void restore()
    const historyTimer = setInterval(restore, 10_000)

    return () => {
      stopped = true
      clearTimeout(reconnectTimer)
      clearInterval(pingTimer)
      clearInterval(historyTimer)
      wsRef.current?.close()
    }
  }, [])

  const clear = () => { clearedBefore.current = Date.now(); setEvents([]) }

  return { events, connected, clear, agentIcon: AGENT_ICONS }
}
