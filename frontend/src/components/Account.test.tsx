import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { linkWithEmail, linkWithGoogle } from '../lib/auth'
import { GUEST, mockApi, renderWithProviders } from '../test/utils'
import { AccountStatus } from './Account'

vi.mock('../lib/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/auth')>()),
  getIdToken: vi.fn(async () => null),
  linkWithGoogle: vi.fn(async () => {}),
  linkWithEmail: vi.fn(async () => {}),
}))

describe('linking an account', () => {
  afterEach(() => vi.clearAllMocks())

  it('links Google from the guest header', async () => {
    mockApi({})
    renderWithProviders(<AccountStatus />, GUEST)
    expect(screen.getByText('Guest')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Link account' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Continue with Google' }))
    await waitFor(() => expect(linkWithGoogle).toHaveBeenCalledOnce())
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('links an email address, and explains a failure', async () => {
    vi.mocked(linkWithEmail).mockRejectedValueOnce(Object.assign(new Error('x'), { code: 'auth/email-already-in-use' }))
    renderWithProviders(<AccountStatus />, GUEST)
    await userEvent.click(screen.getByRole('button', { name: 'Link account' }))
    await userEvent.type(await screen.findByLabelText(/Email/), 'me@example.com')
    await userEvent.type(screen.getByLabelText(/Password/), 'hunter22')
    await userEvent.click(screen.getByRole('button', { name: 'Link with email' }))
    expect(await screen.findByText(/already belongs to another altarmy-profit user/)).toBeInTheDocument()
    expect(linkWithEmail).toHaveBeenCalledWith('me@example.com', 'hunter22')
  })

  it('shows a linked account as such', () => {
    renderWithProviders(<AccountStatus />, { ...GUEST, tier: 'linked' })
    expect(screen.getByText('Linked account')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Link account' })).not.toBeInTheDocument()
  })
})
