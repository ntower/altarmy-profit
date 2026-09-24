import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

export type Status = components['schemas']['Status']
export type RankResult = components['schemas']['RankResult']
export type ImportRequest = components['schemas']['ImportRequest']

export const client = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? '',
  // Look fetch up per call (not once at import) so tests can stub it.
  fetch: (request) => globalThis.fetch(request),
})

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

function errorMessage(error: unknown, response: Response): string {
  if (error && typeof error === 'object' && 'detail' in error) {
    const { detail } = error
    return typeof detail === 'string' ? detail : JSON.stringify(detail)
  }
  return `${response.status} ${response.statusText}`
}

/** Resolve an openapi-fetch call to its data, or throw an ApiError carrying FastAPI's `detail`. */
export async function call<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await request
  if (!response.ok || data === undefined) {
    throw new ApiError(errorMessage(error, response), response.status)
  }
  return data
}
