import { useState } from 'react'
import { Alert, Anchor, Button, Group, List, Modal, Stack, Text } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useQueryClient } from '@tanstack/react-query'
import { client } from '../api/client'
import { authErrorMessage, signOut } from '../lib/auth'

/** Delete the account on the server (data, then the sign-in account), then start a fresh guest session. */
function DeleteAccount({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const remove = async () => {
    setBusy(true)
    setError(null)
    try {
      const { response, error } = await client.DELETE('/api/me')
      const body: unknown = error
      if (!response.ok) {
        const detail = body && typeof body === 'object' && 'detail' in body ? String(body.detail) : response.statusText
        throw new Error(detail)
      }
      await signOut()
      queryClient.clear()
      notifications.show({ color: 'green', title: 'Account deleted', message: 'You are now a new guest.' })
      onDone()
    } catch (e) {
      setError(authErrorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  if (!confirming) {
    return (
      <Group justify="flex-end">
        <Button color="red" variant="light" onClick={() => setConfirming(true)}>
          Delete my account…
        </Button>
      </Group>
    )
  }
  return (
    <Alert color="red" title="Delete your account?">
      <Stack gap="xs">
        <Text size="sm">
          Your characters, settings, upload history and API keys are deleted, and so is the sign-in account. This
          can't be undone.
        </Text>
        {error && <Text size="sm">{error}</Text>}
        <Group justify="flex-end">
          <Button variant="default" onClick={() => setConfirming(false)} disabled={busy}>
            Keep it
          </Button>
          <Button color="red" loading={busy} onClick={() => void remove()}>
            Delete everything
          </Button>
        </Group>
      </Stack>
    </Alert>
  )
}

/** Hosted mode's footer: what the site stores, and deleting the account. */
export function PrivacyNote() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Group justify="center" mt="xl">
        <Anchor component="button" type="button" size="sm" c="dimmed" onClick={() => setOpen(true)}>
          Privacy
        </Anchor>
      </Group>
      <Modal opened={open} onClose={() => setOpen(false)} title="Privacy" size="lg">
        <Stack gap="sm">
          <List size="sm" spacing="xs">
            <List.Item>
              Uploaded addon files are read and thrown away. Only what the app needs is kept: your characters'
              names, realms, levels, professions and known recipes, and auction prices.
            </List.Item>
            <List.Item>
              Auction prices are pooled for everyone on the same realm. They aren't shown with your name or
              account.
            </List.Item>
            <List.Item>
              Each upload is logged (kind, size, time, result) for your history and the upload limit. API keys are
              stored only as hashes.
            </List.Item>
            <List.Item>
              Sign-in is handled by Firebase Authentication. Your email and password live there, not in this app's
              database.
            </List.Item>
          </List>
          <DeleteAccount onDone={() => setOpen(false)} />
        </Stack>
      </Modal>
    </>
  )
}
