import { ArrowRight, Download, FolderOpen, Link, Video } from 'lucide-react';
import { useId, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { errorMessage } from './model';
import type { PublisherWorkspace } from './use-workspace';
import { durationLabel, useMaterialSnapshot, type DownloadJob } from './video-materials';
import { ErrorNotice, WorkspaceHeading, WorkspaceSelect } from './workspace-ui';

type Resolution = { id: string; title: string; duration: number | null; resolutions: number[]; subtitles: string[] };
const downloadLabels = { queued: '排队中', downloading: '下载中', completed: '已完成', failed: '失败', canceled: '已取消' };

export function VideoDownloadPage({ workspace }: { workspace: PublisherWorkspace }) {
  const { snapshot, error: loadError } = useMaterialSnapshot();
  const [url, setUrl] = useState('');
  const [resolved, setResolved] = useState<Resolution>();
  const [height, setHeight] = useState('');
  const [language, setLanguage] = useState('');
  const [pending, setPending] = useState<'resolve' | 'download'>();
  const [error, setError] = useState('');
  const fieldId = useId();

  async function resolveLink() {
    setError('');
    setPending('resolve');
    setResolved(undefined);
    try {
      const metadata = await window.publisher.request<Resolution>('materials.resolve', { url });
      setResolved(metadata);
      setHeight(String(metadata.resolutions[0]));
      setLanguage('');
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setPending(undefined); }
  }

  async function download() {
    if (!resolved || !height) return;
    setError('');
    setPending('download');
    try { await window.publisher.request('materials.download', { id: resolved.id, height: Number(height), language }); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setPending(undefined); }
  }

  async function run(action: () => Promise<unknown>) {
    setError('');
    try { await action(); }
    catch (cause) { setError(errorMessage(cause)); }
  }

  function row(job: DownloadJob) {
    const asset = snapshot?.assets.find(item => item.id === job.asset_id);
    const active = job.status === 'queued' || job.status === 'downloading';
    return <li key={job.id} className="flex flex-wrap items-center gap-3 rounded-lg bg-muted/45 px-3 py-3">
      <div className="grid size-9 shrink-0 place-items-center rounded-md bg-background"><Video className="size-4 text-muted-foreground" /></div>
      <div className="min-w-40 flex-1 space-y-1">
        <div className="flex items-center gap-2">
          <p className="truncate font-medium" title={job.title}>{job.title}</p>
          <Badge variant={job.status === 'failed' ? 'destructive' : 'secondary'}>{downloadLabels[job.status]}</Badge>
        </div>
        <p className="break-words text-xs text-muted-foreground">
          {job.height}p{job.status === 'completed' ? (asset?.available ? ' · MP4' : ' · 文件不可用') : job.detail && ' · ' + job.detail}
        </p>
        {job.status === 'downloading' && job.progress !== null && <div className="flex items-center gap-2">
          <progress value={job.progress} max={100} aria-label={job.title + '下载进度'} className="h-1.5 w-full accent-primary" />
          <span className="text-xs tabular-nums text-muted-foreground">{Math.floor(job.progress)}%</span>
        </div>}
      </div>
      {job.status === 'completed' && asset?.available && <div className="flex flex-wrap gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={() => void run(() => window.publisher.materialAction('reveal', { id: asset.id }))}>
          <FolderOpen data-icon="inline-start" />打开文件夹
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={() => workspace.processDownloadedVideo(asset.id)}>
          送去提取字幕<ArrowRight data-icon="inline-end" />
        </Button>
      </div>}
      {active && <Button type="button" variant="ghost" size="sm"
        onClick={() => void run(() => window.publisher.request('materials.cancel', { id: job.id }))}>取消下载</Button>}
      {(job.status === 'failed' || job.status === 'canceled') && <Button type="button" variant="outline" size="sm"
        onClick={() => void run(() => window.publisher.request('materials.retry', { id: job.id }))}>重试</Button>}
    </li>;
  }

  return <>
    <div className="flex flex-wrap items-end justify-between gap-3">
      <WorkspaceHeading title="视频下载" description="从 B 站链接选择清晰度，下载为本地视频。" />
      <Button type="button" variant="outline" onClick={() => void run(() => window.publisher.materialAction('directory'))}>
        <FolderOpen data-icon="inline-start" />更改下载目录
      </Button>
    </div>
    {(error || loadError) && <ErrorNotice>{error || loadError}</ErrorNotice>}
    <Card className="workspace-panel">
      <CardHeader><CardTitle className="flex items-center gap-2"><Link className="size-4" />B 站链接</CardTitle>
        {snapshot && <CardDescription className="truncate" title={snapshot.directory}>{snapshot.directory}</CardDescription>}
      </CardHeader>
      <CardContent className="grid gap-3">
        <form className="flex gap-2" onSubmit={event => { event.preventDefault(); if (!pending && url.trim()) void resolveLink(); }}>
          <label htmlFor={fieldId} className="sr-only">B 站视频链接</label>
          <Input id={fieldId} value={url} placeholder="粘贴 B 站视频链接或分享文本" disabled={!!pending}
            onChange={event => { setUrl(event.target.value); setResolved(undefined); }} />
          <Button type="submit" disabled={!url.trim() || !!pending}>{pending === 'resolve' ? '正在解析…' : '解析链接'}</Button>
        </form>
        {resolved && <div className="flex flex-wrap items-center gap-3 rounded-lg bg-muted/45 p-3">
          <div className="min-w-44 flex-1">
            <p className="line-clamp-2 break-words font-medium">{resolved.title}</p>
            {resolved.duration !== null && <p className="text-xs text-muted-foreground">{durationLabel(resolved.duration)}</p>}
          </div>
          <WorkspaceSelect label="下载清晰度" value={height} onValueChange={setHeight} disabled={!!pending}
            options={resolved.resolutions.map(value => ({ value: String(value), label: value + 'p' }))} />
          {!!resolved.subtitles.length && <WorkspaceSelect label="可下载的字幕文件" value={language} onValueChange={setLanguage} disabled={!!pending}
            options={[{ value: '', label: '仅下载视频' }, ...resolved.subtitles.map(value => ({ value, label: value }))]} />}
          <Button type="button" disabled={!!pending} onClick={() => void download()}><Download data-icon="inline-start" />下载视频</Button>
        </div>}
      </CardContent>
    </Card>
    <Card className="workspace-panel">
      <CardHeader><CardTitle>下载记录</CardTitle></CardHeader>
      <CardContent>
        {snapshot?.downloads.length ? <ul className="grid gap-2">{snapshot.downloads.map(row)}</ul>
          : <p className="py-5 text-center text-sm text-muted-foreground">{snapshot ? '暂无下载记录' : '正在读取下载记录…'}</p>}
      </CardContent>
    </Card>
  </>;
}
