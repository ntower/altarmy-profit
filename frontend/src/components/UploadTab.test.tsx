import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
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
    // Node's FormData (which Request needs) refuses jsdom's File on newer Node versions, so record what the
    // app appends and pass Node a placeholder.
    const appended = new Map<string, unknown>()
    vi.stubGlobal(
      'FormData',
      class extends FormData {
        override append(name: string, value: string | Blob, fileName?: string): void {
          appended.set(name, value)
          super.append(name, typeof value === 'string' ? value : `file ${fileName}`)
        }
      },
    )
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
    expect(appended.get('kind')).toBe('altarmy')
    expect(appended.get('modified_at')).toBe('1790000000000')
    expect(appended.get('file')).toBe(file)
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

  it('says which realms of a scan were not used', async () => {
    const scan: UploadResult = {
      kind: 'auctionator',
      detail: '',
      characters: 0,
      groups: [],
      realms: [
        { key: 'ClassicBetaPvE', auction_house_id: 1, realm: 'Classic Beta PvE', faction: '', items: 30, moved: 0, quarantined: true },
        { key: 'Dreamscythe Horde', auction_house_id: 2, realm: 'Dreamscythe', faction: 'Horde', items: 5, moved: 2, quarantined: false },
      ],
    }
    mockApi({ '/api/uploads': (url: URL) => (url.search.includes('game_version') ? scan : []) })
    renderWithProviders(<UploadTab />, LINKED)
    const inputs = document.querySelectorAll<HTMLInputElement>('input[type="file"]')
    await userEvent.upload(inputs[1]!, new File(['x'], 'Auctionator.lua'))
    await userEvent.click(screen.getAllByRole('button', { name: 'Upload' })[1]!)
    expect(await screen.findByText(/some prices were not used/)).toBeInTheDocument()
    expect(screen.getByText('not used')).toBeInTheDocument()
    expect(screen.getByText(/Classic Beta PvE: 30 prices$/)).toBeInTheDocument()
    expect(screen.getByText(/Dreamscythe \(Horde\): 5 prices, 2 changed/)).toBeInTheDocument()
  })

  it('lists the stalest auction houses first', async () => {
    const row = { faction: '', prices: 10, last_scan_items: 10, scans_7d: 1, uploaders_7d: 1 }
    mockApi({
      '/api/uploads': [],
      '/api/coverage': [
        { ...row, auction_house_id: 1, realm: 'Fresh', last_scan: '2099-01-01 00:00:00' },
        { ...row, auction_house_id: 2, realm: 'Never', last_scan: null, scans_7d: 0, uploaders_7d: 0 },
        { ...row, auction_house_id: 3, realm: 'Old', faction: 'Horde', last_scan: '2020-01-01 00:00:00' },
      ],
    })
    renderWithProviders(<UploadTab />, GUEST)
    const table = await screen.findByRole('table', { name: 'Coverage' })
    const realms = Array.from(table.querySelectorAll('tbody tr')).map((tr) => tr.querySelector('td')?.textContent)
    expect(realms).toEqual(['Never', 'Old (Horde)', 'Fresh'])
    expect(table).toHaveTextContent('never')
  })

  it('tells guests their characters wait for a linked account', () => {
    mockApi({ '/api/uploads': [] })
    renderWithProviders(<UploadTab />, GUEST)
    expect(screen.getByText(/Your characters are kept: link your account/)).toBeInTheDocument()
  })
})
