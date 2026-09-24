import { useMemo, type ReactNode } from 'react'
import { SegmentedControl } from '@mantine/core'
import {
  DEFAULT_GAME_VERSION,
  GAME_VERSION_KEY,
  GAME_VERSIONS,
  GameVersionContext,
  gameVersionSchema,
  useGameVersionState,
} from '../lib/gameVersion'
import { useStoredState } from '../lib/storage'

/** Remembers the chosen game version (in localStorage) for everything below it. */
export function GameVersionProvider({ children }: { children: ReactNode }) {
  const [gameVersion, setGameVersion] = useStoredState(GAME_VERSION_KEY, gameVersionSchema, DEFAULT_GAME_VERSION)
  const state = useMemo(() => [gameVersion, setGameVersion] as const, [gameVersion, setGameVersion])
  return <GameVersionContext.Provider value={state}>{children}</GameVersionContext.Provider>
}

/** Switches every tab between the games' data. */
export function GameVersionSwitch() {
  const [gameVersion, setGameVersion] = useGameVersionState()
  return (
    <SegmentedControl
      aria-label="Game version"
      data={[...GAME_VERSIONS]}
      value={gameVersion}
      onChange={(v) => setGameVersion(gameVersionSchema.parse(v))}
    />
  )
}
