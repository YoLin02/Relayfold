import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { _electron, expect, test, type Page } from '@playwright/test';
import type { State } from '../src/types';

function launch(dataDir: string) {
  const project = process.cwd();
  return _electron.launch({ args: [project], cwd: project, env: {
    ...process.env, ZT_PUBLISHER_DATA_DIR: dataDir, ZT_PRIVATE_MESSAGE_FIXTURE: '1',
    ZT_WORKER_SCRIPT: path.join(project, 'tests', 'comment_fixture.py'),
  } });
}

async function openInbox(page: Page) {
  await page.getByRole('button', { name: '消息', exact: true }).click();
  await page.getByRole('tab', { name: '私信', exact: true }).click();
}

test('private messages read the selected conversation, cache it and isolate drafts across groups and conversations', async ({}, testInfo) => {
  const dataDir = testInfo.outputPath('private-chat');
  let app = await launch(dataDir);
  try {
    let page = await app.firstWindow();
    await openInbox(page);
    const log = path.join(dataDir, 'private-message-opens.jsonl');
    await expect(readFile(log)).rejects.toMatchObject({ code: 'ENOENT' });
    await page.getByRole('button', { name: '同步私信', exact: true }).click();
    const first = page.getByRole('button', { name: /演示账号 A的一号预览/ });
    const second = page.getByRole('button', { name: /演示账号 A的二号预览/ });
    await expect(first).toBeVisible();
    await expect(page.getByRole('button', { name: /演示群聊/ })).toBeVisible();
    await expect(first.getByLabel('2 条未读')).toBeVisible();
    await first.click();
    const history = page.getByRole('region', { name: '聊天记录' });
    await expect(history.getByText('演示账号 A的会话 1', { exact: true })).toBeVisible();
    await expect(history.getByText('原账号发出的这条消息', { exact: true })).toBeVisible();
    await expect(first.getByLabel('2 条未读')).toHaveCount(0);
    await page.getByRole('button', { name: '加载更早消息' }).click();
    await expect(history.getByText('这是一条更早的聊天消息', { exact: true })).toBeVisible();
    const draft = page.getByRole('textbox', { name: '回复草稿' });
    await draft.fill('A 一号会话的本地草稿');
    await page.getByRole('button', { name: '保存草稿' }).click();
    await expect(page.getByText('草稿已保存到本机。', { exact: true })).toBeVisible();
    const state = await page.evaluate(() => window.publisher.request<State>('state'));
    const a = state.bindings.find(binding => binding.group_id === state.active_group_id && binding.platform === 'xiaohongshu')!;
    const cache = await readFile(path.join(dataDir, 'profiles', a.id, 'private-messages.dat'));
    expect(cache.includes(Buffer.from('本地草稿'))).toBe(false);

    await second.click();
    await expect(history.getByText('演示账号 A的会话 2', { exact: true })).toBeVisible();
    await expect(draft).toHaveValue('');
    await page.getByRole('textbox', { name: '搜索私信会话' }).fill('不存在的联系人');
    await expect(page.getByText('没有匹配的会话。')).toBeVisible();

    await page.getByRole('button', { name: '账号 B', exact: true }).click();
    await expect(page.getByRole('button', { name: '切换私信账号' })).toContainText('演示账号 B');
    await expect(history).toHaveCount(0);
    await expect(page.evaluate(bindingId => window.publisher.request<State>('state').then(state =>
      window.publisher.request('messages.snapshot', { group_id: state.active_group_id, binding_id: bindingId })), a.id))
      .rejects.toThrow('请在原发布组选择对应的小红书账号。');
    await page.getByRole('button', { name: '同步私信', exact: true }).click();
    await page.getByRole('button', { name: /演示账号 B的一号预览/ }).click();
    await expect(history.getByText('演示账号 B的会话 1', { exact: true })).toBeVisible();
    await expect(draft).toHaveValue('');

    await app.close();
    app = await launch(dataDir);
    page = await app.firstWindow();
    await openInbox(page);
    await page.getByRole('button', { name: '账号 A', exact: true }).click();
    await expect(page.getByRole('button', { name: /演示账号 A的一号预览/ })).toBeVisible();
    await writeFile(path.join(dataDir, 'no-personal-chat-data'), '');
    await page.getByRole('button', { name: '同步私信', exact: true }).click();
    await expect(page.getByText(/小红书单聊列表暂未加载/)).toBeVisible();
    await expect(page.getByRole('button', { name: /演示账号 A的一号预览/ })).toBeVisible();
    await writeFile(path.join(dataDir, 'no-private-message-entry'), '');
    await page.getByRole('button', { name: /演示账号 A的一号预览/ }).click();
    await expect(page.getByRole('region', { name: '聊天记录' }).getByText('这是一条更早的聊天消息')).toBeVisible();
    await expect(page.getByRole('textbox', { name: '回复草稿' })).toHaveValue('A 一号会话的本地草稿');
    await expect(page.getByText('当前账号的网页未显示「消息」入口，暂时无法同步私信。')).toBeVisible();
  } finally {
    await app.close();
  }
});

test('private messages stop if the logged-in web identity changes', async ({}, testInfo) => {
  const dataDir = testInfo.outputPath('private-mismatch');
  const app = await launch(dataDir);
  try {
    const page = await app.firstWindow();
    await openInbox(page);
    await writeFile(path.join(dataDir, 'different-private-account'), '');
    await page.getByRole('button', { name: '同步私信', exact: true }).click();
    await expect(page.getByText(/小红书网页身份与绑定账号不一致/)).toBeVisible();
    await expect(readFile(path.join(dataDir, 'private-message-opens.jsonl'))).rejects.toMatchObject({ code: 'ENOENT' });
  } finally {
    await app.close();
  }
});
