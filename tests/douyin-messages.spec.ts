import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { _electron, expect, test } from '@playwright/test';
import type { State } from '../src/types';

test('Douyin messages use official destinations and keep local drafts isolated by binding', async ({}, testInfo) => {
  const project = process.cwd();
  const dataDir = testInfo.outputPath('douyin-messages');
  const app = await _electron.launch({ args: [project], cwd: project, env: {
    ...process.env, ZT_PUBLISHER_DATA_DIR: dataDir, ZT_DOUYIN_MESSAGE_FIXTURE: '1',
    ZT_WORKER_SCRIPT: path.join(project, 'tests', 'comment_fixture.py'),
  } });
  try {
    const page = await app.firstWindow();
    await app.evaluate(({ shell }) => {
      const urls: string[] = [];
      Object.assign(globalThis, { relayfoldTestOfficialLinks: urls });
      shell.openExternal = async url => { urls.push(url); };
    });
    await page.getByRole('button', { name: '消息', exact: true }).click();
    await expect(page.getByRole('combobox', { name: '切换消息平台' })).toContainText('抖音');
    await expect(page.getByRole('tab', { name: '私信' })).toHaveAttribute('aria-selected', 'true');
    await page.getByRole('button', { name: '打开抖音聊天官网' }).click();
    const draft = page.getByRole('textbox', { name: '回复草稿' });
    await draft.fill('只属于演示抖音 A 的草稿');
    await page.getByRole('button', { name: '保存草稿' }).click();
    await expect(page.getByText('草稿已保存到本机。')).toBeVisible();
    const state = await page.evaluate(() => window.publisher.request<State>('state'));
    const binding = state.bindings.find(item => item.group_id === state.active_group_id && item.platform === 'douyin')!;
    const draftPath = path.join(dataDir, 'profiles', binding.id, 'douyin-message-draft.dat');
    expect((await readFile(draftPath)).includes(Buffer.from('只属于演示抖音 A 的草稿'))).toBe(false);

    await page.getByRole('button', { name: '账号 B', exact: true }).click();
    await expect(page.getByRole('button', { name: '切换抖音账号' })).toContainText('演示抖音 B');
    await expect(draft).toHaveValue('');
    await expect(page.evaluate(binding_id => window.publisher.request<State>('state').then(s =>
      window.publisher.request('messages.douyinDraft', { group_id: s.active_group_id, binding_id })), binding.id))
      .rejects.toThrow('请在原发布组选择对应的抖音账号。');
    await page.getByRole('button', { name: '账号 A', exact: true }).click();
    await expect(draft).toHaveValue('只属于演示抖音 A 的草稿');

    await page.getByRole('tab', { name: '评论', exact: true }).click();
    await page.getByRole('button', { name: '打开创作者中心' }).click();
    expect(await app.evaluate(() => Reflect.get(globalThis, 'relayfoldTestOfficialLinks'))).toEqual([
      'https://imdesktop.douyin.com/', 'https://creator.douyin.com/creator-micro/interactive/comment',
    ]);
    await page.getByRole('combobox', { name: '切换消息平台' }).click();
    await page.getByRole('option', { name: '小红书', exact: true }).click();
    await expect(page.getByRole('tab', { name: '收到评论' })).toBeVisible();
  } finally {
    await app.close();
  }
});

test('the official Douyin pane follows its account and grants only opted-in site notifications', async ({}, testInfo) => {
  const project = process.cwd();
  const app = await _electron.launch({ args: [project], cwd: project, env: {
    ...process.env, ZT_PUBLISHER_DATA_DIR: testInfo.outputPath('embedded'), ZT_DOUYIN_MESSAGE_FIXTURE: '1',
    ZT_WORKER_SCRIPT: path.join(project, 'tests', 'comment_fixture.py'),
  } });
  try {
    const page = await app.firstWindow();
    const state = await page.evaluate(() => window.publisher.request<State>('state'));
    const ids = state.bindings.filter(binding => binding.platform === 'douyin').map(binding => binding.id);
    await app.evaluate(({ session }, bindingIds) => {
      for (const id of bindingIds) {
        session.fromPartition(`persist:relayfold-douyin-pane-${id}`).protocol.handle('https', () =>
          new Response('<meta charset="utf-8"><title>抖音页面测试</title><button>官方页面测试</button>', {
            headers: { 'Content-Type': 'text/html; charset=utf-8' },
          }));
      }
    }, ids);
    await page.getByRole('button', { name: '消息', exact: true }).click();
    await page.getByRole('button', { name: '在 Relayfold 中打开' }).click();
    await expect(page.getByText('抖音网页已加载。', { exact: true })).toHaveCount(1);
    const check = () => app.evaluate(async ({ BrowserWindow, webContents }) => {
      const guest = webContents.getAllWebContents().find(contents => contents.getURL() === 'https://www.douyin.com/');
      const count = BrowserWindow.getAllWindows()[0].contentView.children.length;
      if (!guest) return { count, permissions: null };
      const permissions = await guest.executeJavaScript(
        '({ notifications: Notification.permission, bridge: typeof window.publisher, node: typeof require })',
      );
      return { count, permissions };
    });
    const alerts = page.getByRole('checkbox', { name: '允许网页通知' });
    expect(await check()).toMatchObject({ count: 1, permissions: { notifications: 'denied', bridge: 'undefined', node: 'undefined' } });
    await alerts.check();
    await expect.poll(check).toMatchObject({ count: 1, permissions: { notifications: 'granted' } });
    await page.getByRole('button', { name: '账号 B', exact: true }).click();
    await expect(page.getByRole('button', { name: '在 Relayfold 中打开' })).toBeVisible();
    await expect.poll(check).toEqual({ count: 0, permissions: null });
    await page.getByRole('button', { name: '在 Relayfold 中打开' }).click();
    await expect(page.getByText('抖音网页已加载。', { exact: true })).toHaveCount(1);
    await expect(alerts).not.toBeChecked();
    await expect.poll(check).toMatchObject({ count: 1, permissions: { notifications: 'denied' } });
    await page.getByRole('button', { name: '返回工作台' }).click();
    await expect.poll(check).toEqual({ count: 0, permissions: null });
  } finally {
    await app.close();
  }
});
