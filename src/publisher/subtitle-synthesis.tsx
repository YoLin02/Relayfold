import { Captions, FileUp, Film, LoaderCircle, Play, Send } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { errorMessage, fileName } from './model';
import type { PublisherWorkspace } from './use-workspace';
import {
  captionBusy, renderBusy, type CaptionDocument, type ImportedSubtitle, type MaterialAsset, type MaterialSnapshot, type SynthesisSource,
} from './video-materials';
import { playFrom, VideoPreview } from './video-preview';
import { ErrorNotice, WorkspaceSelect } from './workspace-ui';

export function SubtitleSynthesis({ asset, snapshot, workspace }: {
  asset?: MaterialAsset; snapshot?: MaterialSnapshot; workspace: PublisherWorkspace;
}) {
  const selection = workspace.state.videoProcessing.subtitle;
  const chosenId = selection?.kind === 'saved' ? selection.id : '';
  const caption = chosenId ? snapshot?.captions[chosenId] : undefined;
  const options = snapshot?.assets.filter(item => snapshot.captions[item.id]?.count).map(item => ({
    value: item.id, label: item.title + ' · ' + snapshot.captions[item.id].count + ' 条',
  })) ?? [];
  const job = asset ? snapshot?.renders[asset.id] : undefined;
  const output = job?.output_id ? snapshot?.assets.find(item => item.id === job.output_id) : undefined;
  const [saved, setSaved] = useState<{ id: string; document: CaptionDocument }>();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const video = useRef<HTMLVideoElement>(null);
  const renderedVersion = renderBusy(job);
  const selectedDocument = saved?.id === chosenId && saved?.document.revision === caption?.revision ? saved?.document : undefined;
  const cues = selection?.kind === 'srt' ? selection.file.cues : selectedDocument?.cues ?? [];
  const source: SynthesisSource | undefined = selection?.kind === 'srt' ? { kind: 'srt', id: selection.file.id }
    : selectedDocument ? { kind: 'saved', id: chosenId, revision: selectedDocument.revision } : undefined;
  const sourceKey = source?.kind === 'srt' ? 'srt:' + source.id : source ? 'saved:' + source.id + ':' + source.revision : '';
  const durationMs = asset?.duration ? asset.duration * 1000 : 0;
  const withinVideo = cues.filter(cue => !durationMs || cue.startMs < durationMs);
  const exceedsVideo = !!durationMs && cues.some(cue => cue.endMs > durationMs + 100);
  const canRender = !!asset?.available && !!source && !!withinVideo.length && !renderedVersion && !pending && !captionBusy(caption);

  useEffect(() => {
    if (!chosenId) return;
    let current = true;
    void window.publisher.request<CaptionDocument>('materials.caption.get', { id: chosenId }).then(document => {
      if (current) setSaved({ id: chosenId, document });
    }).catch(cause => { if (current) setError(errorMessage(cause)); });
    return () => { current = false; };
  }, [chosenId, caption?.revision]);

  async function perform(action: 'import' | 'render' | 'cancel' | 'publish') {
    setPending(true);
    setError('');
    try {
      if (action === 'import') {
        const file = await window.publisher.materialAction<ImportedSubtitle | null>('import-srt');
        if (file) workspace.changeVideoProcessing({ subtitle: { kind: 'srt', file } });
      } else if (action === 'render' && asset && source) {
        await window.publisher.materialAction<boolean>('synthesize', { id: asset.id, source });
      } else if (action === 'cancel' && asset) {
        await window.publisher.request('materials.render.cancel', { id: asset.id });
      } else if (action === 'publish' && output) {
        const group = workspace.group?.id;
        const file = await window.publisher.materialAction<string>('publish', { id: output.id });
        workspace.useMaterial(file, group);
      }
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setPending(false); }
  }

  return <div className="grid min-h-0 items-start gap-4 lg:h-full lg:grid-cols-[minmax(0,.9fr)_minmax(0,1.2fr)]">
    <div className="min-w-0 lg:overflow-y-auto">
      {asset ? <VideoPreview key={asset.id} asset={asset} video={video} cues={cues} />
        : <Card className="workspace-panel"><CardContent className="grid min-h-40 place-content-center gap-2 text-center text-sm text-muted-foreground">
          <Film className="mx-auto size-5" />选择目标视频后可以预览字幕
        </CardContent></Card>}
    </div>
    <div className="grid min-h-0 min-w-0 gap-3 lg:max-h-full lg:overflow-y-auto">
      <Card className="workspace-panel">
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Captions className="size-4" />字幕来源</CardTitle>
          <CardDescription>选择已保存的字幕，或导入本地 SRT 文件。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <WorkspaceSelect label="已保存的字幕" value={chosenId} disabled={!options.length || pending}
              className="w-full max-w-72"
              options={[{ value: '', label: options.length ? '选择已保存的字幕' : '暂无已保存的字幕' }, ...options]}
              onValueChange={id => { setError(''); workspace.changeVideoProcessing({ subtitle: id ? { kind: 'saved', id } : undefined }); }} />
            <Button type="button" variant="outline" disabled={pending} onClick={() => void perform('import')}>
              <FileUp data-icon="inline-start" />导入 SRT
            </Button>
          </div>
          {selection?.kind === 'srt' && <p className="truncate text-sm" title={selection.file.name}>
            {selection.file.name} <span className="text-muted-foreground">· {cues.length} 条</span>
          </p>}
          {!!withinVideo.length && asset?.available && <Button type="button" variant="ghost" size="sm" className="w-fit"
            onClick={() => playFrom(video.current, withinVideo[0].startMs)}><Play data-icon="inline-start" />预览首条字幕</Button>}
          {exceedsVideo && <p className="text-sm text-muted-foreground">{withinVideo.length
            ? '部分字幕超出目标视频时长，成片会截到视频结束处。'
            : '字幕全部超出目标视频时长，请更换视频或字幕。'}</p>}
          {error && <ErrorNotice>{error}</ErrorNotice>}
        </CardContent>
        <CardFooter className="flex flex-wrap items-center justify-between gap-2 border-t pt-3">
          <span className="text-xs text-muted-foreground">MP4 · 白字黑边硬字幕</span>
          <Button type="button" disabled={!canRender} onClick={() => void perform('render')}>
            <Film data-icon="inline-start" />{renderedVersion ? '正在合成…' : '合成到视频'}
          </Button>
        </CardFooter>
      </Card>
      {job && <Card className="workspace-panel">
        <CardHeader><CardTitle>{job.status === 'ready' ? '合成完成' : '合成任务'}</CardTitle></CardHeader>
        <CardContent className="grid gap-2">
          {job.status === 'failed' ? <ErrorNotice>{job.detail}</ErrorNotice> : job.status === 'ready'
            ? <div className="grid gap-1"><p className="truncate text-sm" title={job.destination}>{fileName(job.destination)}</p>
              {sourceKey && sourceKey !== job.source_key && <p className="text-xs text-muted-foreground">此成片使用上一次合成选定的字幕。</p>}
              {!output?.available && <p className="text-xs text-muted-foreground">成片文件已移动或删除。</p>}
            </div>
            : <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
              {renderedVersion && <LoaderCircle className="size-3.5 animate-spin" />}{job.detail}
              {renderedVersion && job.progress !== null && ' · ' + job.progress + '%'}
            </p>}
          {renderedVersion && job.progress !== null && <progress value={job.progress} max={100} aria-label="字幕合成进度"
            className="h-1.5 w-full accent-primary" />}
        </CardContent>
        {(renderedVersion || output?.available) && <CardFooter className="justify-end">
          {renderedVersion ? <Button type="button" variant="outline" disabled={pending} onClick={() => void perform('cancel')}>取消合成</Button>
            : <Button type="button" disabled={pending || workspace.isBusy} onClick={() => void perform('publish')}>
              <Send data-icon="inline-start" />用合成视频发布
            </Button>}
        </CardFooter>}
      </Card>}
    </div>
  </div>;
}
