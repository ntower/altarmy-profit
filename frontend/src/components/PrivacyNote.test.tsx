import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { signOut } from '../lib/auth'
import { GUEST, mockApi, renderWithProviders } from '../test/utils'
import { PrivacyNote } from './PrivacyNote'

vi.mock('../lib/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/auth')>()),
  getIdToken: vi.fn(async () => null),
  signOut: vi.fn(async () => {}),
}))

async function openAndConfirm() {
  renderWithProviders(<PrivacyNote />, GUEST)
  await userEvent.click(screen.getByRole('button', { name: 'Privacy' }))
  expect(await screen.findByText(/Uploaded addon files are read and thrown away/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Delete my account…' }))
  await userEvent.click(screen.getByRole('button', { name: 'Delete everything' }))
}

describe('privacy note', () => {
  afterEach(() => vi.clearAllMocks())

  it('deletes the account, then starts a new guest session', async () => {
    const fetch = mockApi({ '/api/me': null })
    await openAndConfirm()
    await waitFor(() => expect(signOut).toHaveBeenCalled())
    const request = fetch.mock.calls[0][0]
    expect([request.method, new URL(request.url).pathname]).toEqual(['DELETE', '/api/me'])
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('keeps the session when the server could not delete it', async () => {
    mockApi({})
    await openAndConfirm()
    expect(await screen.findByText('no mock for /api/me')).toBeInTheDocument()
    expect(signOut).not.toHaveBeenCalled()
  })
})
