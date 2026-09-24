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

/**
 * Stub fetch: each API path answers with its JSON body (or `body(url)` for a function); unknown paths get
 * a 404 with a `detail`.
 */
export function mockApi(routes: Record<string, unknown>) {
  const fetch = vi.fn(async (request: Request) => {
    const url = new URL(request.url)
    const found = url.pathname in routes
    const route = routes[url.pathname]
    const body = typeof route === 'function' ? (route as (url: URL) => unknown)(url) : route
    return new Response(JSON.stringify(found ? body : { detail: `no mock for ${url.pathname}` }), {
      status: found ? 200 : 404,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

/** An element's text with the non-breaking spaces that pad money amounts shown as `_`, e.g. `_5 _0` for 5s 0c. */
export const shown = (el: Element | null) => el?.textContent?.replaceAll('\u00a0', '_')
