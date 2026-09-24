import { createContext, useContext } from 'react'
import { z } from 'zod'
import type { GameVersion } from '../api/client'

/** The games the app serves, in switcher order. Keys match the API's `game_version`. */
export const GAME_VERSIONS: readonly { value: GameVersion; label: string }[] = [
  { value: 'forever', label: 'WoW: Forever' },
  { value: 'tbc', label: 'TBC Anniversary' },
]
export const gameVersionSchema = z.enum(['forever', 'tbc'])
export const GAME_VERSION_KEY = 'altarmy-profit.gameVersion'
export const DEFAULT_GAME_VERSION: GameVersion = 'forever'

/** The chosen game version and its setter; outside a provider (as in most tests) it is Forever. */
export const GameVersionContext = createContext<readonly [GameVersion, (v: GameVersion) => void]>([
  DEFAULT_GAME_VERSION,
  () => {},
])

/** Which game's data every API call asks for. */
export const useGameVersion = () => useContext(GameVersionContext)[0]
export const useGameVersionState = () => useContext(GameVersionContext)
