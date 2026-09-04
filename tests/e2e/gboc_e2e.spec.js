// GBOC System v14.0.0 Full Stable Enterprise — End-to-End (E2E) Test Suite with Playwright
const { test, expect } = require('@playwright/test');

test.describe('GBOC Server & Agent E2E Integrity Suite', () => {

  test('Validação do Dashboard Principal e Topbar', async ({ page }) => {
    await page.goto('http://localhost:8000/dashboard.html');
    await expect(page).toHaveTitle(/GBOC/i);
    const badge = page.locator('#serverVersionBadge');
    if (await badge.isVisible()) {
      await expect(badge).toContainText('v14.0.0');
    }
  });

  test('Validação de Endpoints HTTP do Servidor Central (Zero-Mock)', async ({ request }) => {
    const response = await request.get('http://localhost:8000/api/v1/ai/config');
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.status).toBe('success');
  });

  test('Validação da Interface Web do Agente GBOC', async ({ page }) => {
    await page.goto('http://localhost:9200/');
    await expect(page.locator('body')).toBeVisible();
  });

});
