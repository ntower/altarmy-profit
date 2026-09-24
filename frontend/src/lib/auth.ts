import type { Auth, User } from 'firebase/auth'
import type { components } from '../api/schema'

/**
 * Firebase sign-in for hosted mode. The Firebase SDK is loaded on first use, so local mode never downloads it.
 *
 * Every visitor is signed in anonymously. Linking an email and password keeps the uid (and with it the user's data)
 * and moves them to the linked tier; on another browser they sign in with that email. Signing out starts a new
 * anonymous session.
 */
export type FirebaseConfig = components['schemas']['FirebaseOut']

let auth: Auth | null = null
let started: Promise<void> | null = null
const listeners = new Set<() => void>()

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
    fa.onIdTokenChanged(a, () => listeners.forEach((l) => l()))
  })()
  return started
}

/** Call `listener` whenever the signed-in user or their token changes (sign-in, linking, sign-out). */
export function onUserChange(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** The signed-in user's ID token for the API, or null in local mode. Firebase refreshes it when it expires. */
export async function getIdToken(): Promise<string | null> {
  return auth?.currentUser ? auth.currentUser.getIdToken() : null
}

/** The signed-in account's email, if it has one (linked accounts). */
export function currentEmail(): string | null {
  return auth?.currentUser?.email ?? null
}

function requireAuth(): Auth {
  if (!auth) throw new Error('Sign-in has not started.')
  return auth
}

function currentUser(): User {
  const user = requireAuth().currentUser
  if (!user) throw new Error('Not signed in.')
  return user
}

/** Link an email address and password to this browser's guest account: same uid, now the linked tier. */
export async function linkWithEmail(email: string, password: string): Promise<void> {
  const fa = await import('firebase/auth')
  const user = currentUser()
  await fa.linkWithCredential(user, fa.EmailAuthProvider.credential(email, password))
  await user.getIdToken(true) // the new token says "password", which the API reads as linked
}

/** Sign in to an existing account; the guest session's data stays with the guest uid. */
export async function signInWithEmail(email: string, password: string): Promise<void> {
  const fa = await import('firebase/auth')
  await fa.signInWithEmailAndPassword(requireAuth(), email, password)
}

/** Email a link to set a new password. */
export async function resetPassword(email: string): Promise<void> {
  const fa = await import('firebase/auth')
  await fa.sendPasswordResetEmail(requireAuth(), email)
}

/** Sign out, into a fresh guest session. */
export async function signOut(): Promise<void> {
  const fa = await import('firebase/auth')
  const a = requireAuth()
  await fa.signOut(a)
  await fa.signInAnonymously(a)
}

const AUTH_ERRORS: Readonly<Record<string, string>> = {
  'auth/credential-already-in-use': 'That email already has an account: sign in instead.',
  'auth/email-already-in-use': 'That email already has an account: sign in instead.',
  'auth/invalid-credential': 'Wrong email or password.',
  'auth/wrong-password': 'Wrong email or password.',
  'auth/user-not-found': 'Wrong email or password.',
  'auth/too-many-requests': 'Too many attempts. Wait a few minutes, or reset your password.',
  'auth/weak-password': 'Pick a password of at least 6 characters.',
  'auth/invalid-email': 'That is not a valid email address.',
  'auth/missing-email': 'Enter your email address first.',
}

/** What to tell the user when signing in, linking or resetting failed. */
export function authErrorMessage(error: unknown): string {
  const code = error && typeof error === 'object' && 'code' in error ? String(error.code) : ''
  return AUTH_ERRORS[code] ?? (error instanceof Error ? error.message : 'Something went wrong.')
}
