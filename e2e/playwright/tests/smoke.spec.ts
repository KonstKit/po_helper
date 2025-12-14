import { test, expect } from '@playwright/test';

const apiURL = process.env.E2E_API_URL || 'http://localhost:8000/health';

// Simple smoke tests to ensure core services respond before running deeper E2E coverage.

test('backend health endpoint responds with JSON', async ({ request }) => {
  const response = await request.get(apiURL);
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  expect(body).toMatchObject({ status: expect.stringMatching(/healthy|ok/i) });
});

test('login page renders branding', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /po helper/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: /sign in to continue/i })).toBeVisible();
});
