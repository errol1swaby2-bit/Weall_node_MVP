import React from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export default function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { session } = useAuth()
  const loc = useLocation()

  if (session.status === 'unknown') return null // or a spinner
  if (session.status === 'unauthenticated') {
    return <Navigate to="/login" replace state={{ from: loc }} />
  }
  return <>{children}</>
}
