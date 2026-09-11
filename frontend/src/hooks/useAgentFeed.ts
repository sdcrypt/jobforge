'use client'

import { useEffect, useRef, useState } from 'react'
import { WS_URL, AgentEventData } from '@/lib/api'

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

  useEffect(() => {
    let reconnectTimer: ReturnType<typeof setTimeout>

    function connect() {
      const ws = new WebSocket(`${WS_URL}/ws`)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        // Keep-alive ping every 25s
        const ping = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send('ping')
        }, 25_000)
        ws.onclose = () => clearInterval(ping)
      }

      ws.onmessage = (e) => {
        if (e.data === 'pong') return
        try {
          const payload = JSON.parse(e.data)
          if (payload.event === 'agent_event') {
            const data = payload.data as AgentEventData
            setEvents((prev) => {
              const event: AgentEvent = {
                id: `${Date.now()}-${Math.random()}`,
                ...data,
                timestamp: new Date(),
              }
              return [event, ...prev].slice(0, MAX_EVENTS)
            })
          }
        } catch { /* ignore malformed */ }
      }

      ws.onerror = () => ws.close()

      ws.onclose = () => {
        setConnected(false)
        // Reconnect after 3 seconds
        reconnectTimer = setTimeout(connect, 3_000)
      }
    }

    connect()

    return () => {
      clearTimeout(reconnectTimer)
      wsRef.current?.close()
    }
  }, [])

  const clear = () => setEvents([])

  return { events, connected, clear, agentIcon: AGENT_ICONS }
}
