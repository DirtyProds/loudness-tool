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

test.describe('Dynamic Control (broadcast 5.1)', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto(BASE_URL);
    await page.locator('#tabDynamic').click();
  });

  // ── Test 5: La pestaña se muestra y oculta la de Normalize ────────────────
  test('la pestaña Dynamic Control muestra su panel y oculta el de Normalize', async ({ page }) => {
    await expect(page.locator('#panel-dynamic')).toBeVisible();
    await expect(page.locator('#panel-norm')).toBeHidden();
    await expect(page.locator('#dcDropzone')).toBeVisible();
    await expect(page.locator('#dcTitle')).toHaveText('Arrastra un archivo WAV 5.1 aquí');
  });

  // ── Test 6: Preset por defecto ITU-R BS.1770-3 ────────────────────────────
  test('preset por defecto ITU-R BS.1770-3 establece -24 / -2 / 12', async ({ page }) => {
    await expect(
      page.locator('#dcPresets .preset.active').filter({ hasText: 'ITU-R BS.1770-3' })
    ).toBeVisible();
    await expect(page.locator('#dcLufsInput')).toHaveValue('-24');
    await expect(page.locator('#dcTpInput')).toHaveValue('-2');
    await expect(page.locator('#dcLraInput')).toHaveValue('12');
  });

  // ── Test 7: Preset EBU R128 broadcast ─────────────────────────────────────
  test('preset EBU R128 establece -23 / -1 / 18', async ({ page }) => {
    await page.locator('#dcPresets .preset').filter({ hasText: 'EBU R128' }).click();
    await expect(page.locator('#dcLufsInput')).toHaveValue('-23');
    await expect(page.locator('#dcTpInput')).toHaveValue('-1');
    await expect(page.locator('#dcLraInput')).toHaveValue('18');
  });

  // ── Test 8: Parámetros del compresor con valores por defecto ──────────────
  test('los campos del compresor tienen valores por defecto editables', async ({ page }) => {
    await expect(page.locator('#dcRatio')).toHaveValue('2');
    await expect(page.locator('#dcAttack')).toHaveValue('20');
    await expect(page.locator('#dcRelease')).toHaveValue('250');
    const kneeOptions = await page.locator('#dcKnee option').allTextContents();
    expect(kneeOptions).toEqual(['Soft', 'Hard']);
  });

  // ── Test 9: El botón Render Broadcast está deshabilitado al inicio ────────
  test('el botón Render Broadcast está deshabilitado antes de cargar un archivo', async ({ page }) => {
    await expect(page.locator('#dcRenderBtn')).toBeDisabled();
  });

});
