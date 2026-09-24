import { z } from 'zod'
import type { Status } from '../api/client'
import { parseStored } from './storage'

/** The parts of the status that say what the addon sync last imported. */
const seenSchema = z.object({
  data_version: z.number(),
  last_altarmy_sync: z.string().nullable(),
  last_auctionator_sync: z.string().nullable(),
})
export type SyncSeen = z.infer<typeof seenSchema>

/** In localStorage, so an import that happened while the page was closed still gets announced once. */
export const SYNC_SEEN_KEY = 'wowprofit.syncSeen'

export function syncSeen(s: Status): SyncSeen {
  return {
    data_version: s.data_version,
    last_altarmy_sync: s.last_altarmy_sync,
    last_auctionator_sync: s.last_auctionator_sync,
  }
}

export function readSyncSeen(): SyncSeen | null {
  try {
    return parseStored(seenSchema.nullable(), localStorage.getItem(SYNC_SEEN_KEY) ?? undefined, null)
  } catch {
    return null
  }
}

export function writeSyncSeen(seen: SyncSeen) {
  try {
    localStorage.setItem(SYNC_SEEN_KEY, JSON.stringify(seen))
  } catch {
    // Storage blocked: announcements then only cover imports while the page is open.
  }
}

/**
 * What the addon sync imported since `seen`, one sentence per source; empty when nothing new, or when
 * nothing was seen before (a first visit should not announce the initial import).
 */
export function importedSince(seen: SyncSeen | null, s: Status): string[] {
  if (seen === null || s.data_version <= seen.data_version) return []
  const lines: string[] = []
  if (s.last_altarmy_sync !== seen.last_altarmy_sync) {
    lines.push(`Loaded ${s.characters.toLocaleString()} ${s.characters === 1 ? 'character' : 'characters'} from Alt Army.`)
  }
  if (s.last_auctionator_sync !== seen.last_auctionator_sync) {
    lines.push(
      s.auctionator_realm
        ? `Loaded Auctionator prices for ${s.auctionator_realm}.`
        : 'Read Auctionator, but it has no prices for the selected realm.',
    )
  }
  return lines.length ? lines : ['Re-imported the addon files.'] // two syncs within the same second
}
