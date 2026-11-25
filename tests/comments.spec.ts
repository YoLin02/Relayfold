import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { _electron, expect, test } from '@playwright/test';
import type { State } from '../src/types';

test('notes from platform load independently and confirmed replies keep the original account after switching groups', async ({}, testInfo) => {
  const project = process.cwd();
  const dataDir = testInfo.outputPath('comment-data');
  const app = await _electron.launch({ args: [project], cwd: project, env: {
    ...process.env, ZT_PUBLISHER_DATA_DIR: dataDir, ZT_WORKER_SCRIPT: path.join(project, 'tests', 'comment_fixture.py'),
  } });
  try {
    const page = await app.firstWindow();
    await page.getByRole('button', { name: '评论', exact: true }).click();
    await page.getByRole('button', { name: '同步笔记', exact: true }).click();
    await page.getByRole('button', { name: '演示账号 A的站内笔记', exact: true }).click();
    await expect(page.getByText('演示账号 A的原评论', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: '回复', exact: true }).click();
    await page.getByRole('textbox', { name: '以「演示账号 A」回复' }).fill('谢谢你的留言！');
    await page.getByRole('button', { name: '核对回复', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: '确认发送小红书回复' });
    await expect(dialog).toContainText('演示账号 A');
    const deliveryPath = path.join(dataDir, 'comment-deliveries.jsonl');
    await expect(readFile(deliveryPath)).rejects.toMatchObject({ code: 'ENOENT' });
    const state = await page.evaluate(() => window.publisher.request<State>('state'));
    const original = state.bindings.find(binding => binding.group_id === state.active_group_id && binding.platform === 'xiaohongshu')!;
    await dialog.getByRole('button', { name: '确认发送', exact: true }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByRole('status')).toContainText('演示账号 A · 正在向原评论提交回复。');
    await page.getByRole('button', { name: '账号 B', exact: true }).click();
    await expect(page.getByText('账号 B · 小红书', { exact: true })).toBeVisible();
    await expect(page.getByRole('status')).toContainText('演示账号 A · 小红书已确认收到回复。');
    const deliveries = (await readFile(deliveryPath, 'utf8')).trim().split('\n').map(line => JSON.parse(line));
    expect(deliveries).toEqual([{
      binding: original.id, request: { note_id: 'e'.repeat(24), target_comment_id: 'f'.repeat(24), content: '谢谢你的留言！' },
    }]);
    await page.getByRole('button', { name: '同步笔记', exact: true }).click();
    await page.getByRole('button', { name: '演示账号 B的站内笔记', exact: true }).click();
    await expect(page.getByText('演示账号 B的原评论', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '回复', exact: true })).toBeEnabled();
  } finally {
    await app.close();
  }
});

test('scrolling starts below the title bar and each comments pane scrolls with its header fixed', async ({}, testInfo) => {
  const project = process.cwd();
  const app = await _electron.launch({ args: [project], cwd: project, env: {
    ...process.env, ZT_PUBLISHER_DATA_DIR: testInfo.outputPath('scroll-data'),
    ZT_WORKER_SCRIPT: path.join(project, 'tests', 'comment_fixture.py'), ZT_COMMENT_SCROLL_FIXTURE: '1',
  } });
  try {
    const page = await app.firstWindow();
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(1200, 650));
    const viewport = page.locator('[data-slot="workspace-viewport"]');
    const titlebar = page.locator('.workspace-window-header');
    await page.getByRole('button', { name: '平台账号', exact: true }).click();
    await expect(page.getByRole('heading', { name: '平台账号', exact: true })).toBeVisible();
    const titlebarBox = (await titlebar.boundingBox())!;
    expect((await viewport.boundingBox())!.y).toBeCloseTo(titlebarBox.y + titlebarBox.height, 0);
    await viewport.hover();
    await page.mouse.wheel(0, 350);
    await expect.poll(() => viewport.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
    expect(await titlebar.boundingBox()).toEqual(titlebarBox);

    await page.getByRole('button', { name: '评论', exact: true }).click();
    await page.getByRole('button', { name: '同步笔记', exact: true }).click();
    await page.getByRole('button', { name: '演示账号 A的站内笔记', exact: true }).click();
    await expect(page.getByText('演示账号 A的原评论')).toBeVisible();
    const notes = page.getByRole('region', { name: '笔记列表' });
    const comments = page.getByRole('region', { name: '评论列表' });
    const noteHeader = page.getByText('我的笔记', { exact: true });
    const commentHeader = page.getByText('演示账号 A的站内笔记', { exact: true }).last();
    const heading = page.getByRole('heading', { name: '评论', exact: true });
    const headers = await Promise.all([heading.boundingBox(), noteHeader.boundingBox(), commentHeader.boundingBox()]);
    const color = 'rgb(201, 201, 201) rgba(0, 0, 0, 0)';
    for (const pane of [viewport, notes, comments]) {
      expect(await pane.evaluate(el => getComputedStyle(el).scrollbarColor)).toBe(color);
    }

    await notes.hover();
    await page.mouse.wheel(0, 320);
    await expect.poll(() => notes.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
    expect(await comments.evaluate(el => el.scrollTop)).toBe(0);
    const noteScroll = await notes.evaluate(el => el.scrollTop);
    await comments.hover();
    await page.mouse.wheel(0, 320);
    await expect.poll(() => comments.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
    expect(await notes.evaluate(el => el.scrollTop)).toBe(noteScroll);
    expect(await viewport.evaluate(el => ({ offset: el.scrollTop, overflow: el.scrollHeight - el.clientHeight })))
      .toEqual({ offset: 0, overflow: 0 });
    expect(await Promise.all([heading.boundingBox(), noteHeader.boundingBox(), commentHeader.boundingBox()])).toEqual(headers);

    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(460, 570));
    await expect.poll(async () => (await comments.boundingBox())!.y > (await notes.boundingBox())!.y).toBe(true);
    for (const pane of [notes, comments]) {
      expect(await pane.evaluate(el => el.scrollHeight > el.clientHeight)).toBe(true);
      expect((await pane.boundingBox())!.height).toBeGreaterThan(50);
    }
    expect(await viewport.evaluate(el => el.scrollHeight - el.clientHeight)).toBe(0);
  } finally {
    await app.close();
  }
});
