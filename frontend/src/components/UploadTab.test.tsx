import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { components } from '../api/schema'
import { GUEST, LINKED, mockApi, renderWithProviders } from '../test/utils'
import { UploadTab } from './UploadTab'

type UploadResult = components['schemas']['UploadResult']
type UploadOut = components['schemas']['UploadOut']

const characters: UploadResult = {
  kind: 'altarmy',
  detail: '3 characters',
  characters: 3,
  groups: [
    { realm: 'Classic Beta PvE', faction: 'Horde', characters: 1 },
    { realm: 'Dreamscythe', faction: 'Horde', characters: 2 },
  ],
  realms: [],
}

const history: UploadOut[] = [
  {
    id: 2,
    game_version: 'forever',
    kind: 'auctionator',
    via: 'watcher',
    size: 90000,
    received_at: '2026-09-24 20:00:00',
    outcome: 'rejected',
    detail: 'no AUCTIONATOR_PRICE_DATABASE in file',
  },
]

/** Mantine's FileInput is a button over a hidden file input: the Alt Army card's comes first. */
const fileInput = () => document.querySelector<HTMLInputElement>('input[type="file"]')!

describe('UploadTab', () => {
  it('uploads a file for the chosen game and shows what it imported', async () => {
    const fetch = mockApi({ '/api/uploads': (url: URL) => (url.search.includes('game_version') ? characters : history) })
    renderWithProviders(<UploadTab />, LINKED)
    expect(screen.getAllByText(/_classic_beta_/)[0]).toBeInTheDocument() // Forever's SavedVariables folder
    const file = new File(['AltArmyTBC_Data = {}'], 'AltArmy_TBC.lua', { lastModified: 1_790_000_000_000 })
    expect(screen.getByRole('button', { name: 'AltArmy_TBC.lua for WoW: Forever' })).toBeInTheDocument()
    await userEvent.upload(fileInput(), file)
    const [altArmyButton] = screen.getAllByRole('button', { name: 'Upload' })
    await userEvent.click(altArmyButton!)
    expect(await screen.findByText(/Imported 3 characters: Classic Beta PvE \(Horde\) 1, Dreamscythe \(Horde\) 2/)).toBeInTheDocument()

    const post = fetch.mock.calls.map(([r]) => r).find((r) => r.method === 'POST')
    expect(new URL(post!.url).searchParams.get('game_version')).toBe('forever')
    const form = await post!.formData()
    expect(form.get('kind')).toBe('altarmy')
    expect(form.get('modified_at')).toBe('1790000000000')
    // jsdom's File doesn't survive Node's Request (name and content are lost); the browser check covers them
    expect(form.has('file')).toBe(true)
    await waitFor(() => expect(screen.getByText('no AUCTIONATOR_PRICE_DATABASE in file')).toBeInTheDocument())
  })

  it('shows why an upload was refused', async () => {
    const fetch = mockApi({})
    fetch.mockImplementation(async (request: Request) =>
      request.method === 'POST'
        ? new Response(JSON.stringify({ detail: 'no AltArmyTBC_Data in file' }), { status: 400 })
        : new Response('[]', { status: 200 }),
    )
    renderWithProviders(<UploadTab />, LINKED)
    await userEvent.upload(fileInput(), new File(['x'], 'AltArmy_TBC.lua'))
    await userEvent.click(screen.getAllByRole('button', { name: 'Upload' })[0]!)
    expect(await screen.findByText('no AltArmyTBC_Data in file')).toBeInTheDocument()
  })

  it('tells guests their characters wait for a linked account', () => {
    mockApi({ '/api/uploads': [] })
    renderWithProviders(<UploadTab />, GUEST)
    expect(screen.getByText(/Your characters are kept: link your account/)).toBeInTheDocument()
  })
})
