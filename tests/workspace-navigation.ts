import { expect, type Page } from '@playwright/test';

export function groupSwitcher(page: Page) {
  return page.getByRole('button', { name: /^切换发布组，当前 / });
}

export async function openGroupMenu(page: Page) {
  const menu = page.getByRole('dialog', { name: '切换发布组' });
  if (!await menu.isVisible()) {
    const switcher = groupSwitcher(page);
    if (!await switcher.isVisible() && await page.evaluate(() => window.innerWidth < 768)) {
      await page.getByRole('button', { name: '切换侧栏' }).click();
    }
    await switcher.click();
  }
  await expect(menu).toBeVisible();
  return menu;
}

export async function selectGroup(page: Page, name: string) {
  const menu = await openGroupMenu(page);
  await menu.getByRole('button', { name, exact: true }).click();
  await expect(menu).toBeHidden();
  await expect.poll(async () => page.evaluate(async expected => {
    const state = await window.publisher.request<import('../src/types').State>('state');
    return state.groups.find(group => group.id === state.active_group_id)?.name === expected;
  }, name)).toBe(true);
}
