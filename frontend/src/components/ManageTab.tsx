import { useState } from 'react'
import { Alert, Autocomplete, Button, Card, Group, Stack, Text, Title } from '@mantine/core'
import type { Sources } from '../api/client'
import {
  useAltArmyFiles,
  useAuctionatorFiles,
  useReload,
  useSetSources,
  useStatus,
  useSyncNow,
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

/** Pick a SavedVariables file from the ones found, or paste a path; the server syncs from it. */
function SourceFile({
  label,
  files,
  current,
  field,
}: {
  label: string
  files: string[]
  current: string | null
  field: keyof Sources
}) {
  const setSources = useSetSources()
  // null until the user types, so the file in use shows first.
  const [typed, setTyped] = useState<string | null>(null)
  const value = typed ?? current ?? ''
  const path = value.trim()
  return (
    <Group align="flex-end" wrap="nowrap">
      <Autocomplete
        label={label}
        placeholder="Paste the path to the file"
        data={files}
        value={value}
        onChange={setTyped}
        clearable
        style={{ flex: 1 }}
      />
      <Button
        variant="default"
        disabled={!path || path === current}
        loading={setSources.isPending}
        onClick={() => setSources.mutate({ [field]: path })}
      >
        Use this file
      </Button>
    </Group>
  )
}

function AddonDataCard() {
  const status = useStatus()
  const altArmyFiles = useAltArmyFiles()
  const auctionatorFiles = useAuctionatorFiles()
  const sync = useSyncNow()
  if (!status.data) return null
  const s = status.data
  return (
    <Card withBorder>
      <Stack gap="sm">
        <Title order={3}>Addon data</Title>
        <Text size="sm" c="dimmed">
          Characters come from Alt Army and prices from Auctionator. WoW writes both files on logout or /reload;
          wow-profit re-reads them whenever they change.
        </Text>
        {s.warnings.map((w) => (
          <Alert key={w} color="yellow">
            {w}
          </Alert>
        ))}
        <SourceFile
          label="AltArmy_TBC.lua (account-wide SavedVariables)"
          files={altArmyFiles.data?.files ?? []}
          current={s.altarmy_path}
          field="altarmy_path"
        />
        <Text>
          <b>{s.characters.toLocaleString()}</b> characters, last read{' '}
          <b>{s.last_altarmy_sync ? `${s.last_altarmy_sync} UTC` : 'never'}</b>.
        </Text>
        <SourceFile
          label="Auctionator.lua (account-wide SavedVariables)"
          files={auctionatorFiles.data?.files ?? []}
          current={s.auctionator_path}
          field="auctionator_path"
        />
        <Text>
          Prices from <b>{s.auctionator_realm || 'no realm'}</b>
          {s.selection && ` (for ${s.selection.realm}, ${s.selection.faction})`}, last imported{' '}
          <b>{s.last_auctionator_import ? `${s.last_auctionator_import} UTC` : 'never'}</b>.
        </Text>
        <Group>
          <Button onClick={() => sync.mutate()} loading={sync.isPending}>
            Sync now
          </Button>
        </Group>
      </Stack>
    </Card>
  )
}

export function ManageTab() {
  const reload = useReload()
  return (
    <Stack>
      <GameDataCard />
      <AddonDataCard />
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
