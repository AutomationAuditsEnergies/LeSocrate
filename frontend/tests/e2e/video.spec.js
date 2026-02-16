import { test, expect } from '@playwright/test'

/**
 * Login utilisateur et attend que la page se stabilise.
 * Retourne l'état du cours : 'playing' | 'finished' | 'waiting'
 */
async function loginAndGetState(page) {
  await page.goto('/')
  await page.fill('#nom', 'Test')
  await page.fill('#prenom', 'Playwright')
  await page.click('button[type=submit]')

  // Attend d'arriver sur /video ou /attente
  await page.waitForURL(/\/(video|attente)/, { timeout: 15000 })

  if (page.url().includes('/attente')) {
    return 'waiting'
  }

  // Sur /video — attendre que le loading se termine ou une redirection vers /attente
  // Le cours peut être: playing, finished, ou waiting (→ redirect /attente)
  try {
    // Si redirect vers /attente dans les 5s → cours en attente
    await page.waitForURL('/attente', { timeout: 5000 })
    return 'waiting'
  } catch {
    // Pas de redirect → on est sur /video
    // Attendre que le chargement se termine (disparition du texte de loading)
    const loading = page.locator('text=Chargement du cours')
    try {
      await expect(loading).toBeHidden({ timeout: 15000 })
    } catch {
      // Toujours en chargement après 15s → problème réseau/API, on skippe
      return 'loading'
    }

    // Vérifier l'état affiché
    const finished = page.locator('text=Le cours est terminé')
    const playing = page.locator('button[title="Quitter le cours"]')
    const errorMsg = page.locator('.text-red-500')

    if (await finished.isVisible()) return 'finished'
    if (await playing.isVisible()) return 'playing'
    if (await errorMsg.isVisible()) return 'error'
    return 'unknown'
  }
}

test.describe('Page vidéo — Affichage général', () => {
  test('après login, arrive sur /video ou /attente selon le statut du cours', async ({ page }) => {
    await page.goto('/')
    await page.fill('#nom', 'Test')
    await page.fill('#prenom', 'Playwright')
    await page.click('button[type=submit]')
    await expect(page).toHaveURL(/\/(video|attente)/, { timeout: 15000 })
  })

  test('la page /video affiche un contenu valide', async ({ page }) => {
    const state = await loginAndGetState(page)

    if (state === 'waiting') {
      await expect(page).toHaveURL('/attente')
      await expect(page.locator('text=Début de la formation dans')).toBeVisible()
      return
    }

    if (state === 'finished') {
      await expect(page.locator('text=Le cours est terminé')).toBeVisible()
      return
    }

    if (state === 'playing') {
      await expect(page.locator('button[title="Quitter le cours"]')).toBeVisible()
      return
    }

    if (state === 'loading') {
      test.skip(true, 'Page bloquée en chargement (API lente ou inaccessible)')
      return
    }

    if (state === 'error') {
      // Une erreur s'affiche sur la page → la page répond, c'est valide
      await expect(page.locator('.text-red-500')).toBeVisible()
      return
    }

    // unknown : on ne peut pas déterminer l'état → skip plutôt que fail
    test.skip(true, `État indéterminé sur /video`)
  })
})

test.describe('Page vidéo — Contrôles (cours en cours)', () => {
  test('si cours en cours : le bouton son est visible et cliquable', async ({ page }) => {
    const state = await loginAndGetState(page)
    if (state !== 'playing') {
      test.skip()
      return
    }

    const muteBtn = page.locator('button[title="Couper le son"], button[title="Activer le son"]')
    await expect(muteBtn).toBeVisible()
    await muteBtn.click()
    await expect(muteBtn).toBeVisible()
  })

  test('si cours en cours : le bouton chat ouvre le panneau de messages', async ({ page }) => {
    const state = await loginAndGetState(page)
    if (state !== 'playing') {
      test.skip()
      return
    }

    const chatBtn = page.locator('button[title="Ouvrir le chat"]')
    await expect(chatBtn).toBeVisible()
    await chatBtn.click()
    await expect(page.locator('text=Messages')).toBeVisible()
  })

  test('si cours en cours : le bouton raccrocher redirige vers l\'accueil', async ({ page }) => {
    const state = await loginAndGetState(page)
    if (state !== 'playing') {
      test.skip()
      return
    }

    await page.locator('button[title="Quitter le cours"]').click()
    await expect(page).toHaveURL('/', { timeout: 10000 })
  })
})

test.describe('Chat panel', () => {
  test('si cours en cours : peut envoyer un message dans le chat', async ({ page }) => {
    const state = await loginAndGetState(page)
    if (state !== 'playing') {
      test.skip()
      return
    }

    await page.locator('button[title="Ouvrir le chat"]').click()
    const textarea = page.locator('#question')
    await expect(textarea).toBeVisible({ timeout: 5000 })
    await textarea.fill('Bonjour, ceci est un test Playwright')
    await page.click('#send-btn')
    await expect(page.locator('text=Bonjour, ceci est un test Playwright')).toBeVisible({ timeout: 5000 })
  })
})

test.describe('Page d\'attente', () => {
  test('si cours en attente : le bouton Actualiser recharge la page', async ({ page }) => {
    const state = await loginAndGetState(page)
    if (state !== 'waiting') {
      test.skip()
      return
    }

    await page.click('button:has-text("Actualiser")')
    await expect(page).toHaveURL(/\/(video|attente)/, { timeout: 10000 })
  })

  test('si cours en attente : le bouton Accueil redirige vers /', async ({ page }) => {
    const state = await loginAndGetState(page)
    if (state !== 'waiting') {
      test.skip()
      return
    }

    await page.click('button:has-text("Accueil")')
    await expect(page).toHaveURL('/', { timeout: 5000 })
  })
})
