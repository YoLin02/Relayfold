import { execFileSync } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { _electron, expect, test } from '@playwright/test';
import type { State } from '../src/types';

const seed = `
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import time

sys.path.insert(0, str(Path.cwd() / "worker"))
from store import Store, new_id

root = Path(sys.argv[1])
store = Store(root / "publisher.sqlite3")
state = store.state()
group, other = state["groups"]
for account, title, date, appointment in (
    (group, "一月记录", sys.argv[2], None),
    (group, "二月记录", sys.argv[3], None),
    (group, "待发布记录", sys.argv[3], int(time()) + 7200),
    (other, "另一个账号的记录", sys.argv[2], None),
):
    binding = next(item["id"] for item in state["bindings"]
                   if item["group_id"] == account["id"] and item["platform"] == "douyin")
    store.bind(binding, "历史测试账号", "history-" + binding)
    batch = new_id()
    folder = root / "media" / batch
    folder.mkdir(parents=True)
    media = folder / "copy.mp4"
    shutil.copyfile(root / "original.mp4", media)
    store.enqueue(batch, account["id"], [binding], title, "", "无需添加自主声明", str(media), "copy.mp4",
                  scheduled_at=appointment)
    with store.db:
        store.db.execute("UPDATE batches SET created_at=? WHERE id=?",
                         (datetime.fromisoformat(date).astimezone(timezone.utc).isoformat(), batch))
        if appointment is None:
            store.db.execute("UPDATE tasks SET status='submitted' WHERE batch_id=?", (batch,))
store.db.close()
`;

test('history date ranges and individual deletion persist through the app', async ({}, testInfo) => {
  const project = process.cwd();
  const root = testInfo.outputPath('data');
  await mkdir(root, { recursive: true });
  const original = path.join(root, 'original.mp4');
  await writeFile(original, 'local fixture');
  execFileSync(process.env.ZT_PYTHON || 'python', ['-B', '-X', 'utf8', '-c', seed, root,
    new Date(2026, 0, 10, 23, 59, 59).toISOString(), new Date(2026, 1, 10, 12).toISOString(),
  ], { cwd: project });
  const executablePath = process.env.RELAYFOLD_TEST_EXE;
  const app = await _electron.launch({ ...(executablePath ? { executablePath } : { args: [project] }), cwd: project,
    env: { ...process.env, ZT_PUBLISHER_DATA_DIR: root } });
  try {
    const page = await app.firstWindow();
    await page.getByRole('button', { name: '发布记录', exact: true }).click();
    await expect(page.getByText('一月记录', { exact: true })).toBeVisible();
    await expect(page.getByText('二月记录', { exact: true })).toBeVisible();
    const scheduled = page.getByRole('article').filter({ hasText: '待发布记录' });
    await expect(scheduled.getByRole('button', { name: '诊断记录' })).toBeVisible();
    await expect(scheduled.getByRole('button', { name: '取消预约' })).toHaveCount(0);
    await scheduled.getByRole('button', { name: '更多操作' }).click();
    await expect(page.getByRole('menuitem', { name: '取消预约' })).toBeVisible();
    await expect(page.getByRole('menuitem', { name: '删除记录' })).toHaveCount(0);
    await page.keyboard.press('Escape');
    const state = await page.evaluate(() => window.publisher.request<State>('state'));
    const january = state.tasks.find(task => task.title === '一月记录')!;
    const copy = path.join(root, 'media', january.batch_id, 'copy.mp4');
    expect(await readFile(copy, 'utf8')).toBe('local fixture');

    await page.getByRole('combobox', { name: '创建时间' }).click();
    await page.getByRole('option', { name: '自定义日期' }).click();
    await page.getByLabel('开始日期').fill('2026-01-10');
    await page.getByLabel('结束日期').fill('2026-01-10');
    await expect(page.getByText('一月记录', { exact: true })).toBeVisible();
    await expect(page.getByText('二月记录', { exact: true })).toHaveCount(0);

    const januaryRow = page.getByRole('article').filter({ hasText: '一月记录' });
    await expect(januaryRow.getByRole('button', { name: '删除记录', exact: true })).toHaveCount(0);
    await januaryRow.getByRole('button', { name: '更多操作', exact: true }).click();
    const remove = page.getByRole('menuitem', { name: '删除记录', exact: true });
    await expect(remove).toHaveAttribute('data-variant', 'destructive');
    await remove.click();
    const dialog = page.getByRole('dialog', { name: '删除发布记录' });
    await dialog.getByRole('button', { name: '取消', exact: true }).click();
    await expect(page.getByText('一月记录', { exact: true })).toBeVisible();
    await januaryRow.getByRole('button', { name: '更多操作', exact: true }).click();
    await remove.click();
    await dialog.getByRole('button', { name: '确认删除' }).click();
    await expect(page.getByText('所选日期没有发布记录')).toBeVisible();
    await expect(readFile(copy, 'utf8')).rejects.toMatchObject({ code: 'ENOENT' });
    expect(await readFile(original, 'utf8')).toBe('local fixture');

    await page.getByRole('button', { name: '清除筛选' }).click();
    await expect(page.getByText('二月记录', { exact: true })).toBeVisible();
    await expect(page.getByText('一月记录', { exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: /账号 B$/ }).click();
    await expect(page.getByText('另一个账号的记录', { exact: true })).toBeVisible();
  } finally {
    await app.close();
  }
});
