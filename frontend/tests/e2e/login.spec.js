import { test, expect } from '@playwright/test'

test.describe('Page d\'accueil — Login utilisateur', () => {
  test('affiche le formulaire de connexion', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('#email')).toBeVisible()
    await expect(page.locator('#password')).toBeVisible()
    await expect(page.locator('button[type=submit]')).toBeVisible()
  })

  test('connexion réussie redirige vers /video ou /attente', async ({ page }) => {
    await page.goto('/')
    await page.locator('summary').click()
    await page.fill('#nom', 'Test')
    await page.fill('#prenom', 'Playwright')
    await page.click('button[type=submit]')
    await expect(page).toHaveURL(/\/(video|attente)/, { timeout: 10000 })
  })

  test('champs vides bloquent la soumission', async ({ page }) => {
    await page.goto('/')
    // Les champs sont required — le navigateur bloque nativement
    await page.click('button[type=submit]')
    await expect(page).toHaveURL('/')
  })
})
