export function hasAdminAccess(
  account,
  {
    allowedAccountTypes = null,
    requiredPermissions = [],
  } = {},
) {
  if (!account?.type) return false
  if (allowedAccountTypes && !allowedAccountTypes.includes(account.type)) return false
  return requiredPermissions.every(permission => account.permissions?.[permission] === true)
}
