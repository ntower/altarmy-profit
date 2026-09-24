import { useLocalStorage } from '@mantine/hooks'
import type { z } from 'zod'

/** Parse a stored JSON string with `schema`; anything missing, unparsable or invalid gives `fallback`. */
export function parseStored<T>(schema: z.ZodType<T>, raw: string | undefined, fallback: T): T {
  if (raw === undefined) return fallback
  try {
    const parsed = schema.safeParse(JSON.parse(raw))
    return parsed.success ? parsed.data : fallback
  } catch {
    return fallback
  }
}

/**
 * `useState` that persists to localStorage under `key`, validated by `schema` on read.
 * `defaultValue` must be referentially stable (a module constant or primitive).
 */
export function useStoredState<T>(key: string, schema: z.ZodType<T>, defaultValue: T) {
  return useLocalStorage<T>({
    key,
    defaultValue,
    getInitialValueInEffect: false,
    deserialize: (raw) => parseStored(schema, raw, defaultValue),
  })
}
