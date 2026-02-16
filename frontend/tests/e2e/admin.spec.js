import { test, expect } from '@playwright/test'

async function loginAdmin(page) {
  await page.goto('/login-admin')
  await page.fill('#username', 'admin')
  await page.fill('#password', 'secret123')
  await page.click('button[type=submit]')
  await expect(page).toHaveURL('/admin', { timeout: 10000 })
}

test.describe('Page admin — Login', () => {
  test('affiche le formulaire de connexion admin', async ({ page }) => {
    await page.goto('/login-admin')
    await expect(page.locator('#username')).toBeVisible()
    await expect(page.locator('#password')).toBeVisible()
    await expect(page.locator('button[type=submit]')).toBeVisible()
  })

  test('mauvais identifiants affiche une erreur', async ({ page }) => {
    await page.goto('/login-admin')
    await page.fill('#username', 'mauvais')
    await page.fill('#password', 'mauvais')
    await page.click('button[type=submit]')
    await expect(page.locator('text=Identifiants incorrects')).toBeVisible({ timeout: 5000 })
    await expect(page).toHaveURL('/login-admin')
  })

  test('connexion admin réussie redirige vers /admin', async ({ page }) => {
    await loginAdmin(page)
    await expect(page.locator('text=Administration')).toBeVisible()
  })
})

test.describe('Page admin — Fonctionnalités', () => {
  test.beforeEach(async ({ page }) => {
    await loginAdmin(page)
  })

  test('bouton Export Excel déclenche un téléchargement', async ({ page }) => {
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 10000 }),
      page.click('button:has-text("Exporter en Excel")')
    ])
    expect(download.suggestedFilename()).toMatch(/\.xlsx$/)
  })

  test('formulaire config heure du cours fonctionne', async ({ page }) => {
    await page.fill('#date_cours', '2026-02-20')
    await page.fill('#heure_cours', '09:00')
    await page.click('button:has-text("Mettre à jour")')
    // Attendre le message de succès dans la div dédiée (pas le bouton)
    await expect(page.locator('.rounded-xl.border-emerald-400\\/40')).toBeVisible({ timeout: 5000 })
  })

  test('les logs de connexion s\'affichent', async ({ page }) => {
    await expect(page.locator('table')).toBeVisible()
    // Utiliser exact:true pour éviter l'ambiguïté avec "Prénom"
    await expect(page.getByRole('columnheader', { name: 'Nom', exact: true })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Prénom' })).toBeVisible()
  })

  test('lien vers la page Debug est accessible', async ({ page }) => {
    await page.click('a:has-text("Debug cours")')
    await expect(page).toHaveURL('/debug', { timeout: 10000 })
    await expect(page.locator('text=Debug')).toBeVisible()
  })
})
