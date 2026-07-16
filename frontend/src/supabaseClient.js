import { createClient } from '@supabase/supabase-js'
import { apiUrl } from './api'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

export let isSupabaseConfigured = Boolean(supabaseUrl && supabaseAnonKey)

export let supabase = isSupabaseConfigured
  ? createClient(supabaseUrl, supabaseAnonKey)
  : null

let supabaseClientPromise = null

function configureSupabaseClient(url, anonKey) {
  if (!url || !anonKey) return null
  if (!supabase) {
    supabase = createClient(url, anonKey)
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
      return configureSupabaseClient(data.url, data.anon_key)
    })
    .catch(() => null)

  return supabaseClientPromise
}
