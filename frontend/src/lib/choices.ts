/** The user's picks in a recipe's flow chart: tree path ('r.0', 'r.0.1'; 'sell' for the exit) -> option key
 * (vendor | ah | craft:<recipe id>, or an exit kind for the sale). The server ignores keys that don't fit. */
export type Choices = Readonly<Record<string, string>>

export const SELL_PATH = 'sell'

/** `choices` with `key` picked at `path`. Picks inside that branch are dropped: the branch has changed. */
export function choose(choices: Choices, path: string, key: string): Choices {
  const kept = Object.entries(choices).filter(([p]) => !p.startsWith(`${path}.`))
  return { ...Object.fromEntries(kept), [path]: key }
}
