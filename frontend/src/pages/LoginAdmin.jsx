import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { apiFetch, apiUrl, setPlatformId, setPlatformName } from '../api'

export default function LoginAdmin() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const pParam = searchParams.get('p')

  // Si on arrive via le bouton "Admin" du HR Dashboard (ex. /login-admin?p=2),
  // fixer platform_id en localStorage pour que apiFetch injecte X-Platform-Id: 2.
  // Sans ça, sur un domaine Azure distinct, le localStorage est vide et tout
  // retombe sur le default '1' → session admin créée pour P1 au lieu de P2.
  useEffect(() => {
    if (pParam) {
      setPlatformId(pParam)
      fetch(apiUrl(`/api/platform-info?id=${pParam}`))
        .then(r => r.json())
        .then(data => { if (data.name) setPlatformName(data.name) })
        .catch(() => {})
    }
  }, [pParam])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const response = await apiFetch('/api/admin/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          username: username.trim(),
          password: password.trim(),
        }),
      })

      const data = await response.json()

      if (response.ok && data.success) {
        // Propager ?p= vers /admin pour qu'un refresh en navigation privée
        // (localStorage volatile) puisse restaurer le bon tenant.
        navigate(pParam ? `/admin?p=${pParam}` : '/admin')
      } else {
        setError(data.error || 'Identifiants incorrects')
      }
    } catch (err) {
      console.error('Erreur login admin:', err)
      setError('Erreur de connexion au serveur')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-100 flex items-center justify-center">
      <div className="bg-white rounded-lg shadow-md p-8 w-full max-w-sm">
        <h2 className="text-2xl font-semibold text-center mb-4">Connexion Administrateur</h2>

        {error && (
          <div className="bg-red-100 text-red-700 px-3 py-2 rounded mb-4">
            {error}
          </div>
        )}

        <form className="space-y-4" onSubmit={handleSubmit}>
          <div>
            <label htmlFor="username" className="block text-gray-700 mb-1">
              Utilisateur
            </label>
            <input
              type="text"
              id="username"
              name="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              placeholder="username"
              className="w-full px-3 py-2 border rounded focus:outline-none focus:ring focus:ring-blue-300"
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-gray-700 mb-1">
              Mot de passe
            </label>
            <input
              type="password"
              id="password"
              name="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              placeholder="mdp"
              className="w-full px-3 py-2 border rounded focus:outline-none focus:ring focus:ring-blue-300"
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className={`w-full py-2 rounded transition ${
              loading
                ? 'bg-blue-400 cursor-not-allowed'
                : 'bg-blue-600 hover:bg-blue-700'
            } text-white`}
          >
            {loading ? 'Connexion...' : 'Se connecter'}
          </button>
        </form>

      </div>
    </div>
  )
}
