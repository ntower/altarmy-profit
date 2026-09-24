import { useState } from 'react'
import { Alert, Badge, Button, Divider, Group, Modal, PasswordInput, Stack, Text, TextInput } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useQueryClient } from '@tanstack/react-query'
import { linkErrorMessage, linkWithEmail, linkWithGoogle } from '../lib/auth'
import { useSession } from '../lib/session'

/** Link the anonymous session to a Google or email account; the uid, and so the user's data, stays. */
function LinkModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState<'google' | 'email' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const link = async (how: 'google' | 'email') => {
    setBusy(how)
    setError(null)
    try {
      await (how === 'google' ? linkWithGoogle() : linkWithEmail(email.trim(), password))
      await queryClient.invalidateQueries({ queryKey: ['me'] })
      notifications.show({ color: 'green', title: 'Account linked', message: 'Rankings and every price are unlocked.' })
      onClose()
    } catch (e) {
      setError(linkErrorMessage(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <Modal opened={opened} onClose={onClose} title="Link your account">
      <Stack>
        <Text size="sm">
          Linking keeps everything this browser has done so far and unlocks rankings, characters and prices of every
          item.
        </Text>
        {error && <Alert color="red">{error}</Alert>}
        <Button onClick={() => void link('google')} loading={busy === 'google'} disabled={busy === 'email'}>
          Continue with Google
        </Button>
        <Divider label="or with an email address" />
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void link('email')
          }}
        >
          <Stack gap="sm">
            <TextInput label="Email" type="email" value={email} onChange={(e) => setEmail(e.currentTarget.value)} required />
            <PasswordInput
              label="Password"
              value={password}
              onChange={(e) => setPassword(e.currentTarget.value)}
              required
            />
            <Button type="submit" variant="default" loading={busy === 'email'} disabled={busy === 'google'}>
              Link with email
            </Button>
          </Stack>
        </form>
      </Stack>
    </Modal>
  )
}

export function LinkAccountButton({ size = 'sm' }: { size?: 'xs' | 'sm' }) {
  const [opened, setOpened] = useState(false)
  return (
    <>
      <Button size={size} onClick={() => setOpened(true)}>
        Link account
      </Button>
      <LinkModal opened={opened} onClose={() => setOpened(false)} />
    </>
  )
}

/** Hosted mode's header: the tier, and the way to leave the free one. */
export function AccountStatus() {
  const { tier } = useSession()
  return tier === 'linked' ? (
    <Badge variant="light" color="green">
      Linked account
    </Badge>
  ) : (
    <Group gap="xs">
      <Badge variant="light" color="gray">
        Guest
      </Badge>
      <LinkAccountButton size="xs" />
    </Group>
  )
}

/** Shown to free users above the tabs. */
export function LinkPrompt() {
  const { freeMaxLevel } = useSession()
  return (
    <Alert color="blue" title="You are browsing as a guest" mb="md">
      <Group justify="space-between" align="center">
        <Text size="sm">
          Guests see auction prices of items up to level {freeMaxLevel}. Link a Google or email account to unlock
          profit rankings, your characters and every price.
        </Text>
        <LinkAccountButton />
      </Group>
    </Alert>
  )
}
