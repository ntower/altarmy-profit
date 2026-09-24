import { describe, expect, it } from 'vitest'
import { status } from '../test/status'
import { importedSince, readSyncSeen, SYNC_SEEN_KEY, syncSeen, writeSyncSeen } from './syncNotice'

describe('importedSince', () => {
  const seen = syncSeen(status())

  it('says nothing without a newer data version or anything seen before', () => {
    expect(importedSince(null, status({ data_version: 5 }))).toEqual([])
    expect(importedSince(seen, status({ last_altarmy_sync: 'later' }))).toEqual([])
  })

  it('names each source that was re-imported', () => {
    const both = status({ data_version: 2, last_altarmy_sync: 'later', last_auctionator_sync: 'later' })
    expect(importedSince(seen, both)).toEqual([
      'Loaded 3 characters from Alt Army.',
      'Loaded Auctionator prices for ClassicBetaPvE.',
    ])
    expect(importedSince(seen, status({ data_version: 2, last_altarmy_sync: 'later', characters: 1 }))).toEqual([
      'Loaded 1 character from Alt Army.',
    ])
  })

  it('covers a scan without prices for the realm and same-second re-imports', () => {
    const empty = status({ data_version: 2, last_auctionator_sync: 'later', auctionator_realm: '' })
    expect(importedSince(seen, empty)).toEqual(['Read Auctionator, but it has no prices for the selected realm.'])
    expect(importedSince(seen, status({ data_version: 2 }))).toEqual(['Re-imported the addon files.'])
  })
})

describe('stored sync state', () => {
  it('round-trips and ignores garbage', () => {
    expect(readSyncSeen()).toBeNull()
    writeSyncSeen(syncSeen(status()))
    expect(readSyncSeen()).toEqual(syncSeen(status()))
    localStorage.setItem(SYNC_SEEN_KEY, '{"data_version": "x"}')
    expect(readSyncSeen()).toBeNull()
  })
})
