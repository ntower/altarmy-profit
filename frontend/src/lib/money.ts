/** Money arrives from the API as integer copper; the `Money` component shows it as coins. */

export function goldToCopper(gold: number): number {
  return Math.round(gold * 10000)
}

export function formatRoi(roi: number): string {
  return `${Math.round(roi * 100)}%`
}
