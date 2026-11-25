import path from 'node:path';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { _electron, expect, test } from '@playwright/test';
import type { State } from '../src/types';

const project = process.cwd();

test('a scheduled batch survives restart and runs from the tray with its original accounts', async ({}, testInfo) => {
  const root = testInfo.outputPath('data');
  await mkdir(root, { recursive: true });
  const media = path.join(root, 'scheduled.mp4');
  await writeFile(media, 'local scheduled media fixture');
  const launch = () => _electron.launch({ args: [project], cwd: project, env: {
    ...process.env, ZT_PUBLISHER_DATA_DIR: root, ZT_WORKER_SCRIPT: path.join(project, 'tests', 'fixture_worker.py'),
  } });
  let app = await launch();
  try {
    let page = await app.firstWindow();
    const initial = await page.evaluate(() => window.publisher.request<State>('state'));
    const [group, nextGroup] = initial.groups;
    const targets = initial.bindings.filter(binding => binding.group_id === group.id && ['douyin', 'xiaohongshu'].includes(binding.platform));
    expect(targets).toHaveLength(2);
    for (const binding of targets) {
      await page.evaluate(async binding => {
        await window.publisher.request('accounts.open', { id: binding.id });
        await window.publisher.request('accounts.confirm', { id: binding.id, label: binding.platform + ' A' });
      }, binding);
    }
    await app.evaluate(({ dialog }, file) => {
      dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [file] });
    }, media);
    await page.getByRole('button', { name: '选择本地视频' }).click();
    await page.getByPlaceholder('输入视频标题').fill('托盘定时验收');
    await page.getByRole('button', { name: '全选', exact: true }).click();
    await page.getByRole('tab', { name: /^抖音/ }).click();
    await page.getByRole('combobox', { name: '抖音作品声明' }).click();
    await page.getByRole('option', { name: '无需添加自主声明', exact: true }).click();
    await page.getByRole('button', { name: '核对并群发' }).click();
    const confirm = page.getByRole('dialog', { name: '核对发布内容' });
    await confirm.getByRole('radio', { name: '定时发布', exact: true }).click();
    await expect(confirm.getByLabel('发布时间', { exact: true })).not.toHaveValue('');
    await confirm.getByRole('button', { name: '确认定时发布' }).click();
    await expect(page.getByText('待定时', { exact: true })).toHaveCount(2);
    const waiting = await page.evaluate(() => window.publisher.request<State>('state'));
    const batchId = waiting.tasks[0].batch_id;
    expect(waiting.tasks.every(task => task.status === 'scheduled')).toBe(true);
    const operations = page.getByRole('button', { name: '更多操作', exact: true });
    await operations.click();
    await page.getByRole('menuitem', { name: '改期', exact: true }).click();
    await expect(page.getByRole('dialog', { name: '改期定时发布' }).getByLabel('发布时间', { exact: true })).not.toHaveValue('');
    await page.getByRole('button', { name: '保存时间' }).click();
    await expect(page.getByText('定时发布已改期。')).toBeVisible();
    await operations.click();
    await page.getByRole('menuitem', { name: '取消预约' }).click();
    await page.getByRole('dialog', { name: '取消定时发布' }).getByRole('button', { name: '取消', exact: true }).click();
    await expect(page.getByText('待定时', { exact: true })).toHaveCount(2);

    await app.close();
    app = await launch();
    page = await app.firstWindow();
    const reopened = await page.evaluate(() => window.publisher.request<State>('state'));
    expect(reopened.tasks.every(task => task.batch_id === batchId && task.status === 'scheduled')).toBe(true);
    await page.evaluate(async ({ batchId, group }) => {
      await window.publisher.request('groups.select', { id: group });
      await window.publisher.request('tasks.reschedule', { batch_id: batchId, scheduled_at: Math.floor(Date.now() / 1000) + 4 });
    }, { batchId, group: nextGroup.id });
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close());
    expect(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]?.isVisible())).toBe(false);
    await expect.poll(async () => {
      const state = await page.evaluate(() => window.publisher.request<State>('state'));
      return state.tasks.filter(task => task.status === 'submitted').length;
    }, { timeout: 35000 }).toBe(2);
    expect(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isVisible())).toBe(false);
    const verified = await page.evaluate(() => window.publisher.request<State>('state'));
    expect(verified.active_group_id).toBe(nextGroup.id);
    expect(verified.tasks.every(task => task.group_id === group.id)).toBe(true);
    const delivered = (await readFile(path.join(root, 'fixture-deliveries.jsonl'), 'utf8')).trim().split('\n').map(line => JSON.parse(line));
    expect(delivered).toHaveLength(2);
    expect(delivered.every(item => item.actual === item.expected && item.group === group.id)).toBe(true);
  } finally {
    await app.close();
  }
});
