import { Application, ApplicationStatus } from './api'

export const APPLICATION_STATUSES: ApplicationStatus[] = [
  'saved', 'preparing', 'applied', 'screening', 'interviewing', 'offer', 'accepted', 'rejected', 'withdrawn',
]

export function statusLabel(status: string) {
  return status.charAt(0).toUpperCase() + status.slice(1).replace(/_/g, ' ')
}

export function utcDate(value: string): Date {
  return new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`)
}

export function formatDate(value: string | null) {
  return value ? utcDate(value).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '—'
}

export function toLocalInput(value: string | null) {
  if (!value) return ''
  const date = utcDate(value)
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

export function fromLocalInput(value: string) {
  return value ? new Date(value).toISOString() : null
}

export function reminderDue(application: Application) {
  return Boolean(application.follow_up_at && !application.follow_up_completed_at
    && utcDate(application.follow_up_at).getTime() <= Date.now())
}
