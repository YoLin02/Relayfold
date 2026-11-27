import { readFile, stat, writeFile } from 'node:fs/promises';
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
    await page.getByRole('button', { name: '消息', exact: true }).click();
    await page.getByRole('tab', { name: '完整评论', exact: true }).click();
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
    await expect(page.getByRole('status').filter({ has: page.locator('[data-slot=alert-description]') })).toContainText('演示账号 A · 正在向原评论提交回复。');
    await page.getByRole('button', { name: '账号 B', exact: true }).click();
    await expect(page.getByText('账号 B · 小红书', { exact: true })).toBeVisible();
    await expect(page.getByRole('status').filter({ has: page.locator('[data-slot=alert-description]') })).toContainText('演示账号 A · 小红书已确认收到回复。');
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

    await page.getByRole('button', { name: '消息', exact: true }).click();
    await page.getByRole('tab', { name: '完整评论', exact: true }).click();
    await page.getByRole('button', { name: '同步笔记', exact: true }).click();
    await page.getByRole('button', { name: '演示账号 A的站内笔记', exact: true }).click();
    await expect(page.getByText('演示账号 A的原评论')).toBeVisible();
    const notes = page.getByRole('region', { name: '笔记列表' });
    const comments = page.getByRole('region', { name: '评论列表' });
    const noteHeader = page.getByText('我的笔记', { exact: true });
    const commentHeader = page.getByText('演示账号 A的站内笔记', { exact: true }).last();
    const heading = page.getByRole('heading', { name: '消息', exact: true });
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

test('the full comment account persists and the received inbox keeps replies scoped to each account', async ({}, testInfo) => {
  const project = process.cwd();
  const dataDir = testInfo.outputPath('inbox-data');
  const launch = () => _electron.launch({ args: [project], cwd: project, env: {
    ...process.env, ZT_PUBLISHER_DATA_DIR: dataDir, ZT_COMMENT_MULTI_FIXTURE: '1',
    ZT_WORKER_SCRIPT: path.join(project, 'tests', 'comment_fixture.py'),
  } });
  let app = await launch();
  try {
    let page = await app.firstWindow();
    await page.getByRole('button', { name: '消息', exact: true }).click();
    await page.getByRole('tab', { name: '完整评论', exact: true }).click();
    const customGroup = '演示自定义组';
    await page.getByRole('button', { name: customGroup, exact: true }).click();
    const picker = page.getByRole('button', { name: '切换评论账号' });
    await picker.click();
    const dropdown = page.getByRole('dialog', { name: '切换评论账号' });
    const search = dropdown.getByRole('combobox', { name: '搜索账号昵称或编号' });
    await expect(search).toBeFocused();
    const triggerBox = (await picker.boundingBox())!;
    const dropdownBox = (await dropdown.boundingBox())!;
    expect(dropdownBox.y).toBeCloseTo(triggerBox.y + triggerBox.height + 4, 0);
    expect(dropdownBox.x + dropdownBox.width).toBeCloseTo(triggerBox.x + triggerBox.width, 0);
    await search.fill('没有这个账号');
    await expect(dropdown).toContainText('没有找到匹配的账号。');
    await search.press('Escape');
    await expect(picker).toBeFocused();
    await picker.click();
    await expect(search).toHaveValue('');
    await search.fill('小红书 2');
    await expect(dropdown.getByRole('option', { name: '同名账号 · 小红书 2', exact: true })).toBeVisible();
    await search.press('Enter');
    await expect(dropdown).toBeHidden();
    await expect(picker).toContainText('小红书 2');
    await picker.click();
    await page.getByRole('button', { name: '账号 B', exact: true }).click();
    await expect(dropdown).toBeHidden();
    await expect(picker).toContainText('演示账号 B');
    await page.getByRole('button', { name: customGroup, exact: true }).click();
    await expect(picker).toContainText('小红书 2');
    await page.getByRole('button', { name: '同步笔记', exact: true }).click();
    await expect(page.getByRole('button', { name: '同名账号 2的站内笔记', exact: true })).toBeVisible();

    await app.close();
    app = await launch();
    page = await app.firstWindow();

    await page.getByRole('button', { name: '消息', exact: true }).click();
    await expect(page.getByRole('tab', { name: '收到评论', exact: true })).toHaveAttribute('aria-selected', 'true');
    const state = await page.evaluate(() => window.publisher.request<State>('state'));
    const account = state.bindings.find(binding => binding.group_id === state.active_group_id && binding.slot === 2)!;
    expect(state.comment_accounts[state.active_group_id]).toBe(account.id);
    await page.getByRole('button', { name: '同步收到的评论', exact: true }).click();
    const list = page.getByRole('region', { name: '收件箱评论列表' });
    await expect(list.getByText('同名账号 1的原评论', { exact: true })).toBeVisible();
    await expect(list.getByText('同名账号 2的原评论', { exact: true })).toBeVisible();
    await expect(list.getByText('同名账号 2已在站内回复的评论', { exact: true })).toBeVisible();
    await page.getByRole('combobox', { name: '筛选收件箱账号' }).click();
    await page.getByRole('option', { name: '同名账号 · 小红书 2', exact: true }).click();
    await expect(list.getByText('同名账号 1的原评论', { exact: true })).toHaveCount(0);
    await list.getByText('同名账号 2的原评论', { exact: true }).click();
    const detail = page.getByRole('region', { name: '评论详情' });
    await detail.getByRole('button', { name: '回复', exact: true }).click();
    await detail.getByPlaceholder('输入回复').fill('谢谢你的留言！');
    await detail.getByRole('button', { name: '核对回复' }).click();
    const confirmation = page.getByRole('dialog', { name: '确认发送小红书回复' });
    await expect(confirmation).toContainText('同名账号 · 小红书 2');
    await expect(confirmation).toContainText(customGroup);
    await confirmation.getByRole('button', { name: '确认发送', exact: true }).click();
    await page.getByRole('button', { name: '账号 B', exact: true }).click();
    await expect(page.getByText('账号 B · 小红书', { exact: true })).toBeVisible();
    await expect(list.getByText('同名账号 2的原评论', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('status').filter({ has: page.locator('[data-slot=alert-description]') })).toContainText('同名账号 · 小红书 2 · 小红书已确认收到回复。');
    const deliveries = (await readFile(path.join(dataDir, 'comment-deliveries.jsonl'), 'utf8')).trim().split('\n');
    expect(deliveries.map(line => JSON.parse(line))).toEqual([{
      binding: account.id, request: { note_id: 'e'.repeat(24), target_comment_id: 'f'.repeat(24), content: '谢谢你的留言！' },
    }]);
  } finally {
    await app.close();
  }
});

test('comments survive navigation, directory migration and restart, and reminders open the received message', async ({}, testInfo) => {
  const project = process.cwd();
  const dataDir = testInfo.outputPath('cache-data');
  const destination = testInfo.outputPath('custom-cache');
  const launch = () => _electron.launch({ args: [project], cwd: project, env: {
    ...process.env, ZT_PUBLISHER_DATA_DIR: dataDir, ZT_COMMENT_CACHE_FIXTURE: '1',
    ZT_WORKER_SCRIPT: path.join(project, 'tests', 'comment_fixture.py'),
  } });
  let app = await launch();
  try {
    let page = await app.firstWindow();
    const open = (name: string) => page.getByRole('button', { name, exact: true }).click();
    const note = () => page.getByRole('button', { name: '演示账号 A的站内笔记', exact: true });
    const comment = () => page.getByText('演示账号 A的原评论', { exact: true });
    const cover = () => note().locator('img');
    await open('消息');
    await page.getByRole('tab', { name: '完整评论', exact: true }).click();
    await open('同步笔记');
    await expect.poll(() => cover().evaluate(img => (img as HTMLImageElement).naturalWidth)).toBe(1);
    await note().click();
    await expect(comment()).toBeVisible();
    await open('账号 B');
    await expect(comment()).toHaveCount(0);
    await open('账号 A');
    await expect(comment()).toBeVisible();
    await open('平台账号');
    await open('消息');
    await page.getByRole('tab', { name: '完整评论', exact: true }).click();
    await expect(comment()).toBeVisible();
    await expect.poll(() => cover().evaluate(img => (img as HTMLImageElement).naturalWidth)).toBe(1);

    await app.evaluate(({ dialog }, directory) => {
      dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [directory] });
    }, destination);
    await open('设置');
    await open('选择目录');
    await expect(page.getByText(destination, { exact: true })).toBeVisible();
    expect((await stat(path.join(destination, 'relayfold-comment-cache.sqlite3'))).size).toBeGreaterThan(0);
    await expect(stat(path.join(dataDir, 'comments', 'relayfold-comment-cache.sqlite3'))).rejects.toMatchObject({ code: 'ENOENT' });
    await app.close();
    app = await launch();
    page = await app.firstWindow();
    await open('消息');
    await page.getByRole('tab', { name: '完整评论', exact: true }).click();
    await expect(comment()).toBeVisible();
    await expect.poll(() => cover().evaluate(img => (img as HTMLImageElement).naturalWidth)).toBe(1);

    await page.getByRole('tab', { name: '收到评论', exact: true }).click();
    const inbox = page.getByRole('region', { name: '收件箱评论列表' });
    await open('同步收到的评论');
    await expect(inbox.getByText('演示账号 A的原评论', { exact: true })).toBeVisible();
    await open('账号 B');
    await expect(inbox.getByText('演示账号 A的原评论', { exact: true })).toHaveCount(0);
    await open('账号 A');
    await expect(page.getByRole('button', { name: '同步收到的评论' })).toBeEnabled();
    await expect(inbox.getByText('演示账号 A的原评论', { exact: true })).toBeVisible();

    await app.evaluate(({ Notification }) => {
      const notifications: Electron.Notification[] = [];
      Object.assign(globalThis, { relayfoldTestNotifications: notifications });
      Notification.prototype.show = function () { notifications.push(this); };
    });
    await open('设置');
    await page.getByRole('checkbox', { name: '小红书新评论提醒' }).check();
    await expect(page.getByText('已保存评论提醒设置。')).toBeVisible();
    await open('账号 B');
    await writeFile(path.join(dataDir, 'new-comment'), '');
    await expect(page.getByLabel('1 条未读评论')).toBeVisible();
    const notifications = () => app.evaluate(() =>
      (Reflect.get(globalThis, 'relayfoldTestNotifications') as Electron.Notification[]).length);
    await expect.poll(notifications).toBe(1);
    await app.evaluate(() => {
      const recorded = Reflect.get(globalThis, 'relayfoldTestNotifications') as Electron.Notification[];
      recorded[0].emit('click');
    });
    await expect(page.getByText('账号 A · 小红书', { exact: true })).toBeVisible();
    await expect(page.getByRole('region', { name: '评论详情' }).getByText('后台收到的新评论', { exact: true })).toBeVisible();
    await expect(page.getByLabel('1 条未读评论')).toHaveCount(0);
    await expect(page.getByRole('tab', { name: '收到评论', exact: true })).toHaveAttribute('aria-selected', 'true');
    const syncButton = page.getByRole('button', { name: '同步收到的评论' });
    await syncButton.click();
    await expect(syncButton).toBeEnabled();
    expect(await notifications()).toBe(1);
  } finally {
    await app.close();
  }
});

test('sync removes a confirmed deleted note even when the profile still lists it', async ({}, testInfo) => {
  const project = process.cwd();
  const dataDir = testInfo.outputPath('deleted-note-data');
  const launch = () => _electron.launch({ args: [project], cwd: project, env: {
    ...process.env, ZT_PUBLISHER_DATA_DIR: dataDir, ZT_COMMENT_CACHE_FIXTURE: '1',
    ZT_WORKER_SCRIPT: path.join(project, 'tests', 'comment_fixture.py'),
  } });
  let app = await launch();
  try {
    let page = await app.firstWindow();
    const open = (name: string) => page.getByRole('button', { name, exact: true }).click();
    const removed = () => page.getByRole('button', { name: '演示账号 A的站内笔记', exact: true });
    const kept = () => page.getByRole('button', { name: '慢笔记', exact: true });
    const comment = () => page.getByText('演示账号 A的原评论', { exact: true });
    const sync = () => page.getByRole('button', { name: '同步笔记', exact: true });
    await open('消息');
    await page.getByRole('tab', { name: '完整评论', exact: true }).click();
    await sync().click();
    await removed().click();
    await expect(comment()).toBeVisible();
    await expect(sync()).toBeEnabled();

    await writeFile(path.join(dataDir, 'delete-note'), '');
    await writeFile(path.join(dataDir, 'finish-slow-note'), '');
    await sync().click();
    await expect(removed()).toHaveCount(0);
    await expect(comment()).toHaveCount(0);
    await expect(kept()).toBeVisible();
    await expect(sync()).toBeEnabled();

    await app.close();
    app = await launch();
    page = await app.firstWindow();
    await open('消息');
    await page.getByRole('tab', { name: '完整评论', exact: true }).click();
    await expect(kept()).toBeVisible();
    await sync().click();
    await expect(sync()).toBeEnabled();
    await expect(removed()).toHaveCount(0);

    await page.getByRole('tab', { name: '收到评论', exact: true }).click();
    await open('同步收到的评论');
    await expect(page.getByRole('button', { name: '同步收到的评论' })).toBeEnabled();
    await expect(comment()).toHaveCount(0);
  } finally {
    await app.close();
  }
});

test('child replies load page by page and the same comment can be replied to again', async ({}, testInfo) => {
  const project = process.cwd();
  const dataDir = testInfo.outputPath('child-comments-data');
  const launch = () => _electron.launch({ args: [project], cwd: project, env: {
    ...process.env, ZT_PUBLISHER_DATA_DIR: dataDir, ZT_COMMENT_THREAD_FIXTURE: '1',
    ZT_WORKER_SCRIPT: path.join(project, 'tests', 'comment_fixture.py'),
  } });
  let app = await launch();
  try {
    let page = await app.firstWindow();
    const open = (name: string) => page.getByRole('button', { name, exact: true }).click();
    const parent = () => page.locator(`#comment-thread-${'f'.repeat(24)}`);
    const child = () => page.locator(`#comment-thread-${'3'.repeat(24)}`);
    const deliveryPath = path.join(dataDir, 'comment-deliveries.jsonl');
    await open('消息');
    await page.getByRole('tab', { name: '完整评论', exact: true }).click();
    await open('同步笔记');
    await open('演示账号 A的站内笔记');
    await expect(parent().getByText('演示账号 A的原评论', { exact: true })).toBeVisible();
    await open('展开 3 条回复');
    await expect(parent().getByText('站内已有作者回复', { exact: true })).toBeVisible();
    await open('加载更多回复');
    await expect(parent().getByText('第一批额外子评论', { exact: true })).toBeVisible();
    await expect(parent().getByText('第二批额外子评论', { exact: true })).toHaveCount(0);
    await open('加载更多回复');
    await expect(child().getByText('第二批额外子评论', { exact: true })).toBeVisible();
    await expect(child().getByText('回复 演示读者甲', { exact: true })).toBeVisible();
    await expect(parent().getByRole('button', { name: '加载更多回复' })).toHaveCount(0);

    await child().getByRole('button', { name: '回复', exact: true }).click();
    await page.getByPlaceholder('输入回复').fill('给子评论的回复');
    await open('核对回复');
    const confirmation = page.getByRole('dialog', { name: '确认发送小红书回复' });
    await expect(confirmation).toContainText('演示读者乙');
    await expect(readFile(deliveryPath)).rejects.toMatchObject({ code: 'ENOENT' });
    await confirmation.getByRole('button', { name: '确认发送', exact: true }).click();
    await expect(child().getByRole('button', { name: '继续回复', exact: true })).toBeEnabled();
    await open('收起回复');

    for (const [index, text] of ['给主评论的第一条', '给主评论的第二条'].entries()) {
      await parent().getByRole('button', { name: '继续回复', exact: true }).click();
      await expect(page.getByPlaceholder('输入回复')).toHaveValue('');
      await page.getByPlaceholder('输入回复').fill(text);
      await open('核对回复');
      await expect(confirmation).toContainText(text);
      await confirmation.getByRole('button', { name: '确认发送', exact: true }).click();
      await expect.poll(async () => (await readFile(deliveryPath, 'utf8')).trim().split('\n').length).toBe(index + 2);
      await expect(parent().getByRole('button', { name: '继续回复', exact: true })).toBeEnabled();
    }

    const delivered = (await readFile(deliveryPath, 'utf8')).trim().split('\n').map(line => JSON.parse(line));
    const state = await page.evaluate(() => window.publisher.request<State>('state'));
    const binding = state.bindings.find(item => item.group_id === state.active_group_id && item.platform === 'xiaohongshu');
    expect(delivered.map(row => row.binding)).toEqual([binding?.id, binding?.id, binding?.id]);
    expect(delivered.map(row => row.request.target_comment_id)).toEqual(['3'.repeat(24), 'f'.repeat(24), 'f'.repeat(24)]);

    await app.close();
    app = await launch();
    page = await app.firstWindow();
    await open('消息');
    await page.getByRole('tab', { name: '完整评论', exact: true }).click();
    await open('展开 3 条回复');
    await expect(child().getByText('第二批额外子评论', { exact: true })).toBeVisible();
    await expect(child().getByRole('button', { name: '继续回复', exact: true })).toBeEnabled();
  } finally {
    await app.close();
  }
});

test('received top-level comments and follow-ups are separate messages and link to complete comments', async ({}, testInfo) => {
  const project = process.cwd();
  const dataDir = testInfo.outputPath('received-data');
  const app = await _electron.launch({ args: [project], cwd: project, env: {
    ...process.env, ZT_PUBLISHER_DATA_DIR: dataDir, ZT_RECEIVED_COMMENT_FIXTURE: '1',
    ZT_WORKER_SCRIPT: path.join(project, 'tests', 'comment_fixture.py'),
  } });
  try {
    const page = await app.firstWindow();
    const inbox = page.getByRole('region', { name: '收件箱评论列表' });
    const detail = page.getByRole('region', { name: '评论详情' });
    const sync = page.getByRole('button', { name: '同步收到的评论', exact: true });
    await page.getByRole('button', { name: '消息', exact: true }).click();
    await expect(page.getByRole('tab', { name: '收到评论', exact: true })).toHaveAttribute('aria-selected', 'true');
    await sync.click();
    await expect(inbox.getByText('演示账号 A的原评论', { exact: true })).toBeVisible();
    await expect(inbox.getByText('新留言', { exact: true })).toBeVisible();
    await expect(page.getByLabel('1 条未读评论')).toHaveCount(0);
    await writeFile(path.join(dataDir, 'received-follow-up'), '');
    await sync.click();
    await expect(inbox.getByText('读者发来的追回复', { exact: true })).toHaveCount(1);
    await expect(inbox.getByText('追回复', { exact: true })).toBeVisible();
    await expect(page.getByLabel('1 条未读评论')).toBeVisible();
    await inbox.getByRole('button', { name: '回复 追回复读者', exact: true }).click();
    await expect(detail.getByText('读者发来的追回复')).toBeVisible();
    await expect(detail.getByRole('button', { name: /展开|收起/ })).toHaveCount(0);
    await expect(page.getByLabel('1 条未读评论')).toHaveCount(0);
    await detail.getByPlaceholder('输入回复').fill('回复这条追回复');
    await detail.getByRole('button', { name: '核对回复', exact: true }).click();
    const confirmation = page.getByRole('dialog', { name: '确认发送小红书回复' });
    await expect(confirmation).toContainText('读者发来的追回复');
    await confirmation.getByRole('button', { name: '确认发送', exact: true }).click();
    await expect(page.getByRole('status').filter({ has: page.locator('[data-slot=alert-description]') })).toContainText('小红书已确认收到回复。');
    const log = await readFile(path.join(dataDir, 'comment-deliveries.jsonl'), 'utf8');
    expect(JSON.parse(log.trim()).request.target_comment_id).toBe('c'.repeat(24));

    await sync.click();
    await expect(sync).toBeEnabled();
    await expect(inbox.getByText('读者发来的追回复', { exact: true })).toHaveCount(1);
    await page.getByRole('button', { name: '查看原帖评论' }).click();
    await expect(page.getByRole('tab', { name: '完整评论', exact: true })).toHaveAttribute('aria-selected', 'true');
    const thread = page.getByRole('region', { name: '评论列表', exact: true });
    await expect(thread.getByText('读者发来的追回复', { exact: true })).toBeVisible();
    await thread.getByRole('button', { name: '加载更多评论', exact: true }).click();
    await expect(thread.getByText('下一页一级评论', { exact: true })).toBeVisible();
    await expect(thread.getByText('广东', { exact: true })).toBeVisible();
  } finally {
    await app.close();
  }
});

test('the inbox aligns its rows, gives the list room, and opens the correct note before locating a reply', async ({}, testInfo) => {
  const project = process.cwd();
  const dataDir = testInfo.outputPath('inbox-layout-data');
  const app = await _electron.launch({ args: [project], cwd: project, env: {
    ...process.env, ZT_PUBLISHER_DATA_DIR: dataDir, ZT_RECEIVED_COMMENT_FIXTURE: '1',
    ZT_WORKER_SCRIPT: path.join(project, 'tests', 'comment_fixture.py'),
  } });
  try {
    const page = await app.firstWindow();
    const list = page.getByRole('region', { name: '收件箱评论列表' });
    const detail = page.getByRole('region', { name: '评论详情' });
    const followUp = list.getByText('读者发来的追回复', { exact: true });
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(1200, 760));
    await writeFile(path.join(dataDir, 'received-follow-up'), '');
    await writeFile(path.join(dataDir, 'hold-follow-up-location'), '');
    await page.getByRole('button', { name: '消息', exact: true }).click();
    await page.getByRole('button', { name: '同步收到的评论', exact: true }).click();
    await expect(followUp).toBeVisible();
    const fullWidth = (await list.boundingBox())!.width;
    const authorPositions = await list.locator('[data-slot="received-comment-author"]').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().x));
    expect(authorPositions.length).toBe(2);
    expect(authorPositions[0]).toBeCloseTo(authorPositions[1], 0);
    const replyPositions = await list.getByRole('button', { name: /^回复 / }).evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().right));
    expect(replyPositions[0]).toBeCloseTo(replyPositions[1], 0);
    await followUp.click();
    await expect(detail).toBeVisible();
    const listBox = (await list.boundingBox())!;
    const detailBox = (await detail.boundingBox())!;
    expect(listBox.width).toBeLessThan(fullWidth);
    expect(listBox.width).toBeGreaterThan(detailBox.width);
    expect(detailBox.height).toBeLessThan(listBox.height);

    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(620, 720));
    await expect(list).toBeHidden();
    await expect(detail).toBeVisible();
    await page.getByRole('button', { name: '返回消息列表' }).click();
    await expect(list).toBeVisible();
    await followUp.click();
    await page.getByRole('button', { name: '查看原帖评论' }).click();
    const comments = page.getByRole('region', { name: '评论列表', exact: true });
    await expect(page.getByRole('button', { name: /演示账号 A的站内笔记.*来自收件箱/ })).toHaveAttribute('aria-pressed', 'true');
    await expect(comments.getByText('演示账号 A的原评论', { exact: true })).toBeVisible();
    await expect(comments.getByText('正在定位这条回复…')).toBeVisible();
    await expect(comments.getByText('读者发来的追回复', { exact: true })).toHaveCount(0);
    await writeFile(path.join(dataDir, 'release-follow-up-location'), '');
    await expect(comments.getByText('读者发来的追回复', { exact: true })).toBeVisible();
  } finally {
    await app.close();
  }
});

test('the inbox sends another author’s note to the browser and keeps my notes in Relayfold', async ({}, testInfo) => {
  const project = process.cwd();
  const app = await _electron.launch({ args: [project], cwd: project, env: {
    ...process.env, ZT_PUBLISHER_DATA_DIR: testInfo.outputPath('external-note-data'), ZT_RECEIVED_EXTERNAL_FIXTURE: '1',
    ZT_WORKER_SCRIPT: path.join(project, 'tests', 'comment_fixture.py'),
  } });
  try {
    const page = await app.firstWindow();
    await app.evaluate(({ shell }) => {
      const opened: string[] = [];
      Object.assign(globalThis, { commentBrowserLinks: opened });
      shell.openExternal = async url => { opened.push(url); };
    });
    const inbox = page.getByRole('region', { name: '收件箱评论列表' });
    await page.getByRole('button', { name: '消息', exact: true }).click();
    await page.getByRole('button', { name: '同步收到的评论', exact: true }).click();
    await inbox.getByText('别人在自己原帖里回复了我', { exact: true }).click();
    await expect(page.getByRole('button', { name: '查看原帖评论', exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: '在网页查看原帖', exact: true }).click();
    const opened = () => app.evaluate(() => Reflect.get(globalThis, 'commentBrowserLinks') as string[]);
    const noteId = '4'.repeat(24);
    const commentId = '5'.repeat(24);
    const original = `https://www.xiaohongshu.com/explore/${noteId}?xsec_token=fixture&xsec_source=pc_notification`;
    await expect.poll(opened).toEqual([original]);
    await expect(page.getByRole('tab', { name: '收到评论', exact: true })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('region', { name: '评论详情' }).getByText('别人在自己原帖里回复了我')).toBeVisible();

    const rejection = await page.evaluate(async ({ noteId, commentId }) => {
      const state = await window.publisher.request<State>('state');
      const binding = state.bindings.find(item => item.group_id === state.active_group_id && item.platform === 'xiaohongshu')!;
      const destination = { group_id: binding.group_id, binding_id: binding.id, note_id: noteId, comment_id: commentId };
      const pending = await Promise.allSettled([
        window.publisher.request('comments.locate', destination),
        window.publisher.openCommentSource({ ...destination, note_id: 'd'.repeat(24) }),
      ]);
      return pending.map(result => result.status === 'rejected' ? String(result.reason) : '');
    }, { noteId, commentId });
    expect(rejection[0]).toContain('在小红书网页打开');
    expect(rejection[1]).toContain('找不到这条收到的评论');
    expect(await opened()).toEqual([original]);

    await inbox.getByText('演示账号 A的原评论', { exact: true }).click();
    await expect(page.getByRole('button', { name: '在网页查看原帖', exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: '查看原帖评论', exact: true }).click();
    await expect(page.getByRole('tab', { name: '完整评论', exact: true })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('region', { name: '评论列表', exact: true }).getByText('演示账号 A的原评论', { exact: true })).toBeVisible();
    expect(await opened()).toEqual([original]);
  } finally {
    await app.close();
  }
});
