import type { ReactElement } from 'react'
import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { vi } from 'vitest'

export function renderWithProviders(ui: ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MantineProvider env="test">
      <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
    </MantineProvider>,
  )
}

/** Stub fetch: each API path answers with its JSON body; unknown paths get a 404 with a `detail`. */
export function mockApi(routes: Record<string, unknown>) {
  const fetch = vi.fn(async (request: Request) => {
    const { pathname } = new URL(request.url)
    const found = pathname in routes
    return new Response(JSON.stringify(found ? routes[pathname] : { detail: `no mock for ${pathname}` }), {
      status: found ? 200 : 404,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}
