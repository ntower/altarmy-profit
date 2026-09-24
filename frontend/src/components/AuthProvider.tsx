import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import { Alert, Center, Loader } from '@mantine/core'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useConfig, useMe } from '../api/queries'
import { initAuth, onUserChange } from '../lib/auth'
import { SessionContext, type Session } from '../lib/session'

const AUTH_KEYS = new Set(['config', 'sign-in', 'me'])

/**
 * Signs the visitor in before rendering the app: nothing to do in local mode, an anonymous Firebase
 * sign-in (or the stored session) in hosted mode. Then provides who they are (`useSession`).
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const config = useConfig()
  const firebase = config.data?.firebase
  const hosted = config.data?.mode === 'hosted'
  const signIn = useQuery({
    queryKey: ['sign-in'],
    queryFn: async () => {
      if (!firebase) throw new Error('The server runs in hosted mode without a Firebase configuration.')
      await initAuth(firebase)
      return true
    },
    enabled: hosted,
    staleTime: Infinity,
  })
  const me = useMe(config.data !== undefined && (!hosted || signIn.data === true))
  const queryClient = useQueryClient()
  // Signing in, linking or signing out changes the token: ask the API who that is now.
  useEffect(() => onUserChange(() => void queryClient.invalidateQueries({ queryKey: ['me'] })), [queryClient])
  const session = useMemo<Session | undefined>(
    () =>
      config.data && me.data
        ? { mode: config.data.mode, uid: me.data.uid, tier: me.data.tier, freeMaxLevel: me.data.free_max_level }
        : undefined,
    [config.data, me.data],
  )
  useRefetchOnUserChange(session)

  const error = config.error ?? signIn.error ?? me.error
  if (error) {
    return (
      <Alert color="red" title="Could not sign in" m="md">
        {error.message}
      </Alert>
    )
  }
  if (!session) {
    return (
      <Center h="50vh">
        <Loader aria-label="Signing in" />
      </Center>
    )
  }
  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>
}

/** A different user or tier (after linking) sees different data: refetch everything but the sign-in itself. */
function useRefetchOnUserChange(session: Session | undefined) {
  const queryClient = useQueryClient()
  const who = session && `${session.uid}:${session.tier}`
  const last = useRef(who)
  useEffect(() => {
    if (last.current !== undefined && who !== last.current) {
      void queryClient.invalidateQueries({ predicate: (q) => !AUTH_KEYS.has(String(q.queryKey[0])) })
    }
    last.current = who
  }, [who, queryClient])
}
