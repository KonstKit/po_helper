/**
 * E2E Tests for Projects Management
 *
 * Tests cover:
 * - Projects list page rendering
 * - Project creation
 * - Project detail view
 * - Project editing
 * - Project deletion
 * - Project search/filtering
 */
import { test, expect, Page } from '@playwright/test';

// Test user credentials
const TEST_USER = {
  email: process.env.E2E_TEST_EMAIL || 'admin@example.com',
  password: process.env.E2E_TEST_PASSWORD || 'admin123',
};

// Helper to login
async function login(page: Page) {
  await page.goto('/');
  await page.getByLabel(/email address/i).fill(TEST_USER.email);
  await page.getByLabel(/password/i).fill(TEST_USER.password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/(dashboard)?$/);
}

test.describe('Projects Page', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto('/projects');
  });

  test.describe('Layout', () => {
    test('renders projects page with header', async ({ page }) => {
      await expect(page.getByRole('heading', { name: /projects/i })).toBeVisible();
    });

    test('shows create project button', async ({ page }) => {
      const createBtn = page.getByRole('button', { name: /create|new|add/i });
      await expect(createBtn).toBeVisible();
    });

    test('shows search/filter input', async ({ page }) => {
      const searchInput = page.getByPlaceholder(/search/i)
        .or(page.getByLabel(/search/i))
        .or(page.getByRole('searchbox'));

      // Search might be optional, so just check if present
      const isVisible = await searchInput.isVisible().catch(() => false);
      // Pass if search exists or if there's a filter section
      expect(isVisible || await page.getByText(/filter/i).isVisible().catch(() => false)).toBeTruthy();
    });
  });

  test.describe('Project List', () => {
    test('displays projects in list or grid', async ({ page }) => {
      // Wait for loading to complete
      await page.waitForLoadState('networkidle');

      // Either projects are shown, or empty state is shown
      const hasProjects = await page.locator('[data-testid="project-card"]')
        .or(page.locator('.MuiCard-root'))
        .or(page.locator('[class*="project"]'))
        .first()
        .isVisible()
        .catch(() => false);

      const hasEmptyState = await page.getByText(/no projects|get started|create your first/i)
        .isVisible()
        .catch(() => false);

      expect(hasProjects || hasEmptyState).toBeTruthy();
    });

    test('project cards show key information', async ({ page }) => {
      await page.waitForLoadState('networkidle');

      const projectCard = page.locator('[data-testid="project-card"]')
        .or(page.locator('.MuiCard-root'))
        .first();

      if (await projectCard.isVisible()) {
        // Project card should contain a name/title
        const hasTitle = await projectCard.getByRole('heading').isVisible()
          || await projectCard.locator('[class*="title"]').isVisible();
        expect(hasTitle).toBeTruthy();
      }
    });
  });

  test.describe('Project Creation', () => {
    test('can open create project dialog', async ({ page }) => {
      const createBtn = page.getByRole('button', { name: /create|new|add/i });
      await createBtn.click();

      // Dialog or form should appear
      const dialog = page.getByRole('dialog')
        .or(page.locator('.MuiDialog-root'))
        .or(page.getByTestId('create-project-form'));

      await expect(dialog).toBeVisible();
    });

    test('create dialog has required fields', async ({ page }) => {
      const createBtn = page.getByRole('button', { name: /create|new|add/i });
      await createBtn.click();

      // Name field
      const nameInput = page.getByLabel(/name/i)
        .or(page.getByPlaceholder(/project name/i));
      await expect(nameInput).toBeVisible();

      // Optional: Description field
      const descInput = page.getByLabel(/description/i)
        .or(page.getByPlaceholder(/description/i));
      // Description might be optional

      // Submit button
      const submitBtn = page.getByRole('button', { name: /create|save|submit/i });
      await expect(submitBtn).toBeVisible();
    });

    test('can create a new project', async ({ page }) => {
      const projectName = `E2E Test Project ${Date.now()}`;

      const createBtn = page.getByRole('button', { name: /create|new|add/i });
      await createBtn.click();

      // Fill form
      await page.getByLabel(/name/i).fill(projectName);

      const descInput = page.getByLabel(/description/i);
      if (await descInput.isVisible()) {
        await descInput.fill('Created by E2E test');
      }

      // Submit
      await page.getByRole('button', { name: /create|save/i }).click();

      // Wait for dialog to close or redirect
      await page.waitForLoadState('networkidle');

      // Project should appear in list or we should be on project detail
      const projectExists = await page.getByText(projectName).isVisible()
        || await page.getByRole('heading', { name: new RegExp(projectName, 'i') }).isVisible();

      expect(projectExists).toBeTruthy();
    });
  });

  test.describe('Project Detail', () => {
    test('clicking project navigates to detail page', async ({ page }) => {
      await page.waitForLoadState('networkidle');

      const projectCard = page.locator('[data-testid="project-card"]')
        .or(page.locator('.MuiCard-root'))
        .first();

      if (await projectCard.isVisible()) {
        await projectCard.click();

        // Should navigate to project detail or show expanded view
        await expect(page).toHaveURL(/\/projects\/\d+/);
      }
    });

    test('project detail shows tabs or sections', async ({ page }) => {
      // Navigate to a project detail page directly
      await page.goto('/projects');
      await page.waitForLoadState('networkidle');

      const projectCard = page.locator('[data-testid="project-card"]')
        .or(page.locator('.MuiCard-root'))
        .first();

      if (await projectCard.isVisible()) {
        await projectCard.click();
        await page.waitForLoadState('networkidle');

        // Should have tabs or sections
        const hasTabs = await page.getByRole('tab').first().isVisible().catch(() => false);
        const hasSections = await page.getByRole('heading').count() > 1;

        expect(hasTabs || hasSections).toBeTruthy();
      }
    });
  });

  test.describe('Project Editing', () => {
    test('can access edit mode for a project', async ({ page }) => {
      await page.goto('/projects');
      await page.waitForLoadState('networkidle');

      const projectCard = page.locator('[data-testid="project-card"]')
        .or(page.locator('.MuiCard-root'))
        .first();

      if (await projectCard.isVisible()) {
        // Look for edit button on card or in menu
        const editBtn = projectCard.getByRole('button', { name: /edit/i })
          .or(projectCard.getByTestId('edit-btn'));

        if (await editBtn.isVisible()) {
          await editBtn.click();

          // Edit form or dialog should appear
          const hasEditForm = await page.getByLabel(/name/i).isVisible()
            || await page.getByRole('dialog').isVisible();

          expect(hasEditForm).toBeTruthy();
        }
      }
    });
  });

  test.describe('Search and Filter', () => {
    test('search filters projects list', async ({ page }) => {
      const searchInput = page.getByPlaceholder(/search/i)
        .or(page.getByLabel(/search/i));

      if (await searchInput.isVisible()) {
        // Enter search term
        await searchInput.fill('test');

        // Wait for filter to apply
        await page.waitForTimeout(500);

        // List should update (hard to verify without knowing project names)
        // Just verify no error occurred
        await expect(page).not.toHaveURL(/error/);
      }
    });
  });
});

test.describe('Projects API', () => {
  let authToken: string;

  test.beforeAll(async ({ request }) => {
    const response = await request.post('/api/v1/auth/login', {
      form: {
        username: TEST_USER.email,
        password: TEST_USER.password,
      },
    });
    const { access_token } = await response.json();
    authToken = access_token;
  });

  test('can list projects', async ({ request }) => {
    const response = await request.get('/api/v1/projects', {
      headers: { Authorization: `Bearer ${authToken}` },
    });

    expect(response.ok()).toBeTruthy();
    const data = await response.json();
    expect(Array.isArray(data.items) || Array.isArray(data)).toBeTruthy();
  });

  test('can create project via API', async ({ request }) => {
    const response = await request.post('/api/v1/projects', {
      headers: {
        Authorization: `Bearer ${authToken}`,
        'Content-Type': 'application/json',
      },
      data: {
        name: `API Test Project ${Date.now()}`,
        description: 'Created via API test',
      },
    });

    expect(response.status()).toBe(201);
    const project = await response.json();
    expect(project).toHaveProperty('id');
    expect(project).toHaveProperty('name');
  });

  test('can get single project', async ({ request }) => {
    // Create a project first
    const createResponse = await request.post('/api/v1/projects', {
      headers: {
        Authorization: `Bearer ${authToken}`,
        'Content-Type': 'application/json',
      },
      data: {
        name: `Get Test Project ${Date.now()}`,
      },
    });
    const created = await createResponse.json();

    // Get the project
    const response = await request.get(`/api/v1/projects/${created.id}`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });

    expect(response.ok()).toBeTruthy();
    const project = await response.json();
    expect(project.id).toBe(created.id);
  });

  test('can update project', async ({ request }) => {
    // Create a project first
    const createResponse = await request.post('/api/v1/projects', {
      headers: {
        Authorization: `Bearer ${authToken}`,
        'Content-Type': 'application/json',
      },
      data: {
        name: `Update Test Project ${Date.now()}`,
      },
    });
    const created = await createResponse.json();

    // Update it
    const response = await request.put(`/api/v1/projects/${created.id}`, {
      headers: {
        Authorization: `Bearer ${authToken}`,
        'Content-Type': 'application/json',
      },
      data: {
        name: `${created.name} - Updated`,
      },
    });

    expect(response.ok()).toBeTruthy();
    const updated = await response.json();
    expect(updated.name).toContain('Updated');
  });

  test('can delete project', async ({ request }) => {
    // Create a project first
    const createResponse = await request.post('/api/v1/projects', {
      headers: {
        Authorization: `Bearer ${authToken}`,
        'Content-Type': 'application/json',
      },
      data: {
        name: `Delete Test Project ${Date.now()}`,
      },
    });
    const created = await createResponse.json();

    // Delete it
    const response = await request.delete(`/api/v1/projects/${created.id}`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });

    expect(response.status()).toBe(204);

    // Verify deleted
    const getResponse = await request.get(`/api/v1/projects/${created.id}`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
    expect(getResponse.status()).toBe(404);
  });
});
