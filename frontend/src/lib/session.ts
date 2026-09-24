import { createContext, useContext } from 'react'
import type { components } from '../api/schema'

/** local: one user, no sign-in, the addon files sync; hosted: Firebase sign-in, per-user data. */
export type Mode = components['schemas']['ConfigOut']['mode']
/** free (anonymous): prices up to `freeMaxLevel` only; linked: everything. */
export type Tier = components['schemas']['Me']['tier']

export type Session = { mode: Mode; uid: string; tier: Tier; freeMaxLevel: number }

/** Local mode's one user. Also what components see outside an AuthProvider, as in most tests. */
export const LOCAL_SESSION: Session = { mode: 'local', uid: 'local', tier: 'linked', freeMaxLevel: 30 }

export const SessionContext = createContext<Session>(LOCAL_SESSION)

/** Who is signed in, and what the app may show them. */
export const useSession = () => useContext(SessionContext)
