/** Money arrives from the API as integer copper; these are the display-edge helpers (see engine.format_money). */

const pad2 = (n: number) => String(n).padStart(2, '0')

export function formatMoney(copper: number): string {
  const sign = copper < 0 ? '-' : ''
  const c = Math.abs(copper)
  return `${sign}${Math.floor(c / 10000)}g ${pad2(Math.floor(c / 100) % 100)}s ${pad2(c % 100)}c`
}

export function goldToCopper(gold: number): number {
  return Math.round(gold * 10000)
}

export function formatRoi(roi: number): string {
  return `${Math.round(roi * 100)}%`
}
