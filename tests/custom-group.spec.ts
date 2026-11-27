import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { _electron, expect, test } from '@playwright/test';
import { groupSwitcher, openGroupMenu, selectGroup } from './workspace-navigation';
import type { State } from '../src/types';

test('eight accounts bind independently, survive restart, and keep their identities in a batch', async ({}, testInfo) => {
  test.setTimeout(220_000);
  const project = process.cwd();
  const dataDir = testInfo.outputPath('data');
  await mkdir(dataDir, { recursive: true });
  const media = path.join(dataDir, 'test-video.mp4');
  await writeFile(media, 'video fixture');
  const launch = () => _electron.launch({ args: [project], cwd: project, env: {
    ...process.env, ZT_PUBLISHER_DATA_DIR: dataDir, ZT_WORKER_SCRIPT: path.join(project, 'tests', 'fixture_worker.py'),
  } });
  let app = await launch();
  try {
    let page = await app.firstWindow();
    await (await openGroupMenu(page)).getByRole('button', { name: '新建发布组', exact: true }).click();
    const create = page.getByRole('dialog', { name: '新建发布组' });
    await expect(create.getByRole('radio', { name: '常规组', exact: true })).toBeChecked();
    await create.getByRole('radio', { name: '自定义组', exact: true }).click();
    await create.getByLabel('发布组名称').fill('矩阵验收');
    await create.getByRole('button', { name: '创建发布组' }).click();
    await expect(page.getByText('暂无平台账号', { exact: true })).toBeVisible();

    const platforms = ['抖音', '小红书'];
    for (const platform of platforms) {
      await page.getByRole('button', { name: '添加平台账号' }).click();
      const add = page.getByRole('dialog', { name: '添加平台账号' });
      await add.getByRole('combobox', { name: '平台', exact: true }).click();
      const platformList = page.getByRole('listbox');
      const viewport = platformList.locator('[data-radix-select-viewport]');
      await expect(platformList.locator('[data-slot="select-scroll-down-button"], [data-slot="select-scroll-up-button"]')).toHaveCount(0);
      await viewport.hover();
      await page.mouse.wheel(0, 240);
      await expect.poll(() => viewport.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
      await page.keyboard.press('Home');
      await expect.poll(() => viewport.evaluate(element => element.scrollTop)).toBe(0);
      await page.getByRole('option', { name: platform, exact: true }).click();
      await add.getByLabel('账号数量').fill('4');
      await add.getByRole('button', { name: '添加账号', exact: true }).click();
      await expect(add).toBeHidden();
      await expect(page.getByRole('article', { name: new RegExp(`^${platform} [1-4]$`) })).toHaveCount(4);
    }
    const accounts = platforms.flatMap(platform => Array.from({ length: 4 }, (_, index) => ({
      name: `${platform} ${index + 1}`, label: `${platform}验收${index + 1}`,
    })));
    for (const { name, label } of accounts) {
      const row = page.getByRole('article', { name, exact: true });
      await row.getByRole('button', { name: '绑定账号' }).click();
      const bind = page.getByRole('dialog', { name: `绑定${name}`, exact: true });
      await expect(bind.getByLabel('账号昵称或备注')).toHaveValue(name);
      await bind.getByRole('button', { name: '打开扫码窗口' }).click();
      await bind.getByLabel('账号昵称或备注').fill(label);
      await bind.getByRole('button', { name: '确认绑定' }).click();
      await expect(row.getByText('已绑定', { exact: true })).toBeVisible();
    }
    const state = await page.evaluate(() => window.publisher.request<State>('state'));
    const group = state.groups.find(item => item.name === '矩阵验收')!;
    expect(group.mode).toBe('custom');
    const bindings = state.bindings.filter(binding => binding.group_id === group.id);
    expect(new Set(bindings.map(binding => binding.id)).size).toBe(8);
    for (const binding of bindings) {
      const stored = await readFile(path.join(dataDir, 'profiles', binding.id, 'session.dat'));
      expect(stored.length).toBeGreaterThan(0);
      expect(stored.includes(Buffer.from(binding.id))).toBe(false);
    }

    await app.close();
    app = await launch();
    page = await app.firstWindow();
    await expect(groupSwitcher(page)).toHaveAccessibleName('切换发布组，当前 矩阵验收');
    await page.getByRole('button', { name: '新建发布', exact: true }).click();
    for (const { name, label } of accounts) {
      await expect(page.getByRole('checkbox', { name: `选择${name} ${label}`, exact: true })).toBeVisible();
    }
    const restored = await page.evaluate(() => window.publisher.request<State>('state'));
    const restoredAccounts = restored.bindings.filter(binding => binding.group_id === group.id);
    expect(restoredAccounts.map(binding => binding.id)).toEqual(bindings.map(binding => binding.id));
    expect(restoredAccounts.every(binding => binding.login_status === 'saved')).toBe(true);

    await app.evaluate(({ dialog }, file) => {
      dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [file] });
    }, media);
    await page.getByRole('button', { name: '选择本地视频' }).click();
    await page.getByPlaceholder('输入视频标题').fill('矩阵群发验收');
    await page.getByRole('button', { name: '全选', exact: true }).click();
    const tabs = page.getByRole('tablist', { name: '平台文案' });
    await tabs.getByRole('tab', { name: '抖音 3', exact: true }).click();
    await page.getByRole('textbox', { name: '抖音 3标题' }).fill('第三个抖音专用标题');
    await page.getByRole('combobox', { name: '抖音作品声明' }).click();
    await page.getByRole('option', { name: '无需添加自主声明', exact: true }).click();
    await page.getByRole('button', { name: '核对并群发' }).click();
    const confirm = page.getByRole('dialog', { name: '核对发布内容' });
    for (const { name } of accounts) {
      await expect(confirm.getByRole('region', { name: `${name}发布预览`, exact: true })).toBeVisible();
    }
    await confirm.getByRole('button', { name: '确认并群发' }).click();
    await expect(confirm).toBeHidden();
    await selectGroup(page, '账号 B');
    await expect(page.getByText('暂无发布记录', { exact: true })).toBeVisible();
    await selectGroup(page, '矩阵验收');
    await expect(page.getByText('已提交', { exact: true })).toHaveCount(8, { timeout: 70_000 });
    const deliveries = (await readFile(path.join(dataDir, 'fixture-deliveries.jsonl'), 'utf8'))
      .trim().split('\n').map(line => JSON.parse(line));
    expect(deliveries).toHaveLength(8);
    expect(deliveries.every(row => row.expected === row.actual && row.group === group.id)).toBe(true);
    expect(deliveries.map(row => row.actual).sort()).toEqual(bindings.map(binding => binding.id).sort());
    expect(new Set(deliveries.map(row => row.paths[0])).size).toBe(1);
    expect(deliveries.find(row => row.actual === bindings.find(binding => binding.platform === 'douyin' && binding.slot === 3)?.id).title)
      .toBe('第三个抖音专用标题');
    expect(deliveries.filter(row => row.title === '矩阵群发验收')).toHaveLength(7);

    await page.getByRole('button', { name: '平台账号', exact: true }).click();
    const removeRow = page.getByRole('article', { name: '抖音 2', exact: true });
    const removeButton = removeRow.getByRole('button', { name: '删除抖音 2', exact: true });
    await removeButton.click();
    const removeDialog = page.getByRole('dialog', { name: '删除平台账号' });
    await removeDialog.getByRole('button', { name: '取消', exact: true }).click();
    await expect(removeRow).toBeVisible();
    await removeButton.click();
    await removeDialog.getByRole('button', { name: '确认删除' }).click();
    await expect(removeRow).toHaveCount(0);
    await expect(page.getByRole('article', { name: '抖音 3', exact: true })).toBeVisible();
    const removedBinding = bindings.find(binding => binding.platform === 'douyin' && binding.slot === 2)!;
    const backup = path.join(dataDir, 'profiles', removedBinding.id, 'session.dat');
    await expect(readFile(backup)).rejects.toMatchObject({ code: 'ENOENT' });
    await page.getByRole('button', { name: '发布记录', exact: true }).click();
    await expect(page.getByRole('article', { name: '抖音 2 · 抖音验收2', exact: true })).toBeVisible();
  } finally {
    await app.close();
  }
});
