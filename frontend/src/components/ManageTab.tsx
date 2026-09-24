import { useState } from 'react'
import { Alert, Autocomplete, Button, Card, Group, Stack, Table, Text, Title } from '@mantine/core'
import type { Sources } from '../api/client'
import {
  useAhBlocked,
  useAltArmyFiles,
  useAuctionatorFiles,
  useReload,
  useSetAhBlocked,
  useSetSources,
  useStatus,
  useSyncNow,
  useUpdateGameData,
} from '../api/queries'
import { ItemLink } from './ItemTooltip'

function AhBlockedCard() {
  const blocked = useAhBlocked()
  const setBlocked = useSetAhBlocked()
  return (
    <Card withBorder>
      <Stack gap="sm">
        <Title order={3}>Never sold on the auction house</Title>
        <Text size="sm" c="dimmed">
          Searches only vendor or disenchant these items. They can still be bought on the auction house.
        </Text>
        {blocked.isError && <Alert color="red">{blocked.error.message}</Alert>}
        {blocked.data && !blocked.data.items.length && (
          <Text size="sm" c="dimmed">
            Use the ⋯ menu on a search result to stop selling an item on the auction house.
          </Text>
        )}
        {blocked.data && blocked.data.items.length > 0 && (
          <Table>
            <Table.Tbody>
              {blocked.data.items.map(({ item_id, added_at }) => {
                const item = blocked.data.details[item_id]
                const name = item?.name ?? `Item ${item_id}`
                return (
                  <Table.Tr key={item_id}>
                    <Table.Td>
                      <ItemLink item={item} name={name} />
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" c="dimmed">
                        added {added_at} UTC
                      </Text>
                    </Table.Td>
                    <Table.Td ta="right">
                      <Button
                        size="xs"
                        variant="default"
                        aria-label={`Allow ${name} on the auction house`}
                        loading={setBlocked.isPending && setBlocked.variables.itemId === item_id}
                        onClick={() => setBlocked.mutate({ itemId: item_id, blocked: false })}
                      >
                        Remove
                      </Button>
                    </Table.Td>
                  </Table.Tr>
                )
              })}
            </Table.Tbody>
          </Table>
        )}
      </Stack>
    </Card>
  )
}

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
          altarmy-profit re-reads them whenever they change.
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
      <AhBlockedCard />
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
