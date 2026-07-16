export const CENTER_ONBOARDING_VERSION = 1

export function shouldShowCenterOnboarding(state, currentVersion = CENTER_ONBOARDING_VERSION) {
  if (!state || state.success === false) return false
  return Number(state.onboarding_version || 0) < Number(currentVersion)
}

export function getActiveTeachers(platforms = []) {
  return platforms.filter((platform) => (
    !['completed', 'archived'].includes(String(platform?.lifecycle_status || 'active').toLowerCase())
  ))
}

export function getReusableTeacherDefaults(module = {}) {
  return {
    teacherName: String(module.teacher_name || '').trim(),
    teacherColor: String(module.teacher_color || 'violet').trim() || 'violet',
  }
}
