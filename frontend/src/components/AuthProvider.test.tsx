import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Config, Me } from '../api/client'
import { initAuth } from '../lib/auth'
import { useSession } from '../lib/session'
import { mockApi, renderWithProviders } from '../test/utils'
import { AuthProvider } from './AuthProvider'

// The Firebase SDK is never loaded in tests: sign-in is a stub, and the token a fixed string.
vi.mock('../lib/auth', () => ({
  initAuth: vi.fn(async () => {}),
  getIdToken: vi.fn(async () => 'id-token'),
}))

const firebase = {
  api_key: 'key',
  auth_domain: 'demo-altarmy.firebaseapp.com',
  project_id: 'demo-altarmy',
  emulator_url: 'http://127.0.0.1:9099',
}
const hosted: Config = { mode: 'hosted', firebase }
const guest: Me = { uid: 'guest', tier: 'free', free_max_level: 30 }

function Who() {
  const s = useSession()
  return <p>{`${s.mode} ${s.uid} ${s.tier} ${s.freeMaxLevel}`}</p>
}

const renderApp = () =>
  renderWithProviders(
    <AuthProvider>
      <Who />
    </AuthProvider>,
  )

describe('AuthProvider', () => {
  afterEach(() => vi.clearAllMocks())

  it('needs no sign-in in local mode', async () => {
    mockApi({ '/api/config': { mode: 'local', firebase: null }, '/api/me': { uid: 'local', tier: 'linked', free_max_level: 30 } })
    renderApp()
    expect(await screen.findByText('local local linked 30')).toBeInTheDocument()
    expect(initAuth).not.toHaveBeenCalled()
  })

  it('signs in with Firebase in hosted mode, then asks the API who that is', async () => {
    const fetch = mockApi({ '/api/config': hosted, '/api/me': guest })
    renderApp()
    expect(await screen.findByText('hosted guest free 30')).toBeInTheDocument()
    expect(initAuth).toHaveBeenCalledWith(firebase)
    const me = fetch.mock.calls.map(([r]) => r).find((r) => new URL(r.url).pathname === '/api/me')
    expect(me?.headers.get('Authorization')).toBe('Bearer id-token')
  })

  it('explains a failed sign-in', async () => {
    mockApi({ '/api/config': { mode: 'hosted', firebase: null } })
    renderApp()
    expect(await screen.findByText(/hosted mode without a Firebase configuration/)).toBeInTheDocument()
  })
})
