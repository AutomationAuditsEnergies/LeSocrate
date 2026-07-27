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

export function getStudentLoginPath() {
  return localStorage.getItem('student_login_path') || '/'
}

export function setStudentLoginPath(path) {
  localStorage.setItem('student_login_path', path || '/')
}

export function apiRequestHeaders(path = '', headers = {}) {
  const adminToken = localStorage.getItem('admin_auth_token')
  const userToken = localStorage.getItem('auth_token')
  const prefersAdminToken = path.startsWith('/api/admin')
    || path.startsWith('/api/hr')
    || path.startsWith('/api/formation')
    || path.startsWith('/api/slides')
  const token = prefersAdminToken ? (adminToken || userToken) : (userToken || adminToken)
  const platformId = getPlatformId()
  return {
    ...headers,
    ...(token ? { 'X-Auth-Token': token } : {}),
    'X-Platform-Id': platformId,
  }
}

/**
 * Wrapper autour de fetch qui ajoute automatiquement credentials: 'include',
 * le token X-Auth-Token et le header X-Platform-Id
 */
export async function apiFetch(path, options = {}) {
  const {
    timeoutMs = 0,
    signal: callerSignal,
    ...fetchOptions
  } = options
  const controller = timeoutMs > 0 ? new AbortController() : null
  const abortFromCaller = () => controller?.abort(callerSignal?.reason)

  if (controller && callerSignal) {
    if (callerSignal.aborted) abortFromCaller()
    else callerSignal.addEventListener('abort', abortFromCaller, { once: true })
  }

  const timeoutId = controller
    ? window.setTimeout(
        () => controller.abort(new DOMException('Délai de réponse dépassé', 'TimeoutError')),
        timeoutMs,
      )
    : null

  try {
    return await fetch(apiUrl(path), {
      ...fetchOptions,
      headers: apiRequestHeaders(path, fetchOptions.headers || {}),
      credentials: 'include',
      ...(controller ? { signal: controller.signal } : (callerSignal ? { signal: callerSignal } : {})),
    })
  } finally {
    if (timeoutId !== null) window.clearTimeout(timeoutId)
    callerSignal?.removeEventListener?.('abort', abortFromCaller)
  }
}

function downloadFilename(response, fallbackFilename) {
  const disposition = response.headers.get('Content-Disposition') || ''
  const encodedMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (encodedMatch) {
    try {
      return decodeURIComponent(encodedMatch[1])
    } catch {
      return encodedMatch[1]
    }
  }
  const plainMatch = disposition.match(/filename="?([^";]+)"?/i)
  return plainMatch?.[1] || fallbackFilename
}

export async function apiDownload(path, fallbackFilename = 'telechargement') {
  const response = await apiFetch(path)
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(payload.error || `Téléchargement impossible (${response.status})`)
  }

  const objectUrl = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = downloadFilename(response, fallbackFilename)
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
}
