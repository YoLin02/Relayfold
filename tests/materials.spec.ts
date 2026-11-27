import { execFileSync } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { _electron, expect, test } from '@playwright/test';
import { selectGroup } from './workspace-navigation';

const completedDownload = [
  'import asyncio, sys',
  'from pathlib import Path',
  'sys.path.insert(0, "worker")',
  'from materials import Materials',
  'from store import Store',
  'root = Path(sys.argv[1])',
  'store = Store(root / "publisher.sqlite3")',
  'materials = Materials(store, root, lambda _: None)',
  'asset = asyncio.run(materials.add(sys.argv[2], title="下载样片", source="bilibili"))',
  `store.db.execute("INSERT INTO material_downloads (id,url,title,height,directory,status,progress,detail,asset_id,created_at) VALUES ('sample','','下载样片',360,?,'completed',100,'',?,'2026-01-01')",(str(root),asset["id"]))`,
  'store.db.commit()',
].join('\n');
const wordFixture = [
  'import sys',
  'from zipfile import ZipFile',
  'body = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>',
  '<w:p><w:r><w:t>已校对的</w:t></w:r><w:r><w:t>讲稿。</w:t></w:r></w:p>',
  '<w:p><w:r><w:t>跳到第二句。</w:t></w:r></w:p></w:body></w:document>"""',
  'with ZipFile(sys.argv[1], "w") as document: document.writestr("word/document.xml", body.encode())',
].join('\n');

function whitePixels(file: string, timestamp: string) {
  const rgb = execFileSync('ffmpeg', ['-v', 'error', '-ss', timestamp, '-i', file, '-frames:v', '1',
    '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'], { windowsHide: true, maxBuffer: 2 * 1024 * 1024 });
  let pixels = 0;
  for (let index = 0; index < rgb.length; index += 3) {
    if (rgb[index] > 175 && rgb[index + 1] > 175 && rgb[index + 2] > 175) pixels++;
  }
  return pixels;
}

test('download handoff and inline caption editing are separate from arbitrary local video and SRT synthesis', async ({}, testInfo) => {
  const project = process.cwd();
  const data = testInfo.outputPath('app-data');
  const media = testInfo.outputPath('media');
  await mkdir(data, { recursive: true });
  await mkdir(media, { recursive: true });
  const template = path.join(media, 'template.srt');
  const downloaded = path.join(media, 'downloaded.mp4');
  const downloadedSidecar = path.join(media, 'downloaded.srt');
  const local = path.join(media, 'another-video.mp4');
  const srt = path.join(media, '独立台词.srt');
  const exported = path.join(media, 'checked.srt');
  const script = path.join(media, '原稿.docx');
  const rendered = path.join(media, "独立合成's cut.mp4");
  await writeFile(template, '1\n00:00:00,200 --> 00:00:01,500\n下载视频第一句\n\n2\n00:00:02,000 --> 00:00:05,000\n跳到第二句\n', 'utf8');
  await writeFile(downloadedSidecar, '1\n00:00:00,200 --> 00:00:01,500\n外置字幕优先级测试\n', 'utf8');
  await writeFile(srt, '1\n00:00:00,500 --> 00:00:03,500\n来自独立台词文件\n', 'utf8');
  const videoArgs = ['-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=640x360:d=6',
    '-f', 'lavfi', '-i', 'sine=frequency=440:duration=6'];
  execFileSync('ffmpeg', [...videoArgs, '-i', template, '-map', '0:v', '-map', '1:a', '-map', '2:s',
    '-c:v', 'libx264', '-c:a', 'aac', '-c:s', 'mov_text', downloaded], { windowsHide: true });
  execFileSync('ffmpeg', [...videoArgs, '-c:v', 'libx264', '-c:a', 'aac', local], { windowsHide: true });
  execFileSync(process.env.ZT_PYTHON || 'python', ['-B', '-c', completedDownload, data, downloaded], { cwd: project, windowsHide: true });
  execFileSync(process.env.ZT_PYTHON || 'python', ['-B', '-c', wordFixture, script], { windowsHide: true });
  const originalLocal = await readFile(local);

  const app = await _electron.launch({ args: [project], cwd: project, env: { ...process.env, ZT_PUBLISHER_DATA_DIR: data } });
  try {
    const page = await app.firstWindow();
    await app.evaluate(({ dialog }, paths) => {
      let videoPrompts = 0;
      dialog.showOpenDialog = async (_window, options) => {
        const selected = options?.title === '导入 SRT 字幕' ? paths.srt
          : options?.title === '导入 Word 脚本' ? paths.script : paths.local;
        return { canceled: false, filePaths: [selected] };
      };
      dialog.showSaveDialog = async (_window, options) => ({
        canceled: false, filePath: options?.title === '保存合成视频'
          ? (++videoPrompts === 1 ? paths.local : paths.rendered) : paths.exported,
      });
    }, { local, rendered, srt, exported, script });

    await page.getByRole('button', { name: '视频下载', exact: true }).click();
    await expect(page.getByRole('heading', { name: '视频下载' })).toBeVisible();
    await expect(page.getByRole('tab', { name: '合成字幕' })).toHaveCount(0);
    await page.getByRole('button', { name: '送去提取字幕', exact: true }).click();
    await expect(page.getByRole('heading', { name: '提取字幕' })).toBeVisible();
    await expect(page.getByRole('combobox', { name: '选择待提取的视频' })).toContainText('下载样片');
    const extract = page.getByRole('region', { name: '提取字幕' });
    const extractionVideo = extract.locator('video');
    await expect.poll(() => extractionVideo.evaluate((element: HTMLVideoElement) => element.readyState)).toBeGreaterThanOrEqual(1);
    await expect(extract.getByRole('textbox', { name: '第 1 条字幕' })).toHaveCount(0);
    await expect(extract.getByText('检测到内封文字字幕，可直接提取。')).toBeVisible();
    await page.getByRole('button', { name: '脚本核对', exact: true }).click();
    const review = page.getByRole('region', { name: '脚本核对', exact: true });
    await review.getByRole('button', { name: '导入 Word' }).click();
    await expect(review.getByText('原稿.docx', { exact: true })).toBeVisible();
    await expect(review.getByText('已有字幕 · 2 条', { exact: true })).toBeVisible();
    await review.getByRole('button', { name: '返回字幕时间轴', exact: true }).click();
    await extract.getByRole('button', { name: '播放第 2 条', exact: true }).click();
    await expect(extract.getByLabel('实时字幕')).toHaveText('跳到第二句');
    expect(await extractionVideo.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThanOrEqual(2);
    await extractionVideo.evaluate((element: HTMLVideoElement) => element.pause());
    const first = extract.getByRole('textbox', { name: '第 1 条字幕', exact: true });
    await first.fill('已校对的台词');
    await selectGroup(page, '账号 B');
    await expect(page.getByRole('combobox', { name: '选择待提取的视频' })).toContainText('下载样片');
    await expect(first).toHaveValue('已校对的台词');
    await page.getByRole('button', { name: '合成字幕', exact: true }).click();
    await page.getByRole('button', { name: '提取字幕', exact: true }).click();
    await expect(first).toHaveValue('已校对的台词');
    await extract.getByRole('button', { name: '保存字幕' }).click();
    await expect(extract.getByText('字幕已保存。')).toBeVisible();
    await extract.getByRole('button', { name: '导出 SRT', exact: true }).click();
    await expect(extract.getByText('已导出 checked.srt')).toBeVisible();
    await expect(readFile(exported, 'utf8')).resolves.toContain('已校对的台词');

    await extract.getByRole('button', { name: '前往脚本核对', exact: true }).click();
    await expect(review.getByText('原稿.docx', { exact: true })).toBeVisible();
    await expect(review.getByText('1 处差异', { exact: true })).toBeVisible();
    await expect(review.getByText('讲稿', { exact: true })).toBeVisible();
    await expect(review.getByText('台词', { exact: true })).toBeVisible();
    await review.getByRole('button', { name: '试听 00:00.2' }).click();
    await expect(review.getByLabel('实时字幕')).toHaveText('已校对的台词');
    await review.locator('video').evaluate((element: HTMLVideoElement) => element.pause());
    await review.getByRole('button', { name: '标记已核对' }).click();
    await expect(review.getByText('已核对 1', { exact: true })).toBeVisible();
    await review.getByRole('button', { name: '返回字幕时间轴', exact: true }).click();
    await extract.getByRole('button', { name: '前往脚本核对', exact: true }).click();
    await expect(review.getByText('已核对 1', { exact: true })).toBeVisible();
    await review.getByRole('button', { name: '到时间轴修改' }).click();
    await expect(first).toBeFocused();
    await first.fill('已校对的讲稿');
    await extract.getByRole('button', { name: '保存字幕' }).click();
    await expect(extract.getByText('字幕已保存。')).toBeVisible();
    await extract.getByRole('button', { name: '前往脚本核对', exact: true }).click();
    await expect(review.getByText('原稿和字幕一致。', { exact: true })).toBeVisible();
    await review.getByRole('button', { name: '返回字幕时间轴', exact: true }).click();

    await extract.getByRole('button', { name: '用此字幕合成' }).click();
    const synthesis = page.getByRole('region', { name: '合成字幕' });
    await expect(synthesis.getByRole('combobox', { name: '已保存的字幕' })).toContainText('下载样片');
    await page.getByRole('button', { name: '导入本地视频', exact: true }).click();
    await expect(page.getByRole('combobox', { name: '选择目标视频' })).toContainText('another-video');
    await expect(synthesis.getByRole('combobox', { name: '已保存的字幕' })).toContainText('下载样片');
    await synthesis.getByRole('button', { name: '导入 SRT', exact: true }).click();
    await expect(synthesis.getByText(/独立台词\.srt/)).toBeVisible();
    const targetVideo = synthesis.locator('video');
    await expect.poll(() => targetVideo.evaluate((element: HTMLVideoElement) => element.readyState)).toBeGreaterThanOrEqual(1);
    await synthesis.getByRole('button', { name: '预览首条字幕', exact: true }).click();
    await expect(synthesis.getByLabel('实时字幕')).toHaveText('来自独立台词文件');
    await targetVideo.evaluate((element: HTMLVideoElement) => element.pause());

    const synthesize = synthesis.getByRole('button', { name: '合成到视频', exact: true });
    await synthesize.click();
    await expect(synthesis.getByText(/请.*新的文件名/)).toBeVisible();
    await synthesize.click();
    await expect(synthesis.getByText('合成完成', { exact: true })).toBeVisible();
    const mediaInfo = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-show_entries',
      'stream=codec_type,codec_name', '-of', 'json', rendered], { encoding: 'utf8', windowsHide: true }));
    expect(mediaInfo.streams).toEqual([
      { codec_name: 'h264', codec_type: 'video' },
      { codec_name: 'aac', codec_type: 'audio' },
    ]);
    expect(await readFile(local)).toEqual(originalLocal);
    expect(whitePixels(rendered, '0.8')).toBeGreaterThan(8);
    expect(whitePixels(rendered, '0.3')).toBe(0);
    await synthesis.getByRole('button', { name: '用合成视频发布', exact: true }).click();
    await expect(page.getByRole('heading', { name: '新建发布', exact: true })).toBeVisible();
    await expect(page.getByText(path.basename(rendered), { exact: true })).toBeVisible();
    await page.getByRole('button', { name: '提取字幕', exact: true }).click();
    await page.getByRole('combobox', { name: '选择待提取的视频' }).click();
    await page.getByRole('option', { name: 'another-video · 本地', exact: true }).click();
    await extract.getByRole('button', { name: '前往脚本核对', exact: true }).click();
    await review.getByRole('button', { name: '导入 Word' }).click();
    await expect(review.getByText('未发现可提取的文字字幕。可在左侧点「从语音生成」，完成后自动比对。')).toBeVisible();
    await expect(review.getByRole('button', { name: '从语音生成', exact: true })).toBeEnabled();
  } finally {
    await app.close();
  }
});
