import { test, expect } from '@playwright/test'

async function loginCenter(page) {
  await page.goto('/connexion-centre')
  await page.fill('#centre-username', 'admin')
  await page.fill('#centre-password', 'secret123')
  await page.click('button[type=submit]')
  await expect(page).toHaveURL('/dashboard-centre', { timeout: 10000 })
}

test.describe('Connexion centre', () => {
  test('affiche le formulaire de connexion unique', async ({ page }) => {
    await page.goto('/connexion-centre')
    await expect(page.locator('#centre-username')).toBeVisible()
    await expect(page.locator('#centre-password')).toBeVisible()
    await expect(page.locator('button[type=submit]')).toBeVisible()
  })

  test('mauvais identifiants affiche une erreur', async ({ page }) => {
    await page.goto('/connexion-centre')
    await page.fill('#centre-username', 'mauvais')
    await page.fill('#centre-password', 'mauvais')
    await page.click('button[type=submit]')
    await expect(page.locator('text=Identifiants incorrects')).toBeVisible({ timeout: 5000 })
    await expect(page).toHaveURL('/connexion-centre')
  })

  test('connexion réussie redirige vers le tableau de bord', async ({ page }) => {
    await loginCenter(page)
    await expect(page).toHaveURL('/dashboard-centre')
  })
})
