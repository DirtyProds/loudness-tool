// @ts-check
const { test, expect } = require('@playwright/test');

const BASE_URL = 'http://localhost:8765';

test.describe('LoudnessNorm webapp', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto(BASE_URL);
  });

  // ── Test 1: La página carga y se ven todos los elementos ──────────────────
  test('carga la página y muestra todos los elementos esperados', async ({ page }) => {
    // Header
    await expect(page.locator('h1')).toHaveText('LoudnessNorm');

    // Zona de drag & drop
    await expect(page.locator('#dropzone')).toBeVisible();
    await expect(page.locator('#dzTitle')).toHaveText('Arrastra un archivo WAV aquí');

    // Presets de programa
    const presetNames = ['Spotify', 'Apple Music', 'Netflix', 'EBU R128', 'CALM Act'];
    for (const name of presetNames) {
      await expect(
        page.locator('#presets .preset').filter({ hasText: name })
      ).toBeVisible();
    }

    // Campos LUFS y True Peak
    await expect(page.locator('#lufsInput')).toBeVisible();
    await expect(page.locator('#tpInput')).toBeVisible();

    // Desplegable de modo
    await expect(page.locator('#modeSelect')).toBeVisible();

    // Botón Render
    await expect(page.locator('#renderBtn')).toBeVisible();
  });

  // ── Test 2: Cada preset actualiza los campos LUFS y True Peak ─────────────
  test('preset Spotify establece -14 LUFS / -1 dBTP', async ({ page }) => {
    await page.locator('#presets .preset').filter({ hasText: 'Spotify' }).click();
    await expect(page.locator('#lufsInput')).toHaveValue('-14');
    await expect(page.locator('#tpInput')).toHaveValue('-1');
  });

  test('preset Apple Music establece -16 LUFS / -1 dBTP', async ({ page }) => {
    await page.locator('#presets .preset').filter({ hasText: 'Apple Music' }).click();
    await expect(page.locator('#lufsInput')).toHaveValue('-16');
    await expect(page.locator('#tpInput')).toHaveValue('-1');
  });

  test('preset Netflix establece -27 LUFS / -2 dBTP', async ({ page }) => {
    await page.locator('#presets .preset').filter({ hasText: 'Netflix' }).first().click();
    await expect(page.locator('#lufsInput')).toHaveValue('-27');
    await expect(page.locator('#tpInput')).toHaveValue('-2');
  });

  test('preset EBU R128 establece -23 LUFS / -1 dBTP', async ({ page }) => {
    await page.locator('#presets .preset').filter({ hasText: 'EBU R128' }).first().click();
    await expect(page.locator('#lufsInput')).toHaveValue('-23');
    await expect(page.locator('#tpInput')).toHaveValue('-1');
  });

  test('preset CALM Act establece -24 LUFS / -2 dBTP', async ({ page }) => {
    await page.locator('#presets .preset').filter({ hasText: 'CALM Act' }).click();
    await expect(page.locator('#lufsInput')).toHaveValue('-24');
    await expect(page.locator('#tpInput')).toHaveValue('-2');
  });

  // ── Test 3: El desplegable de modo tiene las opciones correctas ───────────
  test('el desplegable de modo tiene las opciones Interleaved y Multi-mono', async ({ page }) => {
    const select = page.locator('#modeSelect');
    await expect(select).toBeVisible();

    const options = await select.locator('option').allTextContents();
    expect(options).toContain('Interleaved');
    expect(options).toContain('Multi-mono');
    expect(options).toHaveLength(2);
  });

  // ── Test 4: El botón Render está deshabilitado al inicio ──────────────────
  test('el botón Render está deshabilitado antes de cargar un archivo', async ({ page }) => {
    await expect(page.locator('#renderBtn')).toBeDisabled();
  });

});
