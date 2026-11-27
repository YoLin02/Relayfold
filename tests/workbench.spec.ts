import { execFileSync } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { _electron, expect, test } from '@playwright/test';
import { groupSwitcher, openGroupMenu, selectGroup } from './workspace-navigation';

const seed = `
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, 'worker')
from store import Store, new_id

root = Path(sys.argv[1])
store = Store(root / 'publisher.sqlite3')
snapshot = store.state()
first, second = snapshot['groups']
primary = next(b for b in snapshot['bindings'] if b['group_id'] == first['id'] and b['platform'] == 'douyin')
other = next(b for b in snapshot['bindings'] if b['group_id'] == second['id'] and b['platform'] == 'douyin')
store.bind(primary['id'], '口播测试账号', 'test-primary')
store.bind(other['id'], '待验证账号', 'test-other')
with store.db:
    store.db.execute("UPDATE bindings SET login_status='attention' WHERE id=?", (other['id'],))

for offset, status, title in ((0, 'submitted', '今日口播'), (0, 'failed', '待处理样片'),
                              (0, 'draft_ready', '平台草稿'), (2, 'submitted', '往期口播'), (15, 'submitted', '月度样片')):
    batch = new_id()
    store.enqueue(batch, first['id'], [primary['id']], title, '', '无需添加自主声明',
                  str(root / 'fixture.mp4'), 'fixture.mp4')
    local_date = datetime.now() - timedelta(days=offset)
    created_at = local_date.replace(hour=12, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
    with store.db:
        store.db.execute('UPDATE batches SET created_at=? WHERE id=?', (created_at, batch))
        store.db.execute('UPDATE tasks SET status=? WHERE batch_id=?', (status, batch))
store.db.close()
`;

function dayLabel(offset: number) {
  const today = new Date();
  const date = new Date(today.getFullYear(), today.getMonth(), today.getDate() - offset);
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

test('workbench shows group-scoped activity and keeps group switching below the tool navigation', async ({}, testInfo) => {
  const root = testInfo.outputPath('local-data');
  await mkdir(root, { recursive: true });
  execFileSync(process.env.ZT_PYTHON || 'python', ['-B', '-X', 'utf8', '-c', seed, root], { cwd: process.cwd() });
  const app = await _electron.launch({ args: [process.cwd()], cwd: process.cwd(), env: { ...process.env, ZT_PUBLISHER_DATA_DIR: root } });
  try {
    const page = await app.firstWindow();
    await expect(page.getByRole('heading', { name: '工作台', exact: true })).toBeVisible();
    await expect(page.getByLabel('已连接账号数量')).toHaveText('1');
    const chart = page.getByRole('group', { name: '每日发布任务分布' });
    await expect(chart.getByRole('button')).toHaveCount(7);
    await chart.getByRole('button', { name: `${dayLabel(0)}，3 条任务`, exact: true }).click();
    await expect(page.getByText('需处理 1', { exact: true })).toBeVisible();
    await expect(page.getByText('已提交 1', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: '近 30 天', exact: true }).click();
    await expect(chart.getByRole('button')).toHaveCount(30);
    await expect(chart.getByRole('button', { name: `${dayLabel(15)}，1 条任务`, exact: true })).toBeVisible();
    await page.getByRole('button', { name: '近 7 天', exact: true }).click();
    await page.screenshot({ path: testInfo.outputPath('workbench.png') });

    const bounds = await groupSwitcher(page).boundingBox();
    expect(bounds!.x).toBeLessThan(30);
    expect(bounds!.y + bounds!.height).toBeGreaterThan(await page.evaluate(() => window.innerHeight - 30));
    await openGroupMenu(page);
    await page.screenshot({ path: testInfo.outputPath('account-menu.png') });
    await selectGroup(page, '账号 B');
    await expect(page.getByRole('heading', { name: '工作台', exact: true })).toBeVisible();
    await expect(page.getByLabel('已连接账号数量')).toHaveText('0');
    await expect(page.getByLabel('需重新验证数量')).toHaveText('1');
    await expect(page.getByText('近 7 天暂无发布任务', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: '打开脚本核对', exact: true }).click();
    await expect(page.getByRole('heading', { name: '脚本核对', exact: true })).toBeVisible();
    await expect(groupSwitcher(page)).toBeEnabled();
    await page.keyboard.press('Control+k');
    const search = page.getByRole('dialog', { name: '搜索工作台' });
    await search.getByRole('combobox').fill('账号 A');
    await search.getByRole('option', { name: '账号 A', exact: true }).click();
    await expect(groupSwitcher(page)).toHaveAccessibleName('切换发布组，当前 账号 A');
    await expect(page.getByRole('heading', { name: '脚本核对', exact: true })).toBeVisible();
  } finally {
    await app.close();
  }
});
