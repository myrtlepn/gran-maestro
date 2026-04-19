import { test, expect } from '@playwright/test';

test.describe('SettingsView TagInput Edit UI', () => {
  test('should render TagInput for protected_branches and support add/edit/remove', async ({ page }) => {
    page.on('console', msg => console.log('BROWSER LOG:', msg.text()));
    page.on('pageerror', err => console.log('BROWSER ERROR:', err.message));

    await page.route('**/api/projects', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([{ id: 'test-project', name: 'Test', path: '/' }])
      });
    });

    await page.route('**/api/mode', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ active: false })
      });
    });

    // Mock the backend API
    await page.route('**/api/projects/test-project/config', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          merged: {
            worktree: {
              root_directory: '/tmp',
              max_active: 5,
              base_branch: 'main',
              protected_branches: ['main', 'master', 'release/*'],
              stale_timeout_hours: 24,
              auto_cleanup_on_cancel: true,
            }
          },
          overrides: {},
          defaults: {}
        })
      });
    });

    // We assume the frontend dev server is running on http://localhost:5173
    // But since we just want to run an execution test, let's start the vite server if needed.
    // Let's actually assume we'll start vite and run the test against it.
    await page.addInitScript(() => {
      window.sessionStorage.setItem('gm_project', 'test-project');
    });

    await page.goto('http://localhost:5173/settings');

    // Wait for the config to load and Settings to render
    // Since the routing and page structure might be complex, let's just wait for the Advanced section or the Tag badges
    
    // We might need to click on "고급" (Advanced) tab to see worktree settings
    const advancedTab = page.locator('button[role="tab"]', { hasText: '고급' });
    await advancedTab.waitFor({ state: 'visible' });
    await advancedTab.click();
    
    // Open "worktree" accordion if not already open
    const worktreeTrigger = page.locator('button[aria-expanded]', { hasText: 'worktree' });
    await worktreeTrigger.waitFor({ state: 'visible' });
    const isExpanded = await worktreeTrigger.getAttribute('aria-expanded') === 'true';
    if (!isExpanded) {
      await worktreeTrigger.click();
    }

    // Verify the protected_branches tag is rendered
    const tagMain = page.locator('.font-mono.text-xs', { hasText: 'main' }).first();
    await expect(tagMain).toBeVisible();

    const tagRelease = page.locator('.font-mono.text-xs', { hasText: 'release/*' }).first();
    await expect(tagRelease).toBeVisible();

    // Test Adding a new tag
    const addInput = page.locator('input[placeholder="Add..."]').first();
    await addInput.fill('new-branch');
    await addInput.press('Enter');
    
    const newTag = page.locator('.font-mono.text-xs', { hasText: 'new-branch' }).first();
    await expect(newTag).toBeVisible();

    // Test Editing a tag
    await newTag.click(); // should turn into input
    const editInput = page.locator('input.w-\\[120px\\]').first();
    await expect(editInput).toBeVisible();
    await editInput.fill('edited-branch');
    await editInput.press('Enter');

    const editedTag = page.locator('.font-mono.text-xs', { hasText: 'edited-branch' }).first();
    await expect(editedTag).toBeVisible();
    await expect(newTag).not.toBeVisible();

    // Test Removing a tag
    // The close button is next to the tag text
    const editedBadge = editedTag.locator('..'); 
    const closeBtn = editedBadge.locator('button[aria-label="Remove edited-branch"]');
    await closeBtn.click();

    await expect(editedTag).not.toBeVisible();
  });
});
