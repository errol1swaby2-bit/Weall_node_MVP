import React, { createContext, useContext, useEffect, useState } from 'react'
import { Session } from './Session'
import { api } from '../lib/api'

interface AuthCtx {
  session: Session
  refresh: () => Promise<void>
  logout: () => Promise<void>
}

const Ctx = createContext<AuthCtx | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session>({ status: 'unknown' })

  const refresh = async () => {
    try {
      const res = await api.get('/auth/session')
      setSession({ status: 'authenticated', ...res })
    } catch {
      setSession({ status: 'unauthenticated' })
    }
  }

  const logout = async () => {
    try { await api.post('/auth/logout', {}) } catch {}
    setSession({ status: 'unauthenticated' })
  }

  useEffect(() => { refresh() }, [])

  return <Ctx.Provider value={{ session, refresh, logout }}>{children}</Ctx.Provider>
}

export const useAuth = () => {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
