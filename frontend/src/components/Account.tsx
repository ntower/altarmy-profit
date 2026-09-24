import { useState } from 'react'
import { Alert, Anchor, Badge, Button, Group, Modal, PasswordInput, Stack, Text, TextInput } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useQueryClient } from '@tanstack/react-query'
import { authErrorMessage, currentEmail, linkWithEmail, resetPassword, signInWithEmail, signOut } from '../lib/auth'
import { useSession } from '../lib/session'

type Mode = 'link' | 'sign-in'

const TITLES: Readonly<Record<Mode, string>> = { link: 'Link your account', 'sign-in': 'Sign in' }

/**
 * Link this browser's guest account to an email and password (same uid, so its data stays), or sign in to an
 * account made before, e.g. on another computer.
 */
function AccountModal({ mode, onClose }: { mode: Mode | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const run = async (action: () => Promise<void>, done: () => void) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await action()
      done()
    } catch (e) {
      setError(authErrorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const submit = () =>
    run(
      () => (mode === 'link' ? linkWithEmail(email.trim(), password) : signInWithEmail(email.trim(), password)),
      () => {
        void queryClient.invalidateQueries({ queryKey: ['me'] })
        notifications.show({
          color: 'green',
          title: mode === 'link' ? 'Account linked' : 'Signed in',
          message: mode === 'link' ? 'Rankings and every price are unlocked.' : `Welcome back, ${email.trim()}.`,
        })
        onClose()
      },
    )

  const forgot = () =>
    run(
      () => resetPassword(email.trim()),
      () => setNotice(`If ${email.trim()} has an account, a link to set a new password is on its way.`),
    )

  return (
    <Modal opened={mode !== null} onClose={onClose} title={mode ? TITLES[mode] : ''}>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <Stack gap="sm">
          <Text size="sm">
            {mode === 'link'
              ? 'Linking keeps everything this browser has done so far and unlocks rankings, characters and prices of every item.'
              : 'Sign in to the account you linked before. What you did as a guest in this browser stays with the guest session.'}
          </Text>
          {error && <Alert color="red">{error}</Alert>}
          {notice && <Alert color="green">{notice}</Alert>}
          <TextInput label="Email" type="email" value={email} onChange={(e) => setEmail(e.currentTarget.value)} required />
          <PasswordInput label="Password" value={password} onChange={(e) => setPassword(e.currentTarget.value)} required />
          <Group justify="space-between">
            {mode === 'sign-in' ? (
              <Anchor component="button" type="button" size="sm" onClick={() => void forgot()} disabled={busy}>
                Forgot password?
              </Anchor>
            ) : (
              <span />
            )}
            <Button type="submit" loading={busy}>
              {mode === 'link' ? 'Link account' : 'Sign in'}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  )
}

/** Opens the account modal; `mode` picks linking a guest account or signing in to an existing one. */
function AccountButton({ mode, size = 'sm', variant }: { mode: Mode; size?: 'xs' | 'sm'; variant?: 'default' }) {
  const [open, setOpen] = useState<Mode | null>(null)
  return (
    <>
      <Button size={size} variant={variant} onClick={() => setOpen(mode)}>
        {mode === 'link' ? 'Link account' : 'Sign in'}
      </Button>
      <AccountModal key={open ?? 'closed'} mode={open} onClose={() => setOpen(null)} />
    </>
  )
}

function SignOutButton() {
  const [busy, setBusy] = useState(false)
  return (
    <Button
      size="xs"
      variant="default"
      loading={busy}
      onClick={async () => {
        setBusy(true)
        try {
          await signOut()
        } catch (e) {
          notifications.show({ color: 'red', title: 'Could not sign out', message: authErrorMessage(e) })
        } finally {
          setBusy(false)
        }
      }}
    >
      Sign out
    </Button>
  )
}

/** Hosted mode's header: who is signed in, and the ways in and out. */
export function AccountStatus() {
  const { tier } = useSession()
  if (tier === 'linked') {
    return (
      <Group gap="xs">
        <Badge variant="light" color="green">
          {currentEmail() ?? 'Linked account'}
        </Badge>
        <SignOutButton />
      </Group>
    )
  }
  return (
    <Group gap="xs">
      <Badge variant="light" color="gray">
        Guest
      </Badge>
      <AccountButton mode="link" size="xs" />
      <AccountButton mode="sign-in" size="xs" variant="default" />
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
          Guests see auction prices of items up to level {freeMaxLevel}. Link an email address to unlock profit
          rankings, your characters and every price.
        </Text>
        <AccountButton mode="link" />
      </Group>
    </Alert>
  )
}
