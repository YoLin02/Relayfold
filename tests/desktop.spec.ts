import path from 'node:path';
import { mkdir, readdir, readFile, writeFile } from 'node:fs/promises';
import { _electron, expect, test, type Page } from '@playwright/test';
import type { Binding, State } from '../src/types';

const project = process.cwd();

async function chooseOption(page: Page, field: string, option: string) {
  await page.getByRole('combobox', { name: field, exact: true }).click();
  await page.getByRole('listbox').getByRole('option', { name: option, exact: true }).click();
}

test('two account groups survive restart and a running batch keeps its original browser sessions', async ({}, testInfo) => {
  const dataDir = testInfo.outputPath('local-data');
  await mkdir(dataDir, { recursive: true });
  const video = path.join(dataDir, 'fixture.mp4');
  const pictures = [path.join(dataDir, 'picture-a.png'), path.join(dataDir, 'picture-b.jpg')];
  const covers = [path.join(dataDir, 'common-cover.png'), path.join(dataDir, 'dy-cover.png')];
  await writeFile(video, 'Fixture media for the local test only.');
  for (const picture of [...pictures, ...covers]) await writeFile(picture, 'Fixture image for the local test only.');
  const launch = () => _electron.launch({ args: [project], cwd: project, env: {
    ...process.env, ZT_PUBLISHER_DATA_DIR: dataDir, ZT_WORKER_SCRIPT: path.join(project, 'tests', 'fixture_worker.py'),
  } });
  let app = await launch();
  try {
    let page = await app.firstWindow();
    page.on('pageerror', error => { throw error; });
    await expect(page.getByRole('heading', { name: '新建发布', exact: true })).toBeVisible();
    const brand = page.locator('[data-sidebar="header"] [data-slot="workspace-brand"]');
    await expect(brand.getByText('Relayfold', { exact: true })).toBeVisible();
    await expect.poll(() => brand.locator('img').evaluate(icon => icon.complete && icon.naturalWidth > 0)).toBe(true);
    await expect(page.getByText('本地执行服务已连接', { exact: true })).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath('publish.png') });
    await page.getByRole('button', { name: '平台账号', exact: true }).click();
    const category = page.getByRole('tablist', { name: '平台内容分类' });
    await category.getByRole('tab', { name: '视频' }).click();
    await expect(page.getByRole('article', { name: '知乎', exact: true })).toHaveCount(0);
    await expect(page.getByRole('article', { name: '哔哩哔哩', exact: true })).toBeVisible();
    await category.getByRole('tab', { name: '图文' }).click();
    await expect(page.getByRole('article', { name: '知乎', exact: true })).toBeVisible();
    await expect(page.getByRole('article', { name: '哔哩哔哩', exact: true })).toHaveCount(0);
    await category.getByRole('tab', { name: '全部' }).click();

    for (const group of ['A', 'B']) {
      const groupButton = page.getByRole('button', { name: new RegExp(`账号 ${group}$`) });
      await groupButton.click();
      await expect(groupButton).toHaveAttribute('aria-pressed', 'true');
      for (const platform of ['抖音', '小红书']) {
        await page.getByRole('article', { name: platform, exact: true }).getByRole('button', { name: '绑定账号' }).click();
        const dialog = page.getByRole('dialog');
        await expect(dialog.getByText(`账号 ${group}`, { exact: true })).toBeVisible();
        await dialog.getByRole('button', { name: '打开扫码窗口', exact: true }).click();
        await dialog.getByLabel('账号昵称或备注').fill(`${platform} ${group}`);
        await dialog.getByRole('button', { name: '确认绑定' }).click();
        await expect(dialog).toBeHidden();
        await expect(page.getByText(`${platform} ${group}`, { exact: true })).toBeVisible();
      }
    }
    await page.screenshot({ path: testInfo.outputPath('accounts.png') });
    const initial = await page.evaluate(() => window.publisher.request<State>('state'));
    expect(initial.platforms).toHaveLength(26);
    expect(initial.bindings).toHaveLength(52);
    expect(initial.bindings.filter(b => b.login_status === 'ready')).toHaveLength(4);

    await app.close();
    app = await launch();
    page = await app.firstWindow();
    await expect(page.getByRole('button', { name: /账号 B$/ })).toHaveAttribute('aria-pressed', 'true');
    await page.getByRole('button', { name: '平台账号', exact: true }).click();
    for (const group of ['B', 'A']) {
      await page.getByRole('button', { name: new RegExp(`账号 ${group}$`) }).click();
      await expect(page.getByText('会话已保存', { exact: true })).toHaveCount(2);
      for (const platform of ['抖音', '小红书']) {
        const card = page.locator('.account-card').filter({ hasText: `${platform} ${group}` });
        await card.getByRole('button', { name: `管理${platform}`, exact: true }).click();
        await page.getByRole('menuitem', { name: '检查登录', exact: true }).press('Enter');
        await expect(page.getByRole('status').getByText(`${platform} · ${platform} ${group} 登录有效。`)).toBeVisible();
        await expect(card.getByText('已绑定', { exact: true })).toBeVisible();
      }
    }

    const saved = await page.evaluate(() => window.publisher.request<State>('state'));
    expect(saved.bindings.map(b => b.id)).toEqual(initial.bindings.map(b => b.id));
    const a = saved.groups.find(group => group.name === '账号 A')!;
    const b = saved.groups.find(group => group.name === '账号 B')!;
    const targetsA = saved.bindings.filter(binding => binding.group_id === a.id && binding.login_status === 'ready');
    const targetB = saved.bindings.find(binding => binding.group_id === b.id && binding.login_status === 'ready')!;
    await expect(page.evaluate(args => window.publisher.request('tasks.create', args), {
      group_id: a.id, binding_ids: [targetB.id], media_path: video, title: '禁止跨组', description: '', declaration: '无需添加自主声明',
    })).rejects.toThrow(/发布目标必须属于此发布组/);
    await expect(page.evaluate(args => window.publisher.request('tasks.create', args), {
      group_id: a.id, binding_ids: [targetsA[0].id], media_path: video, title: '禁止跨组覆盖', description: '',
      declaration: '无需添加自主声明', overrides: { [targetB.id]: { title: '另一个账号' } },
    })).rejects.toThrow(/未选中或不支持的账号/);

    await app.evaluate(({ dialog }, { video, covers }) => {
      let coverIndex = 0;
      dialog.showOpenDialog = async (_window, options) => ({
        canceled: false, filePaths: [options.title === '选择本地封面' ? covers[coverIndex++] : video],
      });
    }, { video, covers });
    await page.getByRole('button', { name: '新建发布', exact: true }).click();
    expect(await page.evaluate(file => window.publisher.mediaPreview(file), covers[0])).toBeNull();
    await page.getByRole('button', { name: '选择本地视频' }).click();
    await page.getByPlaceholder('输入视频标题').fill('本地分发验收');
    for (const platform of ['抖音', '小红书']) await page.getByRole('checkbox', { name: `选择${platform} ${platform} A` }).click();
    await page.getByPlaceholder('输入正文').fill('通用正文');
    await page.getByPlaceholder('用逗号分隔标签').fill('通用，旅行，旅行');
    await page.getByRole('button', { name: '通用封面', exact: true }).click();
    const editorTabs = page.getByRole('tablist', { name: '平台文案' });
    await editorTabs.getByRole('tab', { name: /^抖音/ }).click();
    await expect(page.getByRole('textbox', { name: '抖音标题' })).toHaveValue('本地分发验收');
    await page.getByRole('textbox', { name: '抖音标题' }).fill('抖音的专用标题');
    await page.getByRole('textbox', { name: '抖音正文' }).fill('');
    await page.getByRole('button', { name: '移除标签 通用' }).click();
    await page.getByRole('button', { name: '移除标签 旅行' }).click();
    await page.getByRole('textbox', { name: '抖音标签' }).fill('抖音专用');
    await page.getByRole('textbox', { name: '抖音标签' }).press('Enter');
    await page.getByRole('button', { name: '抖音封面', exact: true }).click();
    await chooseOption(page, '抖音作品声明', '无需添加自主声明');
    await editorTabs.getByRole('tab', { name: /^小红书/ }).click();
    await page.getByRole('textbox', { name: '小红书标题' }).fill('待撤销的标题');
    await page.getByRole('button', { name: '恢复通用小红书标题' }).click();
    await page.getByRole('button', { name: /账号 B$/ }).click();
    await expect(page.getByPlaceholder('输入视频标题')).toHaveValue('');
    await expect(page.getByRole('checkbox', { name: '选择小红书 小红书 B' })).not.toBeChecked();
    await page.getByRole('button', { name: /账号 A$/ }).click();
    await expect(page.getByPlaceholder('输入视频标题')).toHaveValue('本地分发验收');
    await page.getByRole('button', { name: '核对并群发' }).click();
    await expect(page.getByRole('dialog')).toContainText('抖音 · 抖音 A');
    await expect(page.getByRole('dialog')).toContainText('小红书 · 小红书 A');
    const douyinPreview = page.getByRole('region', { name: '抖音发布预览' });
    const xhsPreview = page.getByRole('region', { name: '小红书发布预览' });
    for (const value of ['抖音的专用标题', '无正文', '#抖音专用', 'dy-cover.png']) await expect(douyinPreview).toContainText(value);
    for (const value of ['本地分发验收', '通用正文', '#通用 #旅行', 'common-cover.png']) await expect(xhsPreview).toContainText(value);
    await page.screenshot({ path: testInfo.outputPath('batch-preview.png') });
    await page.getByRole('button', { name: '返回编辑' }).click();
    await expect(page.getByPlaceholder('输入视频标题')).toHaveValue('本地分发验收');
    await page.getByRole('button', { name: '核对并群发' }).click();
    await page.getByRole('button', { name: '确认并群发' }).click();
    await expect(page.getByRole('dialog')).toBeHidden();
    await page.getByRole('button', { name: /账号 B$/ }).click();
    await expect(page.getByText(/其他发布组有 .* 条任务在运行/)).toBeVisible();
    await expect(page.getByText('暂无发布记录')).toBeVisible();
    await page.getByRole('button', { name: /账号 A$/ }).click();
    await expect(page.getByText('已提交', { exact: true })).toHaveCount(2);
    const douyinRecord = page.getByRole('article', { name: '抖音 · 抖音 A' });
    await douyinRecord.getByRole('button', { name: '诊断记录' }).click();
    const diagnostics = page.getByRole('dialog', { name: '诊断记录' });
    await expect(diagnostics.getByText('隔离验收：已观测到模拟提交。')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(diagnostics).toBeHidden();
    await page.screenshot({ path: testInfo.outputPath('history.png') });
    const output = (await readFile(path.join(dataDir, 'fixture-deliveries.jsonl'), 'utf8')).trim().split('\n').map(line => JSON.parse(line));
    expect(output).toHaveLength(2);
    expect(output.map(row => row.actual).sort()).toEqual(targetsA.map((binding: Binding) => binding.id).sort());
    for (const row of output) expect(row).toMatchObject({ group: a.id, expected: row.actual, actual: row.actual, kind: 'video', files: 1 });
    const dy = output.find(row => row.actual === targetsA.find(binding => binding.platform === 'douyin')!.id);
    const xhs = output.find(row => row.actual === targetsA.find(binding => binding.platform === 'xiaohongshu')!.id);
    expect(dy).toMatchObject({ title: '抖音的专用标题', body: '', tags: ['抖音专用'] });
    expect(xhs).toMatchObject({ title: '本地分发验收', body: '通用正文', tags: ['通用', '旅行'] });
    expect(dy.paths).toEqual(xhs.paths);
    expect(path.basename(dy.cover)).toMatch(/dy-cover.png$/);
    expect(path.basename(xhs.cover)).toMatch(/common-cover.png$/);
    expect((await readdir(path.dirname(dy.paths[0]))).sort()).toEqual([dy.paths[0], dy.cover, xhs.cover].map(file => path.basename(file)).sort());

    await page.getByRole('button', { name: '平台账号', exact: true }).click();
    await page.getByRole('textbox', { name: '搜索平台' }).fill('知乎');
    await expect(page.locator('.account-card')).toHaveCount(1);
    await page.getByRole('button', { name: '绑定账号', exact: true }).click();
    const authorDialog = page.getByRole('dialog');
    await authorDialog.getByRole('button', { name: '打开登录窗口', exact: true }).click();
    await authorDialog.getByLabel('账号昵称或备注').fill('知乎 A');
    await authorDialog.getByRole('button', { name: '确认绑定' }).click();
    await expect(authorDialog).toBeHidden();

    await page.getByRole('button', { name: '新建发布', exact: true }).click();
    const kinds = page.getByRole('tablist', { name: '内容类型' });
    await expect(kinds.getByRole('tab')).toHaveCount(2);
    await kinds.getByRole('tab', { name: '图文', exact: true }).click();
    await chooseOption(page, '图文格式', '长文章');
    await expect(page.getByRole('checkbox', { name: /抖音|小红书/ })).toHaveCount(0);
    await page.getByPlaceholder('输入文章标题').fill('离线文章验收');
    await page.getByPlaceholder('输入正文').fill('这是一段测试正文。');
    await page.getByRole('checkbox', { name: '选择知乎 知乎 A' }).click();
    await page.getByRole('button', { name: '核对并群发' }).click();
    await page.getByRole('button', { name: '确认并群发' }).click();
    await expect(page.getByRole('article', { name: '知乎 · 知乎 A' }).getByText('已提交')).toBeVisible();

    await app.evaluate(({ dialog }, files) => {
      dialog.showOpenDialog = async () => ({ canceled: false, filePaths: files });
    }, pictures);
    await page.getByRole('button', { name: '新建发布', exact: true }).click();
    await page.getByRole('tab', { name: '图文', exact: true }).click();
    await chooseOption(page, '图文格式', '多图');
    await page.getByRole('button', { name: '选择本地图片' }).click();
    await expect(page.getByText('已选择 2 张图片')).toBeVisible();
    await page.getByPlaceholder('输入图文标题').fill('离线图文验收');
    await page.getByRole('checkbox', { name: '选择小红书 小红书 A' }).click();
    await page.getByRole('checkbox', { name: '选择抖音 抖音 A' }).click();
    await chooseOption(page, '通用封面', path.basename(pictures[0]));
    await editorTabs.getByRole('tab', { name: /^抖音/ }).click();
    await chooseOption(page, '抖音作品声明', '无需添加自主声明');
    await editorTabs.getByRole('tab', { name: /^小红书/ }).click();
    await chooseOption(page, '小红书封面', path.basename(pictures[1]));
    await page.getByRole('button', { name: '核对并群发' }).click();
    await page.getByRole('button', { name: '确认并群发' }).click();
    await expect(page.getByRole('article', { name: '抖音 · 抖音 A' }).filter({ hasText: '离线图文验收' }).getByText('已提交')).toBeVisible();
    await expect(page.getByRole('article', { name: '小红书 · 小红书 A' }).filter({ hasText: '离线图文验收' }).getByText('已提交')).toBeVisible();
    const finalOutput = (await readFile(path.join(dataDir, 'fixture-deliveries.jsonl'), 'utf8')).trim().split('\n').map(line => JSON.parse(line));
    expect(finalOutput.slice(-3).map(row => [row.kind, row.files])).toEqual([['article', 0], ['image', 2], ['image', 2]]);
    const [douyinImage, xhsImage] = finalOutput.slice(-2);
    expect(douyinImage.paths).toEqual(xhsImage.paths);
    expect(path.basename(douyinImage.cover)).toMatch(/picture-a.png$/);
    expect(path.basename(xhsImage.cover)).toMatch(/picture-b.jpg$/);
    expect(await readdir(path.dirname(douyinImage.paths[0]))).toHaveLength(2);

    await page.locator('[data-slot=sidebar-footer]').getByRole('button', { name: '设置', exact: true }).click();
    await expect(page.getByRole('heading', { name: '设置', exact: true })).toBeVisible();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    const appearance = page.getByRole('radiogroup', { name: '外观' });
    await expect(appearance.getByRole('radio', { name: '默认' })).toBeChecked();
    const themeRoot = page.locator('html');
    await appearance.getByRole('radio', { name: '青蓝' }).click();
    await expect(themeRoot).toHaveAttribute('data-accent-theme', 'cyan');
    await page.getByRole('button', { name: '取消预览' }).click();
    await expect(themeRoot).toHaveAttribute('data-accent-theme', 'neutral');
    await appearance.getByRole('radio', { name: '蓝紫' }).click();
    await expect(themeRoot).toHaveAttribute('data-accent-theme', 'violet');
    await page.getByRole('button', { name: '发布记录', exact: true }).click();
    await expect(themeRoot).toHaveAttribute('data-accent-theme', 'neutral');
    await page.getByRole('button', { name: '设置', exact: true }).click();
    await appearance.getByRole('radio', { name: '浅蓝' }).click();
    await expect(themeRoot).toHaveAttribute('data-accent-theme', 'sky');
    await page.getByRole('button', { name: '保存主题' }).click();
    await expect(page.getByText('已保存「浅蓝」主题。', { exact: true })).toBeVisible();
    const settings = page.getByRole('radiogroup', { name: '平台范围' });
    await expect(settings.getByRole('radio', { name: '国内平台' })).toBeChecked();
    await settings.getByRole('radio', { name: '国外平台' }).click();
    await page.getByRole('button', { name: '取消更改' }).click();
    await expect(settings.getByRole('radio', { name: '国内平台' })).toBeChecked();
    await settings.getByRole('radio', { name: '国外平台' }).click();
    await page.getByRole('button', { name: '保存设置' }).click();
    await expect(page.getByText('当前范围为国外平台。')).toBeVisible();
    await expect(settings.getByRole('radio', { name: '国外平台' })).toBeChecked();
    await expect(page.getByRole('button', { name: '返回工作台' })).toHaveCount(0);
    await page.getByRole('button', { name: '发布记录', exact: true }).click();
    await expect(page.getByRole('heading', { name: '发布记录' })).toBeVisible();
    await page.getByRole('button', { name: '平台账号', exact: true }).click();
    const search = page.getByRole('textbox', { name: '搜索平台' });
    await search.fill('抖音');
    await expect(page.locator('.account-card')).toHaveCount(0);
    await search.fill('TikTok');
    await expect(page.locator('.account-card')).toHaveCount(1);
    await page.locator('.account-card').getByRole('button', { name: '绑定账号' }).click();
    const tiktok = page.getByRole('dialog', { name: '绑定TikTok账号' });
    await tiktok.getByRole('button', { name: '打开登录窗口' }).click();
    await tiktok.getByLabel('账号昵称或备注').fill('TikTok A');
    await tiktok.getByRole('button', { name: '确认绑定' }).click();
    await expect(tiktok).toBeHidden();

    await app.close();
    app = await launch();
    page = await app.firstWindow();
    await expect(page.locator('html')).toHaveAttribute('data-accent-theme', 'sky');
    await expect(page.getByRole('checkbox', { name: '选择TikTok TikTok A' })).toBeVisible();
    await expect(page.getByRole('checkbox', { name: /抖音|小红书/ })).toHaveCount(0);
    await page.getByRole('tab', { name: '图文', exact: true }).click();
    await expect(page.getByRole('combobox', { name: '图文格式' })).toHaveText('长文章');
    await page.getByRole('button', { name: '设置', exact: true }).click();
    const restoredSettings = page.getByRole('radiogroup', { name: '平台范围' });
    await expect(restoredSettings.getByRole('radio', { name: '国外平台' })).toBeChecked();
    await restoredSettings.getByRole('radio', { name: '国内平台' }).click();
    await page.getByRole('button', { name: '保存设置' }).click();
    await expect(page.getByText('当前范围为国内平台。')).toBeVisible();
    await page.getByRole('button', { name: '新建发布', exact: true }).click();
    await expect(page.getByRole('combobox', { name: '图文格式' })).toHaveText('多图');
    await expect(page.getByRole('checkbox', { name: '选择抖音 抖音 A' })).toBeVisible();

    await page.getByRole('button', { name: '新建发布组' }).click();
    const createGroup = page.getByRole('dialog', { name: '新建发布组' });
    await createGroup.getByLabel('发布组名称').fill('账号 C');
    await createGroup.getByRole('button', { name: '创建发布组' }).click();
    await expect(page.getByRole('button', { name: '账号 C', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('heading', { name: '平台账号', exact: true })).toBeVisible();
    await chooseOption(page, '绑定状态', '已绑定');
    await expect(page.getByText('没有匹配的平台')).toBeVisible();
    await chooseOption(page, '绑定状态', '待绑定');
    await page.getByRole('article', { name: '抖音', exact: true }).getByRole('button', { name: '绑定账号' }).click();
    const newBinding = page.getByRole('dialog', { name: '绑定抖音账号' });
    await expect(newBinding.getByText('账号 C', { exact: true })).toBeVisible();
    await newBinding.getByRole('button', { name: '打开扫码窗口' }).click();
    await newBinding.getByLabel('账号昵称或备注').fill('抖音 C');
    await newBinding.getByRole('button', { name: '确认绑定' }).click();
    await expect(newBinding).toBeHidden();
    await page.getByRole('button', { name: '新建发布', exact: true }).click();
    await expect(page.getByRole('checkbox', { name: '选择抖音 抖音 C' })).toBeVisible();
    await expect(page.getByRole('checkbox', { name: '选择抖音 抖音 A' })).toHaveCount(0);

    const groupC = page.getByRole('button', { name: '账号 C', exact: true });
    await groupC.click({ button: 'right' });
    await page.getByRole('menuitem', { name: '重命名', exact: true }).click();
    const rename = page.getByRole('dialog', { name: '重命名发布组' });
    await expect(rename.getByLabel('发布组名称')).toHaveValue('账号 C');
    await rename.getByLabel('发布组名称').fill('样例账号组');
    await rename.getByRole('button', { name: '保存名称' }).click();
    const renamed = page.getByRole('button', { name: '样例账号组', exact: true });
    await expect(renamed).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('checkbox', { name: '选择抖音 抖音 C' })).toBeVisible();
    await renamed.click({ button: 'right' });
    await page.getByRole('menuitem', { name: '删除', exact: true }).click();
    const remove = page.getByRole('dialog', { name: '删除发布组' });
    await remove.getByRole('button', { name: '取消', exact: true }).click();
    await expect(renamed).toBeVisible();
    await renamed.click({ button: 'right' });
    await page.getByRole('menuitem', { name: '删除', exact: true }).click();
    await remove.getByRole('button', { name: '确认删除' }).click();
    await expect(renamed).toHaveCount(0);
    await expect(page.getByRole('button', { name: '账号 A', exact: true })).toHaveAttribute('aria-pressed', 'true');

    await page.keyboard.press('Control+k');
    const command = page.getByRole('dialog', { name: '搜索工作台' });
    await command.getByRole('combobox', { name: '搜索工作台' }).fill('抖音 B');
    await command.getByRole('option', { name: /抖音 · 抖音 B/ }).click();
    await expect(page.getByRole('button', { name: '账号 B', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('article', { name: '抖音', exact: true }).getByText('抖音 B')).toBeVisible();

    await page.getByRole('button', { name: '发布记录', exact: true }).click();
    await page.getByRole('button', { name: '账号 A', exact: true }).click();
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(480, 660));
    await expect.poll(() => page.evaluate(() => window.innerWidth)).toBeLessThan(500);
    await expect(page.locator('.workspace-window-header').getByText('Relayfold', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: '切换侧栏' }).click();
    await page.getByRole('dialog').getByRole('button', { name: '账号 B', exact: true }).click();
    await expect(page.getByRole('dialog')).toBeHidden();
    await expect(page.getByText('暂无发布记录')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(await page.evaluate(() => window.innerWidth));
    await page.getByRole('button', { name: '切换侧栏' }).click();
    await page.getByRole('dialog').getByRole('button', { name: '设置', exact: true }).click();
    await expect(page.getByRole('heading', { name: '设置', exact: true })).toBeVisible();
    await expect(page.getByRole('radiogroup', { name: '平台范围' })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(await page.evaluate(() => window.innerWidth));
  } finally {
    await app.close();
  }
});
