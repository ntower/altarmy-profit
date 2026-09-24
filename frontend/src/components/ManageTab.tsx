import { useState } from 'react'
import { Alert, Autocomplete, Button, Card, Group, Loader, Select, Stack, Text, Title } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import {
  useAuctionatorFiles,
  useAuctionatorRealms,
  useImportAuctionator,
  useReload,
  useStatus,
  useUpdateGameData,
} from '../api/queries'

function GameDataCard() {
  const status = useStatus()
  const update = useUpdateGameData()
  return (
    <Card withBorder>
      <Stack gap="sm">
        <Title order={3}>Game data</Title>
        {status.data && (
          <Text>
            Build <b>{status.data.build ?? 'none'}</b>: {status.data.items.toLocaleString()} items,{' '}
            {status.data.recipes.toLocaleString()} recipes.
          </Text>
        )}
        <Group>
          <Button onClick={() => update.mutate()} loading={update.isPending}>
            Download latest game data
          </Button>
          {update.isPending && (
            <Text size="sm" c="dimmed">
              Downloading DB2 tables from wago.tools and rebuilding...
            </Text>
          )}
        </Group>
      </Stack>
    </Card>
  )
}

function RealmImport({ path }: { path: string }) {
  const realms = useAuctionatorRealms(path)
  const importPrices = useImportAuctionator()
  const [picked, setPicked] = useState<string | null>(null)

  if (!path) return null
  if (realms.isPending) return <Loader size="sm" />
  if (realms.isError) return <Alert color="red">{realms.error.message}</Alert>
  if (!realms.data.realms.length) {
    return <Alert color="yellow">No realms in this file yet. Scan the auction house first.</Alert>
  }
  const realm = picked !== null && realms.data.realms.includes(picked) ? picked : realms.data.default
  return (
    <Group align="flex-end">
      <Select label="Realm" data={realms.data.realms} value={realm} onChange={setPicked} allowDeselect={false} />
      <Button
        disabled={!realm}
        loading={importPrices.isPending}
        onClick={() => realm && importPrices.mutate({ path, realm })}
      >
        Import prices
      </Button>
    </Group>
  )
}

function AuctionatorCard() {
  const status = useStatus()
  const files = useAuctionatorFiles()
  // null until the user types, so the server's default (last import, else WoW: Forever) shows first.
  const [typed, setTyped] = useState<string | null>(null)
  const path = (typed ?? files.data?.default ?? '').trim()
  const [debouncedPath] = useDebouncedValue(path, 400)
  const last = status.data?.last_auctionator_import

  return (
    <Card withBorder>
      <Stack gap="sm">
        <Title order={3}>Auctionator prices</Title>
        <Text>
          Last import: <b>{last ? `${last} UTC` : 'never'}</b>
        </Text>
        <Text size="sm" c="dimmed">
          WoW writes SavedVariables on logout or /reload, so do one of those after scanning.
        </Text>
        <Autocomplete
          label="Auctionator.lua (account-wide SavedVariables)"
          placeholder="Paste the path to Auctionator.lua"
          data={files.data?.files ?? []}
          value={typed ?? files.data?.default ?? ''}
          onChange={setTyped}
          clearable
        />
        <RealmImport path={debouncedPath} />
      </Stack>
    </Card>
  )
}

export function ManageTab() {
  const reload = useReload()
  return (
    <Stack>
      <GameDataCard />
      <AuctionatorCard />
      <Group>
        <Button variant="default" onClick={() => reload.mutate()} loading={reload.isPending}>
          Reload data
        </Button>
        <Text size="sm" c="dimmed">
          Re-read the database after changing it from the command line.
        </Text>
      </Group>
    </Stack>
  )
}
