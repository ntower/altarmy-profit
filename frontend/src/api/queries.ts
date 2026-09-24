import { notifications } from '@mantine/notifications'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { call, client, type ImportRequest } from './client'

export function useStatus() {
  return useQuery({ queryKey: ['status'], queryFn: () => call(client.GET('/api/status')) })
}

export function useProfessions() {
  return useQuery({ queryKey: ['professions'], queryFn: () => call(client.GET('/api/professions')) })
}

/** Ranked recipes; `minProfit` is copper. Disabled until at least one profession is picked. */
export function useRank(professions: string[], minProfit: number, top: number) {
  return useQuery({
    queryKey: ['rank', professions, minProfit, top],
    queryFn: () =>
      call(client.GET('/api/rank', { params: { query: { professions, min_profit: minProfit, top } } })),
    enabled: professions.length > 0,
    placeholderData: keepPreviousData,
  })
}

export function useAuctionatorFiles() {
  return useQuery({
    queryKey: ['auctionator', 'files'],
    queryFn: () => call(client.GET('/api/auctionator/files')),
  })
}

export function useAuctionatorRealms(path: string) {
  return useQuery({
    queryKey: ['auctionator', 'realms', path],
    queryFn: () => call(client.GET('/api/auctionator/realms', { params: { query: { path } } })),
    enabled: path !== '',
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

export function useUpdateGameData() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: () => call(client.POST('/api/game-data/update')),
    onSuccess: (r) => {
      notifications.show({
        color: 'green',
        title: 'Game data updated',
        message: `Loaded build ${r.build}: ${r.items.toLocaleString()} items, ${r.recipes.toLocaleString()} recipes.`,
      })
      return invalidate()
    },
    onError: showError('Update failed'),
  })
}

export function useImportAuctionator() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (body: ImportRequest) => call(client.POST('/api/auctionator/import', { body })),
    onSuccess: (r) => {
      notifications.show({
        color: 'green',
        title: 'Prices imported',
        message: `Imported ${r.imported.toLocaleString()} prices from ${r.realm} (${r.unknown.toLocaleString()} items not in the game data).`,
      })
      return invalidate()
    },
    onError: showError('Import failed'),
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
