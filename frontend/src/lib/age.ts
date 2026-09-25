/** How long ago a server timestamp ("YYYY-MM-DD HH:MM:SS", UTC) was, roughly: "just now", "5 min", "3 h", "2 days". */
export function age(utc: string, now: Date = new Date()): string {
  const then = Date.parse(`${utc.replace(' ', 'T')}Z`)
  if (Number.isNaN(then)) return utc
  const minutes = Math.max(0, Math.floor((now.getTime() - then) / 60_000))
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 48) return `${hours} h ago`
  return `${Math.floor(hours / 24)} days ago`
}
