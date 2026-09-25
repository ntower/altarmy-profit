import { useState } from 'react'
import { Alert, Badge, Button, Card, Code, FileInput, Group, Stack, Table, Text, Title } from '@mantine/core'
import type { components } from '../api/schema'
import { useCoverage, useUpload, useUploads, type UploadKind } from '../api/queries'
import { age } from '../lib/age'
import { GAME_VERSIONS, useGameVersion } from '../lib/gameVersion'
import { useSession } from '../lib/session'

type UploadResult = components['schemas']['UploadResult']

const MAX_MB = 32

const FILES: readonly { kind: UploadKind; name: string; what: string }[] = [
  { kind: 'altarmy', name: 'AltArmy_TBC.lua', what: 'your characters, professions and learned recipes' },
  { kind: 'auctionator', name: 'Auctionator.lua', what: 'auction prices of every realm you scanned' },
]

function Summary({ result }: { result: UploadResult }) {
  if (result.kind === 'altarmy') {
    return (
      <Text size="sm">
        Imported {result.characters} characters
        {result.groups.length > 0 && `: ${result.groups.map((g) => `${g.realm} (${g.faction || 'no faction'}) ${g.characters}`).join(', ')}`}
        .
      </Text>
    )
  }
  if (!result.realms.length) return <Text size="sm">No realm in the file has prices.</Text>
  return (
    <Stack gap={4}>
      {result.realms.map((r) => (
        <Group key={r.key} gap="xs">
          <Text size="sm">
            {r.realm}
            {r.faction ? ` (${r.faction})` : ''}: {r.items} prices
            {r.quarantined ? '' : `, ${r.moved} changed`}
          </Text>
          {r.quarantined && (
            <Badge color="yellow" variant="light" title="They differ widely from recent scans of this realm">
              not used
            </Badge>
          )}
        </Group>
      ))}
    </Stack>
  )
}

/** Each realm's newest scan, stalest first: where uploads are needed. */
function CoverageCard() {
  const coverage = useCoverage()
  if (!coverage.data?.length) return null
  const stalest = [...coverage.data].sort((a, b) => (a.last_scan ?? '').localeCompare(b.last_scan ?? ''))
  return (
    <Card withBorder>
      <Stack gap="sm">
        <Title order={4}>Coverage</Title>
        <Text size="sm" c="dimmed">
          Every user's scans price these auction houses. The stalest come first: a scan there helps the most.
        </Text>
        <Table aria-label="Coverage">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Realm</Table.Th>
              <Table.Th>Last scan</Table.Th>
              <Table.Th ta="right">Items in it</Table.Th>
              <Table.Th ta="right">Prices</Table.Th>
              <Table.Th ta="right">Scans (7 days)</Table.Th>
              <Table.Th ta="right">Uploaders (7 days)</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {stalest.map((c) => (
              <Table.Tr key={c.auction_house_id}>
                <Table.Td>
                  {c.realm}
                  {c.faction ? ` (${c.faction})` : ''}
                </Table.Td>
                <Table.Td title={c.last_scan ? `${c.last_scan} UTC` : undefined}>
                  {c.last_scan ? age(c.last_scan) : 'never'}
                </Table.Td>
                <Table.Td ta="right">{c.last_scan_items.toLocaleString()}</Table.Td>
                <Table.Td ta="right">{c.prices.toLocaleString()}</Table.Td>
                <Table.Td ta="right">{c.scans_7d}</Table.Td>
                <Table.Td ta="right">{c.uploaders_7d}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Stack>
    </Card>
  )
}

function UploadCard({ kind, name, what }: { kind: UploadKind; name: string; what: string }) {
  const gameVersion = useGameVersion()
  const game = GAME_VERSIONS.find((v) => v.value === gameVersion)
  const upload = useUpload()
  const [file, setFile] = useState<File | null>(null)
  const tooBig = file !== null && file.size > MAX_MB * 2 ** 20
  return (
    <Card withBorder>
      <Stack gap="sm">
        <Title order={4}>{name}</Title>
        <Text size="sm" c="dimmed">
          Brings in {what}. It is in{' '}
          <Code>
            World of Warcraft\{game?.flavor}\WTF\Account\&lt;account&gt;\SavedVariables\{name}
          </Code>
          ; WoW writes it on logout or /reload.
        </Text>
        <Group align="flex-end">
          <FileInput
            label={`${name} for ${game?.label ?? gameVersion}`}
            placeholder={`Pick ${name}`}
            accept=".lua"
            value={file}
            onChange={(f) => {
              setFile(f)
              upload.reset()
            }}
            clearable
            w={360}
          />
          <Button disabled={!file || tooBig} loading={upload.isPending} onClick={() => file && upload.mutate({ kind, file })}>
            Upload
          </Button>
        </Group>
        {tooBig && <Alert color="red">Files are limited to {MAX_MB} MB.</Alert>}
        {upload.isError && <Alert color="red">{upload.error.message}</Alert>}
        {upload.data && (
          <Alert
            color={upload.data.realms.some((r) => r.quarantined) ? 'yellow' : 'green'}
            title={
              upload.data.realms.some((r) => r.quarantined)
                ? 'Uploaded, but some prices were not used: they differ widely from recent scans'
                : 'Uploaded'
            }
          >
            <Summary result={upload.data} />
          </Alert>
        )}
      </Stack>
    </Card>
  )
}

function History() {
  const uploads = useUploads()
  if (!uploads.data?.length) return null
  return (
    <Card withBorder>
      <Stack gap="sm">
        <Title order={4}>Your recent uploads</Title>
        <Table>
          <Table.Tbody>
            {uploads.data.map((u) => (
              <Table.Tr key={u.id}>
                <Table.Td>{u.received_at} UTC</Table.Td>
                <Table.Td>
                  {u.kind === 'altarmy' ? 'AltArmy_TBC.lua' : 'Auctionator.lua'} ({u.game_version}, {u.via})
                </Table.Td>
                <Table.Td>
                  <Badge color={u.outcome === 'accepted' ? 'green' : 'red'} variant="light">
                    {u.outcome}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{u.detail}</Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Stack>
    </Card>
  )
}

/** Hosted mode's way in for addon data: upload the SavedVariables files (or run the watcher, see Manage). */
export function UploadTab() {
  const { tier } = useSession()
  return (
    <Stack>
      {tier === 'free' && (
        <Alert color="blue">
          Your characters are kept: link your account to rank what they can craft. Everyone's price uploads fill in
          the auction houses for all users.
        </Alert>
      )}
      {FILES.map((f) => (
        <UploadCard key={f.kind} {...f} />
      ))}
      <History />
      <CoverageCard />
    </Stack>
  )
}
