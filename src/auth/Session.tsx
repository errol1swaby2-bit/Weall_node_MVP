export type SessionStatus = 'unknown' | 'authenticated' | 'unauthenticated'
export interface Session {
  status: SessionStatus
  email?: string
  walletAddress?: string
}
