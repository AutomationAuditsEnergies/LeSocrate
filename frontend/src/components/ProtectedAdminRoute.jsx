import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { apiFetch } from '../api'

export default function ProtectedAdminRoute({ children, loginPath = '/connexion-centre', allowedAccountTypes = null }) {
  const [isAuthenticated, setIsAuthenticated] = useState(null) // null = loading, true/false = résultat
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let isMounted = true
    const controller = new AbortController()
    const timeoutId = window.setTimeout(() => {
      controller.abort()
    }, 12000)

    // Vérifier si l'utilisateur est authentifié comme admin
    const checkAuth = async () => {
      try {
        const response = await apiFetch('/api/admin/session', {
          method: 'GET',
          signal: controller.signal,
        })

        if (response.ok) {
          const data = await response.json().catch(() => ({}))
          const accountType = data.account?.type
          if (isMounted) {
            setIsAuthenticated(!allowedAccountTypes || allowedAccountTypes.includes(accountType))
          }
        } else if (response.status === 403 || response.status === 401) {
          // Non authentifié
          if (isMounted) {
            setIsAuthenticated(false)
          }
        } else {
          // Autre erreur
          if (isMounted) {
            setIsAuthenticated(false)
          }
        }
      } catch (error) {
        console.error('Erreur vérification auth admin:', error)
        if (isMounted) {
          setIsAuthenticated(false)
        }
      } finally {
        window.clearTimeout(timeoutId)
        if (isMounted) {
          setIsLoading(false)
        }
      }
    }

    checkAuth()

    return () => {
      isMounted = false
      window.clearTimeout(timeoutId)
      controller.abort()
    }
  }, [allowedAccountTypes])

  if (isLoading) {
    // Afficher un loader pendant la vérification
    return (
      <div className="min-h-screen bg-gray-100 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Vérification...</p>
        </div>
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to={loginPath} replace />
  }

  // Afficher la page protégée
  return children
}
