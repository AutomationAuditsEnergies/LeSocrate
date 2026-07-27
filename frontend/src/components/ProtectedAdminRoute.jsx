import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { apiFetch } from '../api'
import { hasAdminAccess } from '../adminAccess'
import AppLoader from './AppLoader.jsx'

const NO_REQUIRED_PERMISSIONS = []

export default function ProtectedAdminRoute({
  children,
  loginPath = '/connexion-centre',
  allowedAccountTypes = null,
  requiredPermissions = NO_REQUIRED_PERMISSIONS,
}) {
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
          if (isMounted) {
            setIsAuthenticated(hasAdminAccess(data.account, {
              allowedAccountTypes,
              requiredPermissions,
            }))
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
        if (error?.name === 'AbortError' || !isMounted) return
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
  }, [allowedAccountTypes, requiredPermissions])

  if (isLoading) {
    return <AppLoader label="Vérification de votre accès" />
  }

  if (!isAuthenticated) {
    return <Navigate to={loginPath} replace />
  }

  // Afficher la page protégée
  return children
}
