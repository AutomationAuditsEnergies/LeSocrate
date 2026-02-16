// En local (dev) : VITE_API_URL n'est pas défini → les appels passent par le proxy Vite ("/api/...")
// En prod : VITE_API_URL = "https://socrate1-xxx.azurewebsites.net" → appels directs
const API_BASE = import.meta.env.VITE_API_URL || ''

export function apiUrl(path) {
  return `${API_BASE}${path}`
}

/**
 * Wrapper autour de fetch qui ajoute automatiquement credentials: 'include'
 * Indispensable pour que les cookies de session fonctionnent en cross-origin (prod)
 */
export function apiFetch(path, options = {}) {
  return fetch(apiUrl(path), {
    ...options,
    credentials: 'include',
  })
}
