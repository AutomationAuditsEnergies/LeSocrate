import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { apiUrl } from '../api'

export default function ProtectedAdminRoute({ children, loginPath = '/login-admin' }) {
  const [isAuthenticated, setIsAuthenticated] = useState(null) // null = loading, true/false = résultat
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    // Vérifier si l'utilisateur est authentifié comme admin
    const checkAuth = async () => {
      try {
        const response = await fetch(apiUrl('/api/admin/logs'), {
          method: 'GET',
          credentials: 'include', // Important pour envoyer les cookies de session
        })

        if (response.ok) {
          // Si on peut accéder aux logs, c'est qu'on est admin
          setIsAuthenticated(true)
        } else if (response.status === 403 || response.status === 401) {
          // Non authentifié
          setIsAuthenticated(false)
        } else {
          // Autre erreur
          setIsAuthenticated(false)
        }
      } catch (error) {
        console.error('Erreur vérification auth admin:', error)
        setIsAuthenticated(false)
      } finally {
        setIsLoading(false)
      }
    }

    checkAuth()
  }, [])

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
