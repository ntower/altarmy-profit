import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { components } from '../api/schema'
import { LINKED, mockApi, renderWithProviders } from '../test/utils'
import { ApiKeysCard } from './ApiKeysCard'

type ApiKeyOut = components['schemas']['ApiKeyOut']

const pc: ApiKeyOut = { id: 1, prefix: 'ak_abcde', label: 'gaming pc', created_at: '2026-09-24 20:00:00', last_used_at: null }

describe('ApiKeysCard', () => {
  it('makes a key, shows it once with the watch command, and revokes keys', async () => {
    let keys: ApiKeyOut[] = []
    const fetch = mockApi({
      '/api/keys': () => keys,
      '/api/keys/1': () => [],
    })
    fetch.mockImplementation(async (request: Request) => {
      const path = new URL(request.url).pathname
      let body: unknown = keys
      if (request.method === 'POST') {
        keys = [pc]
        body = { ...pc, key: 'ak_abcdefghSECRET' }
      } else if (path === '/api/keys/1') {
        keys = []
        body = []
      }
      return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    renderWithProviders(<ApiKeysCard />, LINKED)
    await userEvent.type(screen.getByLabelText('New key for'), 'gaming pc')
    await userEvent.click(screen.getByRole('button', { name: 'Make key' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/altarmy-profit watch --server http:\/\/localhost:\d+ --key ak_abcdefghSECRET/)).toBeInTheDocument()
    expect(within(dialog).getByText(/only time the key is shown/)).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Done' }))
    await waitFor(() => expect(screen.queryByText(/ak_abcdefghSECRET/)).not.toBeInTheDocument())

    expect(await screen.findByText('ak_abcde…')).toBeInTheDocument() // only the prefix stays
    expect(screen.getByText('never')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Revoke gaming pc' }))
    await waitFor(() => expect(screen.queryByText('ak_abcde…')).not.toBeInTheDocument())
    const post = fetch.mock.calls.map(([r]) => r).find((r) => r.method === 'POST')
    expect(await post!.json()).toEqual({ label: 'gaming pc' })
  })
})
