import { apiFetch } from './api.js'
import { normalizeScheduleTemplate, serializeScheduleTemplate } from './dayScheduleTemplates.js'

const TEMPLATE_ENDPOINT = '/api/hr/day-schedule-templates'

async function readJson(response) {
  const payload = await response.json().catch(() => ({}))
  if (!response.ok || payload?.success === false) {
    const error = new Error(
      payload?.error
      || payload?.message
      || `Le service a répondu avec le statut ${response.status}.`,
    )
    error.status = response.status
    error.payload = payload
    throw error
  }
  return payload
}

function unwrapTemplate(payload) {
  return payload?.template || payload?.data?.template || payload?.data || payload
}

export async function listDayScheduleTemplates() {
  const response = await apiFetch(TEMPLATE_ENDPOINT)
  const payload = await readJson(response)
  const templates = Array.isArray(payload)
    ? payload
    : (payload?.templates || payload?.data?.templates || payload?.data || [])
  return Array.isArray(templates) ? templates.map(normalizeScheduleTemplate) : []
}

export async function createDayScheduleTemplate(template) {
  const response = await apiFetch(TEMPLATE_ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(serializeScheduleTemplate(template)),
  })
  return normalizeScheduleTemplate(unwrapTemplate(await readJson(response)))
}

export async function updateDayScheduleTemplate(template) {
  if (!template?.id) throw new Error('Ce template ne possède pas d’identifiant.')
  const response = await apiFetch(`${TEMPLATE_ENDPOINT}/${encodeURIComponent(template.id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(serializeScheduleTemplate(template)),
  })
  return normalizeScheduleTemplate(unwrapTemplate(await readJson(response)))
}

export async function deleteDayScheduleTemplate(templateId) {
  if (!templateId) throw new Error('Ce template ne possède pas d’identifiant.')
  const response = await apiFetch(`${TEMPLATE_ENDPOINT}/${encodeURIComponent(templateId)}`, {
    method: 'DELETE',
  })
  await readJson(response)
}
