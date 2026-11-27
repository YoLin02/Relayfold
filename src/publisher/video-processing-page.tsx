import { Captions, FolderOpen } from 'lucide-react';
import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { CaptionEditor } from './caption-editor';
import { errorMessage, fileName } from './model';
import { SubtitleSynthesis } from './subtitle-synthesis';
import type { PublisherWorkspace } from './use-workspace';
import { durationLabel, sourceLabels, useMaterialSnapshot, type MaterialAsset } from './video-materials';
import { ErrorNotice, WorkspaceHeading, WorkspaceSelect } from './workspace-ui';

export function SubtitleToolPage({ workspace }: { workspace: PublisherWorkspace }) {
  const { snapshot, error: loadError } = useMaterialSnapshot();
  const [pending, setPending] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState('');
  const processing = workspace.state.videoProcessing;
  const synthesis = workspace.state.view === 'subtitle-synthesis';
  const review = workspace.state.view === 'script-review';
  const id = synthesis ? processing.synthesizeId : processing.extractId;
  const asset = snapshot?.assets.find(item => item.id === id);
  const options = (snapshot?.assets ?? []).filter(item => item.available || item.id === id).map(item => ({
    value: item.id, label: item.title + ' · ' + sourceLabels[item.source] + (item.available ? '' : ' · 文件缺失'),
  }));
  const dimensions = asset?.width && asset?.height ? asset.width + ' × ' + asset.height : '';

  function selectVideo(id: string) {
    workspace.changeVideoProcessing(synthesis ? { synthesizeId: id } : { extractId: id });
  }

  const heading = synthesis ? ['合成字幕', '为目标视频添加已保存的字幕或本地 SRT。']
    : review ? ['脚本核对', '将 Word 原稿与视频字幕并排核对。']
    : ['提取字幕', '提取已有文字字幕或从音轨识别，再校对字幕时间轴。'];

  async function importVideo(paths?: string[]) {
    setError('');
    setPending(true);
    try {
      const selected = paths ?? await window.publisher.materialAction<string[]>('select');
      const results = await Promise.allSettled(selected.map(path => window.publisher.request<MaterialAsset>('materials.import', { path })));
      const first = results.find(result => result.status === 'fulfilled');
      if (first) selectVideo(first.value.id);
      const failures = results.flatMap((result, index) => result.status === 'rejected'
        ? [fileName(selected[index]) + ' · ' + errorMessage(result.reason)] : []);
      if (failures.length) setError(failures.join(' · '));
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setPending(false); }
  }

  return <>
    <WorkspaceHeading title={heading[0]} description={heading[1]} />
      <div className={cn('workspace-panel grid shrink-0 gap-2 rounded-xl bg-card p-3 sm:px-4', dragging && 'ring-2 ring-primary/50')}
        onDragOver={event => { event.preventDefault(); if (!pending) setDragging(true); }}
        onDragLeave={event => {
          if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) setDragging(false);
        }}
        onDrop={event => {
          event.preventDefault();
          setDragging(false);
          if (!pending) void importVideo(Array.from(event.dataTransfer.files, file => window.publisher.filePath(file)).filter(Boolean));
        }}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="mr-1 text-sm font-medium">{synthesis ? '目标视频' : review ? '待核对的视频' : '待提取的视频'}</span>
          <WorkspaceSelect label={synthesis ? '选择目标视频' : review ? '选择待核对的视频' : '选择待提取的视频'}
            value={asset?.id ?? ''} disabled={pending || !options.length} className="w-full max-w-72 sm:w-72"
            options={[{ value: '', label: '从下载记录或素材中选择' }, ...options]} onValueChange={selectVideo} />
          <Button type="button" variant="outline" disabled={pending} onClick={() => void importVideo()}>
            <FolderOpen data-icon="inline-start" />{pending ? '正在导入…' : '导入本地视频'}
          </Button>
          {asset && <div className="flex min-w-0 flex-wrap items-center gap-2">
            <Badge variant={asset.available ? 'secondary' : 'destructive'}>{asset.available ? sourceLabels[asset.source] : '文件缺失'}</Badge>
            <span className="text-xs text-muted-foreground">{[dimensions, durationLabel(asset.duration)].filter(Boolean).join(' · ')}</span>
          </div>}
        </div>
        {!asset && <p className="text-xs text-muted-foreground">也可以将视频拖到这里。</p>}
        {(error || loadError) && <ErrorNotice>{error || loadError}</ErrorNotice>}
      </div>
      <section aria-label={heading[0]} className="min-h-0 flex-1 overflow-y-auto pb-1 lg:overflow-hidden">
        {synthesis ? <SubtitleSynthesis asset={asset} snapshot={snapshot} workspace={workspace} />
          : asset ? <CaptionEditor key={asset.id} asset={asset} caption={snapshot?.captions[asset.id]} drafts={workspace.captionDrafts}
            review={review} onTimeline={() => workspace.changeView('subtitle-extract')}
            onReview={() => workspace.changeView('script-review')}
            onUseForSynthesis={() => {
              workspace.changeVideoProcessing({ synthesizeId: processing.synthesizeId || asset.id, subtitle: { kind: 'saved', id: asset.id } });
              workspace.changeView('subtitle-synthesis');
            }} />
          : <Card className="workspace-panel"><CardContent className="grid min-h-48 place-content-center gap-2 text-center text-sm text-muted-foreground">
            <Captions className="mx-auto size-5" />{review ? '选择视频后即可导入 Word 原稿。' : '选择视频后可提取已有字幕，或从语音生成字幕。'}
          </CardContent></Card>}
      </section>
  </>;
}
