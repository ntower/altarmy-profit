import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { linkWithEmail, resetPassword, signInWithEmail, signOut } from '../lib/auth'
import { GUEST, LINKED, mockApi, renderWithProviders } from '../test/utils'
import { AccountStatus } from './Account'

vi.mock('../lib/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/auth')>()),
  getIdToken: vi.fn(async () => null),
  currentEmail: vi.fn(() => 'me@example.com'),
  linkWithEmail: vi.fn(async () => {}),
  signInWithEmail: vi.fn(async () => {}),
  resetPassword: vi.fn(async () => {}),
  signOut: vi.fn(async () => {}),
}))

async function fill(email: string, password = '') {
  await userEvent.type(await screen.findByLabelText(/Email/), email)
  if (password) await userEvent.type(screen.getByLabelText(/Password/), password)
}

describe('account', () => {
  afterEach(() => vi.clearAllMocks())

  it('links an email to the guest account', async () => {
    mockApi({})
    renderWithProviders(<AccountStatus />, GUEST)
    expect(screen.getByText('Guest')).toBeInTheDocument()
    expect(screen.queryByText(/Google/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Link account' }))
    await fill('me@example.com', 'hunter22')
    await userEvent.click(screen.getAllByRole('button', { name: 'Link account' }).at(-1)!)
    await waitFor(() => expect(linkWithEmail).toHaveBeenCalledWith('me@example.com', 'hunter22'))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('points a taken email to signing in', async () => {
    vi.mocked(linkWithEmail).mockRejectedValueOnce(Object.assign(new Error('x'), { code: 'auth/email-already-in-use' }))
    renderWithProviders(<AccountStatus />, GUEST)
    await userEvent.click(screen.getByRole('button', { name: 'Link account' }))
    await fill('me@example.com', 'hunter22')
    await userEvent.click(screen.getAllByRole('button', { name: 'Link account' }).at(-1)!)
    expect(await screen.findByText('That email already has an account: sign in instead.')).toBeInTheDocument()
  })

  it('signs in to an existing account, and explains a wrong password', async () => {
    vi.mocked(signInWithEmail).mockRejectedValueOnce(Object.assign(new Error('x'), { code: 'auth/invalid-credential' }))
    renderWithProviders(<AccountStatus />, GUEST)
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await fill('me@example.com', 'wrong')
    await userEvent.click(screen.getAllByRole('button', { name: 'Sign in' }).at(-1)!)
    expect(await screen.findByText('Wrong email or password.')).toBeInTheDocument()
    await userEvent.clear(screen.getByLabelText(/Password/))
    await userEvent.type(screen.getByLabelText(/Password/), 'right')
    await userEvent.click(screen.getAllByRole('button', { name: 'Sign in' }).at(-1)!)
    await waitFor(() => expect(signInWithEmail).toHaveBeenLastCalledWith('me@example.com', 'right'))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('sends a password reset email', async () => {
    renderWithProviders(<AccountStatus />, GUEST)
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await fill('me@example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Forgot password?' }))
    expect(await screen.findByText(/a link to set a new password is on its way/)).toBeInTheDocument()
    expect(resetPassword).toHaveBeenCalledWith('me@example.com')
  })

  it('shows the linked email and signs out', async () => {
    renderWithProviders(<AccountStatus />, LINKED)
    expect(screen.getByText('me@example.com')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Link account' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(signOut).toHaveBeenCalledOnce()
  })
})
