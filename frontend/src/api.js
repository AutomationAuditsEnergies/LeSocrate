// En local (dev) : VITE_API_URL n'est pas défini → les appels passent par le proxy Vite ("/api/...")
// En prod : VITE_API_URL = "https://socrate1-xxx.azurewebsites.net" → appels directs
const API_BASE = import.meta.env.VITE_API_URL || ''

export function apiUrl(path) {
  return `${API_BASE}${path}`
}

export function getPlatformId() {
  return localStorage.getItem('platform_id') || '1'
}

export function setPlatformId(id) {
  localStorage.setItem('platform_id', String(id))
}

export function getPlatformName() {
  return localStorage.getItem('platform_name') || import.meta.env.VITE_FORMATION_NAME || 'Formation'
}

export function setPlatformName(name) {
  localStorage.setItem('platform_name', name)
}

/**
 * Wrapper autour de fetch qui ajoute automatiquement credentials: 'include',
 * le token X-Auth-Token et le header X-Platform-Id
 */
export function apiFetch(path, options = {}) {
  const token = localStorage.getItem('auth_token')
  const platformId = getPlatformId()
  const headers = {
    ...(options.headers || {}),
    ...(token ? { 'X-Auth-Token': token } : {}),
    'X-Platform-Id': platformId,
  }
  return fetch(apiUrl(path), {
    ...options,
    headers,
    credentials: 'include',
  })
}
