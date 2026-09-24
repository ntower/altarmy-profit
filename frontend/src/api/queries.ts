import { useEffect, useRef } from 'react'
import { notifications } from '@mantine/notifications'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { call, client, type Selection, type Sources, type Status, type UpdateResult } from './client'
import { importedSince, readSyncSeen, syncSeen, writeSyncSeen } from '../lib/syncNotice'

/**
 * Server status. Fetching it also makes the server re-import the Alt Army and Auctionator files if WoW
 * rewrote them (on logout or /reload), so poll it, and refetch when the user comes back from the game.
 */
export function useStatus() {
  return useQuery({
    queryKey: ['status'],
    queryFn: () => call(client.GET('/api/status')),
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  })
}

/** Bumped by the server whenever a sync re-imported something; part of the keys of data it affects. */
function useDataVersion() {
  return useStatus().data?.data_version
}

export function useCharacters() {
  const version = useDataVersion()
  return useQuery({
    queryKey: ['characters', version],
    queryFn: () => call(client.GET('/api/characters')),
    enabled: version !== undefined,
    placeholderData: keepPreviousData,
  })
}

export type Exit = 'vendor' | 'disenchant' | 'ah'

/** `/api/rank` parameters: money in copper, ROI as a fraction (0.5 = 50%), `null` for no bound. */
export type RankParams = {
  includeUnlearned: boolean
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
  const version = useDataVersion()
  return useQuery({
    queryKey: ['rank', version, params],
    queryFn: () =>
      call(
        client.GET('/api/rank', {
          params: {
            query: {
              include_unlearned: params.includeUnlearned,
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

export function useAuctionatorFiles() {
  return useQuery({
    queryKey: ['auctionator', 'files'],
    queryFn: () => call(client.GET('/api/auctionator/files')),
  })
}

export function useAltArmyFiles() {
  return useQuery({
    queryKey: ['altarmy', 'files'],
    queryFn: () => call(client.GET('/api/altarmy/files')),
  })
}

function showError(title: string) {
  return (error: Error) => notifications.show({ color: 'red', title, message: error.message })
}

/** Every mutation changes the database, so refetch everything afterwards. */
function useInvalidateAll() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries()
}

function updateGameData(onlyIfNew: boolean) {
  return call(client.POST('/api/game-data/update', { params: { query: { only_if_new: onlyIfNew } } }))
}

function showUpdated(r: UpdateResult, title: string) {
  notifications.show({
    color: 'green',
    title,
    message: `Loaded build ${r.build}: ${r.items.toLocaleString()} items, ${r.recipes.toLocaleString()} recipes.`,
  })
}

export function useUpdateGameData() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: () => updateGameData(false),
    onSuccess: (r) => {
      showUpdated(r, 'Game data updated')
      return invalidate()
    },
    onError: showError('Update failed'),
  })
}

/**
 * Once per page load, fetch the newest game build if the database does not have it yet. Failures only
 * go to the console: being offline should not raise a toast on every visit.
 */
export function useAutoUpdateGameData() {
  const invalidate = useInvalidateAll()
  const { mutate } = useMutation({
    mutationFn: () => updateGameData(true),
    onSuccess: (r) => {
      if (!r.updated) return
      showUpdated(r, 'New game data downloaded')
      return invalidate()
    },
    onError: (error) => console.warn('Automatic game data update failed:', error),
  })
  const started = useRef(false) // StrictMode runs effects twice in development
  useEffect(() => {
    if (started.current) return
    started.current = true
    mutate()
  }, [mutate])
}

/**
 * Toast whenever the server's addon sync re-imported Alt Army or Auctionator data: while the page is
 * open (status polling), or since it was last open.
 */
export function useSyncNotifications() {
  const status = useStatus().data
  useEffect(() => {
    if (!status) return
    const lines = importedSince(readSyncSeen(), status)
    writeSyncSeen(syncSeen(status))
    if (lines.length) notifications.show({ color: 'green', title: 'Addon data imported', message: lines.join(' ') })
  }, [status])
}

/** The mutations below answer with the new status: show it at once, then refetch the rest. */
function useApplyStatus() {
  const queryClient = useQueryClient()
  return (status: Status) => {
    queryClient.setQueryData(['status'], status)
    return queryClient.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'status' })
  }
}

/** Switch realm/faction; the server swaps in that realm's Auctionator prices. */
export function useSelectRealm() {
  const apply = useApplyStatus()
  return useMutation({
    mutationFn: (body: Selection) => call(client.PUT('/api/selection', { body })),
    onSuccess: apply,
    onError: showError('Could not switch realm'),
  })
}

export function useSetSources() {
  const apply = useApplyStatus()
  return useMutation({
    mutationFn: (body: Sources) => call(client.PUT('/api/sources', { body })),
    onSuccess: apply,
    onError: showError('Could not use that file'),
  })
}

/** Re-import both addon files even if they look unchanged. */
export function useSyncNow() {
  const apply = useApplyStatus()
  return useMutation({
    mutationFn: () => call(client.POST('/api/sync')),
    onSuccess: apply,
    onError: showError('Sync failed'),
  })
}

export function useReload() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: () => call(client.POST('/api/reload')),
    onSuccess: () => invalidate(),
    onError: showError('Reload failed'),
  })
}
