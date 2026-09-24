import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Status } from '../api/client'
import { mockApi, renderWithProviders } from '../test/utils'
import { SearchTab } from './SearchTab'

const status = (over: Partial<Status>): Status => ({
  db_path: 'data/wowprofit.db',
  build: '1.60.1.69913',
  items: 3,
  recipes: 1,
  prices: 2,
  last_auctionator_import: null,
  ...over,
})

describe('SearchTab', () => {
  it('points to the Manage tab when there are no recipes', async () => {
    mockApi({ '/api/status': status({ recipes: 0 }), '/api/professions': [] })
    renderWithProviders(<SearchTab />)
    expect(await screen.findByText(/Download game data on the Manage tab/)).toBeInTheDocument()
  })

  it('asks for professions before ranking, and warns when there are no prices', async () => {
    const fetch = mockApi({ '/api/status': status({ prices: 0 }), '/api/professions': ['Tailoring'] })
    renderWithProviders(<SearchTab />)
    expect(await screen.findByText('Pick the professions you have.')).toBeInTheDocument()
    expect(screen.getByText(/No prices yet/)).toBeInTheDocument()
    const paths = fetch.mock.calls.map(([request]) => new URL(request.url).pathname)
    expect(paths).not.toContain('/api/rank')
  })
})
