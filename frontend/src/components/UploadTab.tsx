import { useState } from 'react'
import { Alert, Badge, Button, Card, Code, FileInput, Group, Stack, Table, Text, Title } from '@mantine/core'
import type { components } from '../api/schema'
import { useUpload, useUploads, type UploadKind } from '../api/queries'
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
    <Text size="sm">
      {result.realms.map((r) => `${r.realm}${r.faction ? ` (${r.faction})` : ''}: ${r.items} prices, ${r.moved} changed`).join('; ')}
    </Text>
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
          <Alert color="green" title="Uploaded">
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
    </Stack>
  )
}
