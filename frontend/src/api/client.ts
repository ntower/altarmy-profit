import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

export type Status = components['schemas']['Status']
export type RankResult = components['schemas']['RankResult']
/** One recipe re-costed with the user's choices, and tooltip details for the items it now uses. */
export type Evaluation = components['schemas']['EvaluateResponse']
export type ItemInfo = components['schemas']['ItemInfo']
/** One item in a recipe's reagent tree: bought (no inputs) or crafted from its inputs. */
export type FlowNode = components['schemas']['NodeOut']
/** Tooltip details keyed by item id (JSON object keys are strings). */
export type ItemMap = Readonly<Record<string, ItemInfo>>
export type Characters = components['schemas']['Characters']
export type CharacterGroup = components['schemas']['GroupOut']
export type Selection = components['schemas']['SelectionModel']
export type Sources = components['schemas']['Sources']
export type UpdateResult = components['schemas']['UpdateResult']
/** Items never sold on the AH, with tooltip details. */
export type AhBlocked = components['schemas']['AhBlocked']

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
