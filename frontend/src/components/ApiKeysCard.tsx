import { useState } from 'react'
import { Alert, Button, Card, Code, CopyButton, Group, Modal, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { useApiKeys, useCreateKey, useRevokeKey } from '../api/queries'

/** The command that runs the watcher against this site with `key`. */
function watchCommand(key: string, origin = globalThis.location?.origin ?? ''): string {
  return `altarmy-profit watch --server ${origin} --key ${key}`
}

/** API keys for the CLI watcher, which uploads the addon files whenever WoW rewrites them. */
export function ApiKeysCard() {
  const keys = useApiKeys()
  const create = useCreateKey()
  const revoke = useRevokeKey()
  const [label, setLabel] = useState('')
  const made = create.data
  return (
    <Card withBorder>
      <Stack gap="sm">
        <Title order={3}>Upload automatically</Title>
        <Text size="sm" c="dimmed">
          <Code>altarmy-profit watch</Code> (the Python package, on the computer you play on) uploads AltArmy_TBC.lua
          and Auctionator.lua whenever WoW rewrites them. It signs in with an API key; a key can only upload.
        </Text>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            create.mutate(label.trim() || 'watcher')
          }}
        >
          <Group align="flex-end">
            <TextInput
              label="New key for"
              placeholder="e.g. gaming PC"
              maxLength={64}
              value={label}
              onChange={(e) => setLabel(e.currentTarget.value)}
            />
            <Button type="submit" loading={create.isPending}>
              Make key
            </Button>
          </Group>
        </form>
        {keys.isError && <Alert color="red">{keys.error.message}</Alert>}
        {keys.data && keys.data.length > 0 && (
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Key</Table.Th>
                <Table.Th>For</Table.Th>
                <Table.Th>Made</Table.Th>
                <Table.Th>Last used</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {keys.data.map((k) => (
                <Table.Tr key={k.id}>
                  <Table.Td>
                    <Code>{k.prefix}…</Code>
                  </Table.Td>
                  <Table.Td>{k.label}</Table.Td>
                  <Table.Td>{k.created_at} UTC</Table.Td>
                  <Table.Td>{k.last_used_at ? `${k.last_used_at} UTC` : 'never'}</Table.Td>
                  <Table.Td ta="right">
                    <Button
                      size="xs"
                      variant="default"
                      color="red"
                      aria-label={`Revoke ${k.label}`}
                      loading={revoke.isPending && revoke.variables === k.id}
                      onClick={() => revoke.mutate(k.id)}
                    >
                      Revoke
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Stack>
      <Modal opened={made !== undefined} onClose={() => create.reset()} title="Your new API key" size="lg">
        {made && (
          <Stack gap="sm">
            <Alert color="yellow">This is the only time the key is shown. Copy it now; revoke it here if it leaks.</Alert>
            <Text size="sm">Install the Python package on the computer you play on, then run:</Text>
            <Code block>{watchCommand(made.key)}</Code>
            <Group>
              <CopyButton value={watchCommand(made.key)}>
                {({ copied, copy }) => (
                  <Button onClick={copy} color={copied ? 'green' : undefined}>
                    {copied ? 'Copied' : 'Copy command'}
                  </Button>
                )}
              </CopyButton>
              <Button variant="default" onClick={() => create.reset()}>
                Done
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Card>
  )
}
