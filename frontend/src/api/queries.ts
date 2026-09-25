import { useEffect, useRef } from 'react'
import { notifications } from '@mantine/notifications'
import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  call,
  client,
  type Evaluation,
  type GameVersion,
  type Selection,
  type Sources,
  type Status,
  type UpdateResult,
} from './client'
import { useGameVersion } from '../lib/gameVersion'
import type { Choices } from '../lib/choices'
import { importedSince, readSyncSeen, syncSeen, writeSyncSeen } from '../lib/syncNotice'

/** The `game_version` query parameter every per-game route takes. */
const gv = (gameVersion: GameVersion) => ({ params: { query: { game_version: gameVersion } } })

/**
 * The chosen game's server status. Fetching it also makes the server re-import the Alt Army and Auctionator files if WoW
 * rewrote them (on logout or /reload), so poll it, and refetch when the user comes back from the game.
 */
export function useStatus() {
  const gameVersion = useGameVersion()
  return useQuery({
    queryKey: ['status', gameVersion],
    queryFn: () => call(client.GET('/api/status', gv(gameVersion))),
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  })
}

/**
 * Part of the keys of data that imports and merges affect: the user's data version (bumped whenever a sync or upload
 * re-imported something) and the selected auction house's price version (bumped by the hourly merge).
 */
export function useDataVersion() {
  const status = useStatus().data
  return status && `${status.data_version}.${status.price_version ?? 0}`
}

export function useCharacters() {
  const gameVersion = useGameVersion()
  const version = useDataVersion()
  return useQuery({
    queryKey: ['characters', gameVersion, version],
    queryFn: () => call(client.GET('/api/characters', gv(gameVersion))),
    enabled: version !== undefined,
    placeholderData: keepPreviousData,
  })
}

export type Exit = 'vendor' | 'disenchant' | 'ah'

/** `/api/rank` parameters: money in copper, ROI as a fraction (0.5 = 50%), `null` for no bound. */
export type RankParams = {
  includeUnlearned: boolean
  /** false: only recipes that can give the crafter a skillup */
  includeTrivial: boolean
  exits: Exit[]
  minCost: number | null
  maxCost: number | null
  minProfit: number | null
  maxProfit: number | null
  minRoi: number | null
  maxRoi: number | null
  top: number
}

const orUndefined = <T>(v: T | null) => v ?? undefined

/** Ranked recipes for the selected realm/faction's characters. */
export function useRank(params: RankParams) {
  const gameVersion = useGameVersion()
  const version = useDataVersion()
  return useQuery({
    queryKey: ['rank', gameVersion, version, params],
    queryFn: () =>
      call(
        client.GET('/api/rank', {
          params: {
            query: {
              game_version: gameVersion,
              include_unlearned: params.includeUnlearned,
              include_trivial: params.includeTrivial,
              exits: params.exits,
              min_cost: orUndefined(params.minCost),
              max_cost: orUndefined(params.maxCost),
              min_profit: orUndefined(params.minProfit),
              max_profit: orUndefined(params.maxProfit),
              min_roi: orUndefined(params.minRoi),
              max_roi: orUndefined(params.maxRoi),
              top: params.top,
            },
          },
        }),
      ),
    enabled: version !== undefined,
    placeholderData: keepPreviousData,
  })
}

/** What `/api/evaluate` needs besides the choices: the search's settings, and the data version its results
 * came from (so a sync re-costs the user's changed plans too). */
export type EvaluateParams = Pick<RankParams, 'includeUnlearned' | 'includeTrivial' | 'exits'> & { version?: string }

export type EvaluationState = { data?: Evaluation; isFetching: boolean; error: Error | null }

/** Each recipe re-costed with the user's choices, by recipe id. While a new choice loads, the recipe's
 * previous evaluation stays in `data`. */
export function useEvaluations(
  choices: Readonly<Record<number, Choices>>,
  { includeUnlearned, includeTrivial, exits, version }: EvaluateParams,
): Readonly<Record<number, EvaluationState>> {
  const gameVersion = useGameVersion()
  const ids = Object.keys(choices).map(Number)
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: ['evaluate', gameVersion, version, id, includeUnlearned, includeTrivial, exits, choices[id]],
      queryFn: () =>
        call(
          client.POST('/api/evaluate', {
            ...gv(gameVersion),
            body: {
              recipe_id: id,
              include_unlearned: includeUnlearned,
              include_trivial: includeTrivial,
              exits,
              choices: choices[id] ?? {},
            },
          }),
        ),
      // Observers are matched by position, so only keep data that belongs to the same recipe.
      placeholderData: (previous: Evaluation | undefined, query?: { queryKey: readonly unknown[] }) =>
        query?.queryKey[3] === id ? previous : undefined,
    })),
    combine: (results) =>
      Object.fromEntries(
        results.map(({ data, isFetching, error }, i) => [ids[i], { data, isFetching, error }]),
      ),
  })
}

/** How to sign in (never changes while the page is open). */
export function useConfig() {
  return useQuery({
    queryKey: ['config'],
    queryFn: () => call(client.GET('/api/config')),
    staleTime: Infinity,
  })
}

/** The signed-in user and tier; fetched once signed in (`enabled`), and again after linking. */
export function useMe(enabled: boolean) {
  return useQuery({
    queryKey: ['me'],
    queryFn: () => call(client.GET('/api/me')),
    enabled,
    staleTime: Infinity,
  })
}

/** The chosen game's auction houses, with how many prices each has. */
export function useRealms() {
  const gameVersion = useGameVersion()
  const version = useDataVersion()
  return useQuery({
    queryKey: ['realms', gameVersion, version],
    queryFn: () => call(client.GET('/api/realms', gv(gameVersion))),
    placeholderData: keepPreviousData,
  })
}

/** Items priced on an auction house whose name contains `q`, by name. */
export function usePrices(auctionHouseId: number | null, q: string, top = 50) {
  const gameVersion = useGameVersion()
  const version = useDataVersion()
  return useQuery({
    queryKey: ['prices', gameVersion, version, auctionHouseId, q, top],
    queryFn: () =>
      call(
        client.GET('/api/prices', {
          params: { query: { game_version: gameVersion, auction_house_id: auctionHouseId ?? 0, q, top } },
        }),
      ),
    enabled: auctionHouseId !== null,
    placeholderData: keepPreviousData,
  })
}

/** One item's current price and daily history on an auction house. */
export function usePriceHistory(auctionHouseId: number, itemId: number) {
  const gameVersion = useGameVersion()
  const version = useDataVersion()
  return useQuery({
    queryKey: ['price-history', gameVersion, version, auctionHouseId, itemId],
    queryFn: () =>
      call(
        client.GET('/api/prices/{item_id}', {
          params: {
            path: { item_id: itemId },
            query: { game_version: gameVersion, auction_house_id: auctionHouseId },
          },
        }),
      ),
  })
}

/** Each realm's scans of the chosen game (every tier), so uploaders see where scans are needed. */
export function useCoverage() {
  const gameVersion = useGameVersion()
  const version = useDataVersion()
  return useQuery({
    queryKey: ['coverage', gameVersion, version],
    queryFn: () => call(client.GET('/api/coverage', gv(gameVersion))),
  })
}

/** Your newest uploads, every game version. */
export function useUploads() {
  return useQuery({
    queryKey: ['uploads'],
    queryFn: () => call(client.GET('/api/uploads')),
  })
}

export type UploadKind = 'altarmy' | 'auctionator'

/** Upload an addon file for the chosen game; everything it can change is refetched afterwards. */
export function useUpload() {
  const gameVersion = useGameVersion()
  const invalidate = useInvalidateAll()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ kind, file }: { kind: UploadKind; file: File }) =>
      call(
        client.POST('/api/uploads', {
          ...gv(gameVersion),
          // The generated type says `string` (OpenAPI's binary format); the serializer sends the File itself.
          body: { kind, file: file as unknown as string, modified_at: file.lastModified, via: 'browser' },
          bodySerializer: (body) => {
            const form = new FormData()
            form.append('kind', body.kind)
            form.append('via', 'browser')
            if (body.modified_at != null) form.append('modified_at', String(body.modified_at))
            form.append('file', file, file.name)
            return form
          },
        }),
      ),
    onSuccess: () => invalidate(),
    onError: () => queryClient.invalidateQueries({ queryKey: ['uploads'] }), // it lists rejected ones too
  })
}

/** Your API keys for the CLI watcher. */
export function useApiKeys() {
  return useQuery({
    queryKey: ['keys'],
    queryFn: () => call(client.GET('/api/keys')),
  })
}

/** Make an API key; the response is the only time the key itself is shown. */
export function useCreateKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (label: string) => call(client.POST('/api/keys', { body: { label } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['keys'] }),
    onError: showError('Could not make a key'),
  })
}

export function useRevokeKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (keyId: number) => call(client.DELETE('/api/keys/{key_id}', { params: { path: { key_id: keyId } } })),
    onSuccess: (keys) => queryClient.setQueryData(['keys'], keys),
    onError: showError('Could not revoke the key'),
  })
}

export function useAuctionatorFiles() {
  const gameVersion = useGameVersion()
  return useQuery({
    queryKey: ['auctionator', gameVersion, 'files'],
    queryFn: () => call(client.GET('/api/auctionator/files', gv(gameVersion))),
  })
}

export function useAltArmyFiles() {
  const gameVersion = useGameVersion()
  return useQuery({
    queryKey: ['altarmy', gameVersion, 'files'],
    queryFn: () => call(client.GET('/api/altarmy/files', gv(gameVersion))),
  })
}

function showError(title: string) {
  return (error: Error) => notifications.show({ color: 'red', title, message: error.message })
}

/** Items never sold on the AH: searches only vendor or disenchant them. */
export function useAhBlocked() {
  const gameVersion = useGameVersion()
  return useQuery({
    queryKey: ['ah-blocked', gameVersion],
    queryFn: () => call(client.GET('/api/ah-blocked', gv(gameVersion))),
  })
}

/** Never sell an item on the AH, or allow it again; searches and re-costed plans are refetched. */
export function useSetAhBlocked() {
  const gameVersion = useGameVersion()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ itemId, blocked }: { itemId: number; blocked: boolean }) => {
      const params = { params: { path: { item_id: itemId }, query: { game_version: gameVersion } } }
      return call(blocked ? client.PUT('/api/ah-blocked/{item_id}', params) : client.DELETE('/api/ah-blocked/{item_id}', params))
    },
    onSuccess: (list, { itemId, blocked }) => {
      queryClient.setQueryData(['ah-blocked', gameVersion], list)
      if (blocked) {
        const name = list.details[itemId]?.name ?? `Item ${itemId}`
        notifications.show({
          title: `${name} won't be sold on the auction house`,
          message: 'Allow it again from its menu or the Manage tab.',
        })
      }
      return queryClient.invalidateQueries({ predicate: (q) => q.queryKey[0] === 'rank' || q.queryKey[0] === 'evaluate' })
    },
    onError: showError('Could not update the auction house list'),
  })
}

/** Every mutation changes the database, so refetch everything afterwards. */
function useInvalidateAll() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries()
}

function updateGameData(gameVersion: GameVersion, onlyIfNew: boolean) {
  return call(
    client.POST('/api/game-data/update', { params: { query: { game_version: gameVersion, only_if_new: onlyIfNew } } }),
  )
}

function showUpdated(r: UpdateResult, title: string) {
  notifications.show({
    color: 'green',
    title,
    message: `Loaded build ${r.build}: ${r.items.toLocaleString()} items, ${r.recipes.toLocaleString()} recipes.`,
  })
}

export function useUpdateGameData() {
  const gameVersion = useGameVersion()
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: () => updateGameData(gameVersion, false),
    onSuccess: (r) => {
      showUpdated(r, 'Game data updated')
      return invalidate()
    },
    onError: showError('Update failed'),
  })
}

/**
 * Once per page load and game version, fetch the chosen game's newest build if its database does not have
 * it yet. Failures only go to the console: being offline should not raise a toast on every visit.
 */
export function useAutoUpdateGameData() {
  const gameVersion = useGameVersion()
  const invalidate = useInvalidateAll()
  const { mutate } = useMutation({
    mutationFn: (v: GameVersion) => updateGameData(v, true),
    onSuccess: (r) => {
      if (!r.updated) return
      showUpdated(r, 'New game data downloaded')
      return invalidate()
    },
    onError: (error) => console.warn('Automatic game data update failed:', error),
  })
  const started = useRef(new Set<GameVersion>()) // StrictMode runs effects twice in development
  useEffect(() => {
    if (started.current.has(gameVersion)) return
    started.current.add(gameVersion)
    mutate(gameVersion)
  }, [mutate, gameVersion])
}

/**
 * Toast whenever the server's addon sync re-imported Alt Army or Auctionator data: while the page is
 * open (status polling), or since it was last open.
 */
export function useSyncNotifications() {
  const gameVersion = useGameVersion()
  const status = useStatus().data
  useEffect(() => {
    if (!status) return
    const lines = importedSince(readSyncSeen(gameVersion), status)
    writeSyncSeen(gameVersion, syncSeen(status))
    if (lines.length) notifications.show({ color: 'green', title: 'Addon data imported', message: lines.join(' ') })
  }, [status, gameVersion])
}

/** The mutations below answer with the new status: show it at once, then refetch the rest. */
function useApplyStatus() {
  const gameVersion = useGameVersion()
  const queryClient = useQueryClient()
  return (status: Status) => {
    queryClient.setQueryData(['status', gameVersion], status)
    return queryClient.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'status' })
  }
}

/** Switch realm/faction; the server swaps in that realm's Auctionator prices. */
export function useSelectRealm() {
  const gameVersion = useGameVersion()
  const apply = useApplyStatus()
  return useMutation({
    mutationFn: (body: Selection) => call(client.PUT('/api/selection', { ...gv(gameVersion), body })),
    onSuccess: apply,
    onError: showError('Could not switch realm'),
  })
}

export function useSetSources() {
  const gameVersion = useGameVersion()
  const apply = useApplyStatus()
  return useMutation({
    mutationFn: (body: Sources) => call(client.PUT('/api/sources', { ...gv(gameVersion), body })),
    onSuccess: apply,
    onError: showError('Could not use that file'),
  })
}

/** Re-import both addon files even if they look unchanged. */
export function useSyncNow() {
  const gameVersion = useGameVersion()
  const apply = useApplyStatus()
  return useMutation({
    mutationFn: () => call(client.POST('/api/sync', gv(gameVersion))),
    onSuccess: apply,
    onError: showError('Sync failed'),
  })
}

export function useReload() {
  const gameVersion = useGameVersion()
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: () => call(client.POST('/api/reload', gv(gameVersion))),
    onSuccess: () => invalidate(),
    onError: showError('Reload failed'),
  })
}
