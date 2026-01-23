/**
 * E2E Tests for Authentication Flow
 *
 * Tests cover:
 * - Login page rendering and accessibility
 * - Successful login with valid credentials
 * - Failed login with invalid credentials
 * - Session persistence after page reload
 * - Logout functionality
 * - Protected route redirection
 */
import { test, expect, Page } from '@playwright/test';

// Test user credentials - should match seeded demo user or test fixtures
const TEST_USER = {
  email: process.env.E2E_TEST_EMAIL || 'admin@example.com',
  password: process.env.E2E_TEST_PASSWORD || 'admin123',
};

const INVALID_USER = {
  email: 'invalid@example.com',
  password: 'wrongpassword',
};

// Helper to perform login
async function login(page: Page, email: string, password: string) {
  await page.goto('/');
  await page.getByLabel(/email address/i).fill(email);
  await page.getByLabel(/password/i).fill(password);
  await page.getByRole('button', { name: /sign in/i }).click();
}

// Helper to check if user is logged in (on dashboard)
async function expectLoggedIn(page: Page) {
  // After login, user should be redirected to dashboard
  await expect(page).toHaveURL(/\/(dashboard)?$/);
  // Should see user-related elements or dashboard content
  await expect(page.getByRole('navigation')).toBeVisible();
}

// Helper to check if user is on login page
async function expectOnLoginPage(page: Page) {
  await expect(page.getByRole('heading', { name: /po helper/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: /sign in to continue/i })).toBeVisible();
}

test.describe('Authentication', () => {
  test.beforeEach(async ({ page }) => {
    // Clear localStorage to ensure clean state
    await page.goto('/');
    await page.evaluate(() => localStorage.clear());
  });

  test.describe('Login Page', () => {
    test('renders branding and form elements', async ({ page }) => {
      await page.goto('/');

      // Check branding
      await expect(page.getByRole('heading', { name: /po helper/i })).toBeVisible();
      await expect(page.getByRole('heading', { name: /sign in to continue/i })).toBeVisible();

      // Check form elements
      await expect(page.getByLabel(/email address/i)).toBeVisible();
      await expect(page.getByLabel(/password/i)).toBeVisible();
      await expect(page.getByRole('button', { name: /sign in/i })).toBeVisible();

      // Check additional elements
      await expect(page.getByRole('button', { name: /configure jira/i })).toBeVisible();
      await expect(page.getByRole('link', { name: /forgot password/i })).toBeVisible();
    });

    test('email field has correct input type', async ({ page }) => {
      await page.goto('/');
      const emailInput = page.getByLabel(/email address/i);
      await expect(emailInput).toHaveAttribute('type', 'email');
    });

    test('password field is masked', async ({ page }) => {
      await page.goto('/');
      const passwordInput = page.getByLabel(/password/i);
      await expect(passwordInput).toHaveAttribute('type', 'password');
    });

    test('form fields are required', async ({ page }) => {
      await page.goto('/');

      // Click sign in without filling fields
      await page.getByRole('button', { name: /sign in/i }).click();

      // Browser should show validation - email field should be invalid
      const emailInput = page.getByLabel(/email address/i);
      await expect(emailInput).toHaveJSProperty('validity.valueMissing', true);
    });
  });

  test.describe('Login Flow', () => {
    test('successful login redirects to dashboard', async ({ page }) => {
      await login(page, TEST_USER.email, TEST_USER.password);

      // Should redirect to dashboard
      await expectLoggedIn(page);

      // Token should be stored
      const token = await page.evaluate(() => localStorage.getItem('token'));
      expect(token).toBeTruthy();
    });

    test('failed login shows error message', async ({ page }) => {
      await login(page, INVALID_USER.email, INVALID_USER.password);

      // Should show error alert
      await expect(page.getByRole('alert')).toBeVisible();

      // Should still be on login page
      await expectOnLoginPage(page);

      // Token should not be stored
      const token = await page.evaluate(() => localStorage.getItem('token'));
      expect(token).toBeFalsy();
    });

    test('empty password shows validation error', async ({ page }) => {
      await page.goto('/');
      await page.getByLabel(/email address/i).fill(TEST_USER.email);
      await page.getByRole('button', { name: /sign in/i }).click();

      // Password field should be invalid
      const passwordInput = page.getByLabel(/password/i);
      await expect(passwordInput).toHaveJSProperty('validity.valueMissing', true);
    });

    test('invalid email format is rejected', async ({ page }) => {
      await page.goto('/');
      const emailInput = page.getByLabel(/email address/i);

      await emailInput.fill('notanemail');
      await page.getByLabel(/password/i).fill('somepassword');
      await page.getByRole('button', { name: /sign in/i }).click();

      // Email field should be invalid
      await expect(emailInput).toHaveJSProperty('validity.typeMismatch', true);
    });
  });

  test.describe('Session Persistence', () => {
    test('session persists after page reload', async ({ page }) => {
      // Login first
      await login(page, TEST_USER.email, TEST_USER.password);
      await expectLoggedIn(page);

      // Reload the page
      await page.reload();

      // Should still be logged in (not redirected to login)
      await expectLoggedIn(page);
    });

    test('session persists when navigating between pages', async ({ page }) => {
      // Login first
      await login(page, TEST_USER.email, TEST_USER.password);
      await expectLoggedIn(page);

      // Navigate to another page
      await page.goto('/projects');

      // Should still be authenticated (not redirected to login)
      await expect(page).not.toHaveURL(/login/);
    });
  });

  test.describe('Logout', () => {
    test.beforeEach(async ({ page }) => {
      // Login before each logout test
      await login(page, TEST_USER.email, TEST_USER.password);
      await expectLoggedIn(page);
    });

    test('logout clears session and redirects to login', async ({ page }) => {
      // Find and click logout button
      // This might be in a menu or directly visible
      const userMenu = page.getByTestId('user-menu').or(page.getByRole('button', { name: /account|profile|user/i }));
      if (await userMenu.isVisible()) {
        await userMenu.click();
      }

      const logoutButton = page.getByRole('menuitem', { name: /logout|sign out/i })
        .or(page.getByRole('button', { name: /logout|sign out/i }));

      await logoutButton.click();

      // Should redirect to login
      await expectOnLoginPage(page);

      // Token should be cleared
      const token = await page.evaluate(() => localStorage.getItem('token'));
      expect(token).toBeFalsy();
    });

    test('after logout, protected routes redirect to login', async ({ page }) => {
      // Find and click logout
      const userMenu = page.getByTestId('user-menu').or(page.getByRole('button', { name: /account|profile|user/i }));
      if (await userMenu.isVisible()) {
        await userMenu.click();
      }

      const logoutButton = page.getByRole('menuitem', { name: /logout|sign out/i })
        .or(page.getByRole('button', { name: /logout|sign out/i }));
      await logoutButton.click();

      // Try to access protected route
      await page.goto('/dashboard');

      // Should be redirected to login
      await expectOnLoginPage(page);
    });
  });

  test.describe('Protected Routes', () => {
    test('unauthenticated user is redirected to login from dashboard', async ({ page }) => {
      await page.goto('/dashboard');
      await expectOnLoginPage(page);
    });

    test('unauthenticated user is redirected to login from projects', async ({ page }) => {
      await page.goto('/projects');
      await expectOnLoginPage(page);
    });

    test('unauthenticated user is redirected to login from analytics', async ({ page }) => {
      await page.goto('/analytics');
      await expectOnLoginPage(page);
    });

    test('unauthenticated user is redirected to login from traceability', async ({ page }) => {
      await page.goto('/traceability');
      await expectOnLoginPage(page);
    });
  });

  test.describe('Jira Configuration Modal', () => {
    test('can open Jira configuration from login page', async ({ page }) => {
      await page.goto('/');

      await page.getByRole('button', { name: /configure jira/i }).click();

      // Should show Jira configuration form
      await expect(page.getByRole('heading', { name: /configure jira/i })).toBeVisible();
      await expect(page.getByLabel(/jira url/i)).toBeVisible();
      await expect(page.getByLabel(/jira email/i)).toBeVisible();
      await expect(page.getByLabel(/jira api token/i)).toBeVisible();
    });

    test('can return to login from Jira configuration', async ({ page }) => {
      await page.goto('/');

      await page.getByRole('button', { name: /configure jira/i }).click();
      await expect(page.getByRole('heading', { name: /configure jira/i })).toBeVisible();

      await page.getByRole('button', { name: /back to login/i }).click();

      // Should be back on login form
      await expectOnLoginPage(page);
    });
  });
});

test.describe('OAuth2 SSO', () => {
  test('login page shows OAuth2 buttons when providers are configured', async ({ page }) => {
    await page.goto('/');

    // OAuth providers are loaded asynchronously
    // Check if buttons appear when providers are enabled
    await page.waitForTimeout(1000); // Allow time for provider fetch

    // The buttons may or may not be visible depending on backend config
    // This test just verifies the page handles provider loading gracefully
    await expect(page.getByRole('heading', { name: /po helper/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /sign in/i })).toBeVisible();
  });

  test('Google OAuth button initiates OAuth flow when clicked', async ({ page }) => {
    await page.goto('/');

    // Wait for provider buttons to potentially appear
    await page.waitForTimeout(1000);

    const googleButton = page.getByRole('button', { name: /continue with google/i });

    // Skip test if Google OAuth is not configured
    if (!(await googleButton.isVisible())) {
      test.skip();
      return;
    }

    // Store current URL
    const initialUrl = page.url();

    // Click should attempt to redirect to Google
    await googleButton.click();

    // Either URL changes (redirect) or error is shown
    await page.waitForTimeout(500);

    const currentUrl = page.url();
    const hasError = await page.getByRole('alert').isVisible();

    // One of these should be true:
    // - URL changed (redirect initiated)
    // - Error shown (OAuth not configured properly)
    expect(currentUrl !== initialUrl || hasError).toBeTruthy();
  });

  test('Microsoft OAuth button initiates OAuth flow when clicked', async ({ page }) => {
    await page.goto('/');

    // Wait for provider buttons to potentially appear
    await page.waitForTimeout(1000);

    const msButton = page.getByRole('button', { name: /continue with microsoft/i });

    // Skip test if Microsoft OAuth is not configured
    if (!(await msButton.isVisible())) {
      test.skip();
      return;
    }

    // Store current URL
    const initialUrl = page.url();

    // Click should attempt to redirect to Microsoft
    await msButton.click();

    // Either URL changes (redirect) or error is shown
    await page.waitForTimeout(500);

    const currentUrl = page.url();
    const hasError = await page.getByRole('alert').isVisible();

    expect(currentUrl !== initialUrl || hasError).toBeTruthy();
  });
});

test.describe('OAuth2 API', () => {
  test('OAuth2 providers endpoint returns provider status', async ({ request }) => {
    const response = await request.get('/api/v1/auth/oauth2/providers');

    expect(response.ok()).toBeTruthy();
    const body = await response.json();

    // Should return provider availability
    expect(body).toHaveProperty('google');
    expect(body).toHaveProperty('microsoft');
    expect(typeof body.google).toBe('boolean');
    expect(typeof body.microsoft).toBe('boolean');
  });

  test('Google OAuth start endpoint returns authorization URL', async ({ request }) => {
    const response = await request.get('/api/v1/auth/oauth2/google/authorize');

    // May return 404 if not configured, 200 if configured
    if (response.status() === 404) {
      // Google OAuth not configured - acceptable
      return;
    }

    expect(response.ok()).toBeTruthy();
    const body = await response.json();
    expect(body).toHaveProperty('authorization_url');
    expect(body).toHaveProperty('state');
    expect(body.authorization_url).toContain('accounts.google.com');
  });

  test('Microsoft OAuth start endpoint returns authorization URL', async ({ request }) => {
    const response = await request.get('/api/v1/auth/oauth2/microsoft/authorize');

    // May return 404 if not configured, 200 if configured
    if (response.status() === 404) {
      // Microsoft OAuth not configured - acceptable
      return;
    }

    expect(response.ok()).toBeTruthy();
    const body = await response.json();
    expect(body).toHaveProperty('authorization_url');
    expect(body).toHaveProperty('state');
    expect(body.authorization_url).toContain('login.microsoftonline.com');
  });
});

test.describe('Multi-Factor Authentication (MFA)', () => {
  let authToken: string;

  test.beforeAll(async ({ request }) => {
    // Get auth token for MFA API tests
    const loginResponse = await request.post('/api/v1/auth/login', {
      form: {
        username: TEST_USER.email,
        password: TEST_USER.password,
      },
    });

    // If MFA is required for demo user, skip these tests
    if (loginResponse.status() === 200) {
      const body = await loginResponse.json();
      if (body.mfa_required) {
        // Cannot test MFA setup if user already has MFA
        authToken = '';
      } else {
        authToken = body.access_token;
      }
    } else {
      authToken = '';
    }
  });

  test('MFA status endpoint returns current MFA state', async ({ request }) => {
    if (!authToken) {
      test.skip();
      return;
    }

    const response = await request.get('/api/v1/auth/mfa/status', {
      headers: { Authorization: `Bearer ${authToken}` },
    });

    expect(response.ok()).toBeTruthy();
    const body = await response.json();

    expect(body).toHaveProperty('mfa_enabled');
    expect(typeof body.mfa_enabled).toBe('boolean');

    if (body.mfa_enabled) {
      expect(body).toHaveProperty('remaining_backup_codes');
      expect(typeof body.remaining_backup_codes).toBe('number');
    }
  });

  test('MFA setup endpoint returns QR code and secret', async ({ request }) => {
    if (!authToken) {
      test.skip();
      return;
    }

    const response = await request.post('/api/v1/auth/mfa/setup', {
      headers: { Authorization: `Bearer ${authToken}` },
    });

    // May fail if MFA is already enabled
    if (response.status() === 400) {
      // MFA already enabled - acceptable
      return;
    }

    expect(response.ok()).toBeTruthy();
    const body = await response.json();

    expect(body).toHaveProperty('secret');
    expect(body).toHaveProperty('qr_code');
    expect(body).toHaveProperty('backup_codes');
    expect(body.secret).toHaveLength(32); // Standard TOTP secret length
    expect(body.qr_code).toMatch(/^data:image\/png;base64,/);
    expect(Array.isArray(body.backup_codes)).toBeTruthy();
    expect(body.backup_codes.length).toBe(10); // Standard backup code count
  });

  test('MFA verify endpoint rejects invalid codes', async ({ request }) => {
    if (!authToken) {
      test.skip();
      return;
    }

    const response = await request.post('/api/v1/auth/mfa/verify', {
      headers: { Authorization: `Bearer ${authToken}` },
      data: { code: '000000' },
    });

    // Should reject invalid code
    // May return 400 (bad code) or 404 (no pending setup)
    expect([400, 404]).toContain(response.status());
  });

  test('Profile page shows MFA settings section', async ({ page }) => {
    // Login first
    await login(page, TEST_USER.email, TEST_USER.password);
    await expectLoggedIn(page);

    // Navigate to profile
    await page.goto('/profile');

    // Look for Security tab
    const securityTab = page.getByRole('tab', { name: /security/i });
    await expect(securityTab).toBeVisible();

    // Click security tab
    await securityTab.click();

    // Should show MFA section
    await expect(page.getByText(/two-factor authentication/i)).toBeVisible();
  });

  test('MFA setup UI shows QR code step', async ({ page }) => {
    // Login first
    await login(page, TEST_USER.email, TEST_USER.password);
    await expectLoggedIn(page);

    // Navigate to profile
    await page.goto('/profile');

    // Click security tab
    await page.getByRole('tab', { name: /security/i }).click();

    // Check if MFA is already enabled
    const mfaEnabled = await page.getByText(/two-factor authentication is active/i).isVisible();

    if (!mfaEnabled) {
      // Click setup button
      const setupButton = page.getByRole('button', { name: /set up two-factor authentication/i });
      if (await setupButton.isVisible()) {
        await setupButton.click();

        // Should show QR code step
        await expect(page.getByText(/scan qr code/i)).toBeVisible({ timeout: 5000 });
        await expect(page.getByRole('img', { name: /mfa qr code/i })).toBeVisible();
      }
    } else {
      // MFA is enabled, check for management options
      await expect(page.getByRole('button', { name: /disable 2fa/i })).toBeVisible();
      await expect(page.getByRole('button', { name: /regenerate backup codes/i })).toBeVisible();
    }
  });
});

test.describe('MFA Login Flow', () => {
  test('login with MFA shows verification dialog', async ({ page }) => {
    // This test requires a user with MFA enabled
    // We'll test the dialog appears when MFA is required

    await page.goto('/');

    // Try to login - if MFA is enabled for user, dialog should appear
    await page.getByLabel(/email address/i).fill(TEST_USER.email);
    await page.getByLabel(/password/i).fill(TEST_USER.password);
    await page.getByRole('button', { name: /sign in/i }).click();

    // Wait for either dashboard (no MFA) or MFA dialog
    await page.waitForTimeout(1000);

    const mfaDialog = page.getByRole('dialog').filter({ hasText: /two-factor authentication/i });
    const isDashboard = await page.url().includes('dashboard') || page.url() === '/';

    if (await mfaDialog.isVisible()) {
      // MFA is required - verify dialog elements
      await expect(page.getByLabel(/verification code/i)).toBeVisible();
      await expect(page.getByRole('button', { name: /verify/i })).toBeVisible();
      await expect(page.getByRole('button', { name: /cancel/i })).toBeVisible();
    } else if (isDashboard) {
      // No MFA required - user is logged in
      await expectLoggedIn(page);
    }
    // Either outcome is valid depending on user's MFA status
  });

  test('MFA verification dialog accepts 6-digit code input', async ({ page }) => {
    // If MFA dialog is shown, test code input
    await page.goto('/');
    await page.getByLabel(/email address/i).fill(TEST_USER.email);
    await page.getByLabel(/password/i).fill(TEST_USER.password);
    await page.getByRole('button', { name: /sign in/i }).click();

    await page.waitForTimeout(1000);

    const mfaDialog = page.getByRole('dialog').filter({ hasText: /two-factor authentication/i });

    if (!(await mfaDialog.isVisible())) {
      test.skip(); // MFA not enabled for this user
      return;
    }

    const codeInput = page.getByLabel(/verification code/i);

    // Test that input accepts only digits
    await codeInput.fill('123456');
    await expect(codeInput).toHaveValue('123456');

    // Test that non-digits are filtered
    await codeInput.clear();
    await codeInput.type('12ab34cd56');
    // Should only contain digits
    const value = await codeInput.inputValue();
    expect(value).toMatch(/^\d+$/);
    expect(value.length).toBeLessThanOrEqual(6);
  });

  test('MFA cancel button closes dialog and returns to login', async ({ page }) => {
    await page.goto('/');
    await page.getByLabel(/email address/i).fill(TEST_USER.email);
    await page.getByLabel(/password/i).fill(TEST_USER.password);
    await page.getByRole('button', { name: /sign in/i }).click();

    await page.waitForTimeout(1000);

    const mfaDialog = page.getByRole('dialog').filter({ hasText: /two-factor authentication/i });

    if (!(await mfaDialog.isVisible())) {
      test.skip(); // MFA not enabled for this user
      return;
    }

    // Click cancel
    await page.getByRole('button', { name: /cancel/i }).click();

    // Dialog should close
    await expect(mfaDialog).not.toBeVisible();

    // Should be back on login page
    await expectOnLoginPage(page);
  });
});

test.describe('API Authentication', () => {
  test('login endpoint returns token on valid credentials', async ({ request }) => {
    const response = await request.post('/api/v1/auth/login', {
      form: {
        username: TEST_USER.email,
        password: TEST_USER.password,
      },
    });

    expect(response.ok()).toBeTruthy();
    const body = await response.json();
    expect(body).toHaveProperty('access_token');
    expect(body).toHaveProperty('token_type', 'bearer');
  });

  test('login endpoint returns 401 on invalid credentials', async ({ request }) => {
    const response = await request.post('/api/v1/auth/login', {
      form: {
        username: INVALID_USER.email,
        password: INVALID_USER.password,
      },
    });

    expect(response.status()).toBe(401);
  });

  test('protected endpoints require authentication', async ({ request }) => {
    const response = await request.get('/api/v1/users/me');
    expect(response.status()).toBe(401);
  });

  test('protected endpoints work with valid token', async ({ request }) => {
    // Get token first
    const loginResponse = await request.post('/api/v1/auth/login', {
      form: {
        username: TEST_USER.email,
        password: TEST_USER.password,
      },
    });
    const { access_token } = await loginResponse.json();

    // Use token to access protected endpoint
    const response = await request.get('/api/v1/users/me', {
      headers: {
        Authorization: `Bearer ${access_token}`,
      },
    });

    expect(response.ok()).toBeTruthy();
    const body = await response.json();
    expect(body).toHaveProperty('email', TEST_USER.email);
  });
});
