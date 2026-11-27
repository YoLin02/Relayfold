import { Check, ChevronLeft, ChevronRight, FileUp, Pencil, Play, RotateCcw } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { errorMessage } from './model';
import { captionBusy, type CaptionSummary } from './video-materials';
import { ErrorNotice, WorkspaceSelect } from './workspace-ui';

type Excerpt = { before: string; text: string; after: string };
type DifferenceKind = 'changed' | 'script-only' | 'transcript-only';
type Difference = {
  id: string; kind: DifferenceKind; script: Excerpt | null; transcript: Excerpt | null;
  startMs: number | null; endMs: number | null; cueIndex: number | null; nearby: boolean;
};
type Review = {
  id: string; name: string; revision: number; marked: string[]; error: string;
  result: { differences: Difference[]; counts: Record<DifferenceKind, number>; total: number } | null;
};
const labels: Record<DifferenceKind, string> = {
  changed: '文字不同', 'script-only': '仅原稿出现', 'transcript-only': '仅转写出现',
};
const pageSize = 12;

function displayTime(ms: number) {
  const seconds = Math.floor(ms / 1000);
  return [Math.floor(seconds / 60), seconds % 60].map(value => String(value).padStart(2, '0')).join(':')
    + '.' + String(Math.floor(ms % 1000 / 100));
}

function TextExcerpt({ title, excerpt }: { title: string; excerpt: Excerpt | null }) {
  let content: ReactNode = <span className="text-xs text-muted-foreground">无对应文字</span>;
  if (excerpt) {
    content = <>
      <span className="text-muted-foreground">{excerpt.before}</span>
      <mark className="rounded bg-amber-100 px-0.5 text-amber-950">{excerpt.text}</mark>
      <span className="text-muted-foreground">{excerpt.after}</span>
    </>;
  }
  return <div className="min-w-0 rounded-lg bg-muted/55 p-2.5">
    <p className="mb-1 text-xs font-medium text-muted-foreground">{title}</p>
    <p className="break-words whitespace-pre-wrap text-sm leading-relaxed">{content}</p>
  </div>;
}

export function ScriptReviewPanel({ assetId, revision, hasDraft, caption, hasTextTrack, hasAudio, onPlay, onEdit }: {
  assetId: string; revision: number; hasDraft: boolean;
  caption?: CaptionSummary; hasTextTrack: boolean; hasAudio: boolean;
  onPlay: (ms: number) => void; onEdit: (index: number) => void;
}) {
  const [review, setReview] = useState<Review | null>();
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const [kind, setKind] = useState('');
  const [status, setStatus] = useState('');
  const [pageNumber, setPageNumber] = useState(0);

  useEffect(() => {
    let active = true;
    void window.publisher.request<Review | null>('materials.script.review', { id: assetId }).then(data => {
      if (active) setReview(data);
    }).catch(cause => { if (active) { setReview(null); setError(errorMessage(cause)); } });
    return () => { active = false; };
  }, [assetId, revision]);

  async function importScript() {
    setPending(true);
    setError('');
    try {
      const result = await window.publisher.materialAction<Review | undefined>('import-word', { id: assetId });
      if (result) {
        setReview(result);
        setKind('');
        setStatus('');
        setPageNumber(0);
      }
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setPending(false); }
  }

  async function mark(item: Difference, reviewed: boolean) {
    if (!review) return;
    setPending(true);
    setError('');
    try {
      const marked = await window.publisher.request<string[]>('materials.script.mark', {
        id: assetId, scriptId: review.id, revision: review.revision, differenceId: item.id, reviewed,
      });
      setReview(current => current?.id === review.id && current.revision === review.revision ? { ...current, marked } : current);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setPending(false); }
  }

  const result = review?.revision === revision ? review.result : null;
  const marked = new Set(review?.marked ?? []);
  const items = result?.differences ?? [];
  const filtered = items.filter(item => (!kind || item.kind === kind)
    && (!status || marked.has(item.id) === (status === 'reviewed')));
  const page = Math.min(pageNumber, Math.max(0, Math.ceil(filtered.length / pageSize) - 1));
  const start = page * pageSize;
  const reviewedCount = items.filter(item => marked.has(item.id)).length;
  const waitingForSubtitles = captionBusy(caption) ? caption?.detail
    : hasTextTrack ? '提取文字字幕后即可核对。'
    : hasAudio ? '未发现可提取的文字字幕。可在左侧点「从语音生成」，完成后自动比对。'
    : '未发现可提取的文字字幕或可识别的音轨。';

  return <div className="grid gap-3">
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-muted/50 p-3">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium" title={review?.name}>{review?.name || 'Word 原稿'}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{review
          ? '按正文顺序比对，忽略大小写、空格和常见标点。'
          : '导入本地 .docx，与当前视频的转写字幕核对。'}</p>
      </div>
      <Button type="button" variant="outline" size="sm" disabled={pending || review === undefined} onClick={() => void importScript()}>
        <FileUp data-icon="inline-start" />{review ? '更换 Word' : '导入 Word'}
      </Button>
    </div>
    {hasDraft && <p className="text-xs text-muted-foreground">时间轴有未保存的修改，保存后会重新比对。</p>}
    {(error || review?.error) && <ErrorNotice>{error || review?.error}</ErrorNotice>}
    {review === undefined || (review && review.revision !== revision)
      ? <p role="status" className="py-5 text-center text-sm text-muted-foreground">正在读取核对结果…</p>
      : review && !result && !review.error && <p role="status" className="py-5 text-center text-sm text-muted-foreground">{waitingForSubtitles}</p>}
    {result && (result.total ? <>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>{result.total} 处差异</span>
        <span>已核对 {reviewedCount}</span>
        <div className="ml-auto flex flex-wrap gap-2">
          <WorkspaceSelect label="差异类型" value={kind} onValueChange={value => { setKind(value); setPageNumber(0); }}
            options={[{ value: '', label: '全部差异' }, ...Object.entries(labels).map(([value, label]) => ({
              value, label: label + ' · ' + result.counts[value as DifferenceKind],
            }))]} />
          <WorkspaceSelect label="核对状态" value={status} onValueChange={value => { setStatus(value); setPageNumber(0); }}
            options={[{ value: '', label: '全部状态' }, { value: 'pending', label: '待核对' }, { value: 'reviewed', label: '已核对' }]} />
        </div>
      </div>
      {result.total > items.length && <p className="text-xs text-muted-foreground">当前显示前 {items.length} 处差异，可分段核对剩余内容。</p>}
      {filtered.length ? <ol className="grid gap-3">
        {filtered.slice(start, start + pageSize).map(item => {
          const reviewed = marked.has(item.id);
          return <li key={item.id} className="grid gap-2 rounded-lg border border-border/70 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">{labels[item.kind]}</Badge>
              {reviewed && <Badge variant="outline">已核对</Badge>}
              {item.startMs !== null && <Button type="button" size="sm" variant="ghost" className="ml-auto h-7 font-mono"
                onClick={() => onPlay(item.startMs!)}><Play data-icon="inline-start" />
                {item.nearby ? '试听附近 ' : '试听 '}{displayTime(item.startMs)}
              </Button>}
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <TextExcerpt title="Word 原稿" excerpt={item.script} />
              <TextExcerpt title="转写字幕" excerpt={item.transcript} />
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              {item.cueIndex !== null && <Button type="button" size="sm" variant="ghost"
                onClick={() => onEdit(item.cueIndex!)}><Pencil data-icon="inline-start" />
                {item.nearby ? '查看相邻字幕' : '到时间轴修改'}
              </Button>}
              <Button type="button" size="sm" variant="outline" disabled={pending} onClick={() => void mark(item, !reviewed)}>
                {reviewed ? <RotateCcw data-icon="inline-start" /> : <Check data-icon="inline-start" />}
                {reviewed ? '取消标记' : '标记已核对'}
              </Button>
            </div>
          </li>;
        })}
      </ol> : <p className="py-6 text-center text-sm text-muted-foreground">没有符合筛选条件的差异。</p>}
      {filtered.length > pageSize && <div className="flex items-center justify-end gap-2 text-xs text-muted-foreground">
        {start + 1}–{Math.min(start + pageSize, filtered.length)} / {filtered.length}
        <Button type="button" variant="outline" size="icon-sm" aria-label="上一页差异" disabled={page === 0}
          onClick={() => setPageNumber(page - 1)}><ChevronLeft /></Button>
        <Button type="button" variant="outline" size="icon-sm" aria-label="下一页差异" disabled={start + pageSize >= filtered.length}
          onClick={() => setPageNumber(page + 1)}><ChevronRight /></Button>
      </div>}
    </> : <p role="status" className="rounded-lg bg-muted/45 py-6 text-center text-sm">原稿和字幕一致。</p>)}
  </div>;
}
