import type { Auth, User } from 'firebase/auth'
import type { components } from '../api/schema'

/**
 * Firebase sign-in for hosted mode. The Firebase SDK is loaded on first use, so local mode never downloads it.
 *
 * Every visitor is signed in anonymously; linking a Google or email account keeps the uid (and with it the
 * user's data) and moves them to the linked tier.
 */
export type FirebaseConfig = components['schemas']['FirebaseOut']

let auth: Auth | null = null
let started: Promise<void> | null = null

/** Start Firebase and sign in anonymously unless a session is already stored. Safe to call twice. */
export function initAuth(config: FirebaseConfig): Promise<void> {
  started ??= (async () => {
    const [{ initializeApp }, fa] = await Promise.all([import('firebase/app'), import('firebase/auth')])
    const app = initializeApp({ apiKey: config.api_key, authDomain: config.auth_domain, projectId: config.project_id })
    const a = fa.getAuth(app)
    if (config.emulator_url) fa.connectAuthEmulator(a, config.emulator_url, { disableWarnings: true })
    await a.authStateReady()
    if (!a.currentUser) await fa.signInAnonymously(a)
    auth = a
  })()
  return started
}

/** The signed-in user's ID token for the API, or null in local mode. Firebase refreshes it when it expires. */
export async function getIdToken(): Promise<string | null> {
  return auth?.currentUser ? auth.currentUser.getIdToken() : null
}

function currentUser(): User {
  const user = auth?.currentUser
  if (!user) throw new Error('Not signed in.')
  return user
}

/** Link a Google account in a popup. The new token carries the Google sign-in, so the API sees the linked tier. */
export async function linkWithGoogle(): Promise<void> {
  const fa = await import('firebase/auth')
  const user = currentUser()
  await fa.linkWithPopup(user, new fa.GoogleAuthProvider())
  await user.getIdToken(true)
}

/** Link an email address and password (a new one: signing in to an existing account comes later). */
export async function linkWithEmail(email: string, password: string): Promise<void> {
  const fa = await import('firebase/auth')
  const user = currentUser()
  await fa.linkWithCredential(user, fa.EmailAuthProvider.credential(email, password))
  await user.getIdToken(true)
}

const LINK_ERRORS: Readonly<Record<string, string>> = {
  'auth/credential-already-in-use':
    'That account already belongs to another altarmy-profit user. Merging accounts is not supported yet.',
  'auth/email-already-in-use':
    'That email already belongs to another altarmy-profit user. Merging accounts is not supported yet.',
  'auth/popup-closed-by-user': 'The sign-in window was closed before linking finished.',
  'auth/weak-password': 'Pick a password of at least 6 characters.',
  'auth/invalid-email': 'That is not a valid email address.',
}

/** What to tell the user when linking failed. */
export function linkErrorMessage(error: unknown): string {
  const code = error && typeof error === 'object' && 'code' in error ? String(error.code) : ''
  return LINK_ERRORS[code] ?? (error instanceof Error ? error.message : 'Linking failed.')
}
