// En local (dev) : VITE_API_URL n'est pas défini → les appels passent par le proxy Vite ("/api/...")
// En prod : VITE_API_URL = "https://socrate1-xxx.azurewebsites.net" → appels directs
const API_BASE = import.meta.env.VITE_API_URL || ''

export function apiUrl(path) {
  return `${API_BASE}${path}`
}

/**
 * Wrapper autour de fetch qui ajoute automatiquement credentials: 'include'
 * et le token X-Auth-Token pour les navigateurs bloquant les cookies tiers (navigation privée)
 */
export function apiFetch(path, options = {}) {
  const token = localStorage.getItem('auth_token')
  const headers = {
    ...(options.headers || {}),
    ...(token ? { 'X-Auth-Token': token } : {}),
  }
  return fetch(apiUrl(path), {
    ...options,
    headers,
    credentials: 'include',
  })
}
