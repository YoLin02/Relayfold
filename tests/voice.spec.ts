import { execFileSync } from 'node:child_process';
import { mkdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { _electron, expect, test } from '@playwright/test';

const runtime = process.env.RELAYFOLD_TTS_TEST_PYTHON;
const model = process.env.RELAYFOLD_TTS_TEST_MODEL;
const reference = process.env.RELAYFOLD_TTS_TEST_REFERENCE;
const legacy = process.env.RELAYFOLD_TTS_TEST_LEGACY;
const executablePath = process.env.RELAYFOLD_TTS_TEST_EXE;
const referenceText = '这是一段由系统生成的普通话测试音频，用来验证离线配音和音色保存。';
const script = '这段配音由已保存的音色重新生成。';

test('clone a local voice, preview and export its narration, and reopen the saved library', async ({}, testInfo) => {
  test.skip(!runtime || !model || !reference, 'Requires an existing Qwen 1.7B CUDA environment and a synthetic test recording');
  test.setTimeout(240000);
  const project = process.cwd();
  const data = testInfo.outputPath('app-data');
  const exported = testInfo.outputPath('测试配音.wav');
  await mkdir(data, { recursive: true });
  const env = { ...process.env, ZT_PUBLISHER_DATA_DIR: data };
  const launch = { executablePath, args: executablePath ? [] : [project], cwd: project, env };
  const ios = { model: model!, runtime: runtime!, reference: reference!, legacy, exported };
  const app = await _electron.launch(launch);
  try {
    await app.evaluate(({ dialog }, files) => {
      const selections: Record<string, string | undefined> = {
        '选择已下载的 TTS 模型目录': files.model,
        '选择已有配音环境的 python.exe': files.runtime,
        '选择参考录音': files.reference,
        '选择旧音色目录': files.legacy,
      };
      dialog.showOpenDialog = async (_window, options) => {
        const file = selections[options?.title ?? ''];
        return file ? { canceled: false, filePaths: [file] } : { canceled: true, filePaths: [] };
      };
      dialog.showSaveDialog = async () => ({ canceled: false, filePath: files.exported });
    }, ios);
    const page = await app.firstWindow();
    await page.getByRole('button', { name: '配音与音色', exact: true }).click();
    const panel = page.getByRole('main');
    await expect(panel.getByRole('button', { name: '下载 0.6B 模型' })).toBeVisible();
    await panel.getByRole('button', { name: '选择 1.7B 本机目录' }).click();
    await expect(panel.getByText('模型已就绪。')).toBeVisible({ timeout: 60000 });
    await panel.getByRole('button', { name: '选择已有环境' }).click();
    await expect(panel.getByText('配音环境已就绪。')).toBeVisible({ timeout: 60000 });
    await panel.getByRole('button', { name: '选择参考录音' }).click();
    await panel.getByRole('button', { name: '自动识别' }).click();
    await expect(panel.getByText('识别完成，请核对参考原文。')).toBeVisible({ timeout: 60000 });
    const original = panel.getByRole('textbox', { name: '参考录音原文' });
    await expect(original).toHaveValue(/普通话测试音频/);
    await original.fill(referenceText);
    await panel.getByRole('textbox', { name: '音色名称' }).fill('普通话测试音色');
    await panel.getByRole('button', { name: '克隆并保存' }).click();
    await expect(panel.getByText('音色已保存。')).toBeVisible({ timeout: 90000 });
    await panel.getByRole('button', { name: '重命名 普通话测试音色' }).click();
    await page.getByRole('textbox', { name: '新音色名称' }).fill('验收音色');
    await page.getByRole('button', { name: '保存名称' }).click();
    await expect(panel.getByRole('combobox', { name: '配音音色' })).toContainText('验收音色');
    await panel.getByRole('textbox', { name: '配音文案' }).fill(script);
    await panel.getByRole('button', { name: '生成配音', exact: true }).click();
    await expect(panel.getByText('配音已生成，可试听或导出。')).toBeVisible({ timeout: 90000 });
    await panel.getByRole('button', { name: '试听配音' }).click();
    const player = panel.locator('audio');
    await expect.poll(() => player.evaluate((element: HTMLAudioElement) => element.duration)).toBeGreaterThan(1);
    await expect.poll(() => player.evaluate((element: HTMLAudioElement) => element.currentTime)).toBeGreaterThan(0);
    await panel.getByRole('button', { name: '导出 WAV' }).click();
    await expect(panel.getByText('已导出 测试配音.wav')).toBeVisible();
    expect((await readFile(exported)).subarray(0, 4).toString()).toBe('RIFF');
    const stream = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-select_streams', 'a:0', '-show_entries',
      'stream=codec_name,sample_rate,channels', '-of', 'json', exported], { encoding: 'utf8', windowsHide: true }));
    expect(stream.streams).toEqual([{ codec_name: 'pcm_s24le', sample_rate: '24000', channels: 1 }]);
    if (legacy) {
      await panel.getByRole('button', { name: '导入旧音色' }).click();
      await expect(panel.getByText('旧音色已导入。')).toBeVisible({ timeout: 60000 });
      await expect(panel.getByText(path.basename(legacy), { exact: true })).toBeVisible();
    }
    await page.screenshot({ path: testInfo.outputPath('voice-workspace.png') });
  } finally {
    await app.close();
  }

  const reopened = await _electron.launch(launch);
  try {
    const page = await reopened.firstWindow();
    await page.getByRole('button', { name: '配音与音色', exact: true }).click();
    await expect(page.getByRole('button', { name: '重命名 验收音色' })).toBeVisible();
    await expect(page.getByText(script, { exact: true })).toBeVisible();
    await page.getByRole('button', { name: '删除 验收音色' }).click();
    await page.getByRole('button', { name: '确认删除' }).click();
    await expect(page.getByRole('button', { name: '重命名 验收音色' })).toHaveCount(0);
    await expect(page.getByText(script, { exact: true })).toBeVisible();
  } finally {
    await reopened.close();
  }
});
