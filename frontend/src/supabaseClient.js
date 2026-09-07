import { createClient } from '@supabase/supabase-js'
import { apiUrl } from './runtimeConfig'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabasePublishableKey = (
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY
  || import.meta.env.VITE_SUPABASE_ANON_KEY
)

const SUPABASE_AUTH_OPTIONS = {
  auth: {
    autoRefreshToken: true,
    detectSessionInUrl: true,
    persistSession: true,
  },
}

export let isSupabaseConfigured = Boolean(supabaseUrl && supabasePublishableKey)

export let supabase = isSupabaseConfigured
  ? createClient(supabaseUrl, supabasePublishableKey, SUPABASE_AUTH_OPTIONS)
  : null

let supabaseClientPromise = null

function configureSupabaseClient(url, publishableKey) {
  if (!url || !publishableKey) return null
  if (!supabase) {
    supabase = createClient(url, publishableKey, SUPABASE_AUTH_OPTIONS)
  }
  isSupabaseConfigured = true
  return supabase
}

export async function getSupabaseClient() {
  if (supabase) return supabase
  if (supabaseClientPromise) return supabaseClientPromise

  supabaseClientPromise = fetch(apiUrl('/api/auth/supabase-config'), {
    credentials: 'include',
  })
    .then(async (response) => {
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.success) return null
      return configureSupabaseClient(data.url, data.publishable_key || data.anon_key)
    })
    .catch(() => null)

  return supabaseClientPromise
}

export async function getSupabaseAccessToken() {
  const client = await getSupabaseClient()
  if (!client) return null
  const { data, error } = await client.auth.getSession()
  if (error) return null
  return data.session?.access_token || null
}

export async function clearSupabaseSession() {
  const client = await getSupabaseClient()
  if (!client) return
  await client.auth.signOut({ scope: 'local' })
}
