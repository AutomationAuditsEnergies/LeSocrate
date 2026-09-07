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
