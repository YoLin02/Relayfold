import { ChevronLeft, ChevronRight, Download, FileText, Film, LoaderCircle, Mic, Play } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { errorMessage, fileName } from './model';
import { ScriptReviewPanel } from './script-review-panel';
import { captionBusy, type CaptionDocument, type CaptionDraft, type CaptionSummary, type EditableCue, type MaterialAsset } from './video-materials';
import { playFrom, VideoPreview } from './video-preview';
import { ErrorNotice, WorkspaceSelect } from './workspace-ui';

const languages = [
  { value: 'auto', label: '自动识别' }, { value: 'zh', label: '中文' }, { value: 'en', label: '英语' },
  { value: 'ja', label: '日语' }, { value: 'ko', label: '韩语' }, { value: 'es', label: '西班牙语' },
  { value: 'fr', label: '法语' }, { value: 'de', label: '德语' },
];
const pageSize = 30;

function stamp(value: number) {
  const seconds = Math.floor(value / 1000);
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60]
    .map(part => String(part).padStart(2, '0')).join(':') + ',' + String(value % 1000).padStart(3, '0');
}

function milliseconds(stamp: string) {
  const match = /^(\d{2,3}):([0-5]\d):([0-5]\d)[,.](\d{3})$/.exec(stamp.trim());
  if (!match) return null;
  const [, h, m, s, ms] = match;
  return (Number(h) * 3600 + Number(m) * 60 + Number(s)) * 1000 + Number(ms);
}

function editable(document: CaptionDocument): EditableCue[] {
  return document.cues.map(cue => ({ start: stamp(cue.startMs), end: stamp(cue.endMs), text: cue.text }));
}

export function CaptionEditor({ asset, caption, drafts, onUseForSynthesis }: {
  asset: MaterialAsset; caption?: CaptionSummary; drafts: RefObject<Map<string, CaptionDraft>>; onUseForSynthesis: () => void;
}) {
  const [document, setDocument] = useState<CaptionDocument>();
  const [draft, setDraft] = useState<CaptionDraft | undefined>(() => drafts.current.get(asset.id));
  const [language, setLanguage] = useState('auto');
  const [trackId, setTrackId] = useState('');
  const [replace, setReplace] = useState(false);
  const [pending, setPending] = useState(false);
  const [page, setPage] = useState(0);
  const [rightTab, setRightTab] = useState('timeline');
  const [focusCue, setFocusCue] = useState<number>();
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const video = useRef<HTMLVideoElement>(null);
  const tracks = asset.subtitles.filter(track => track.convertible);
  const track = tracks.find(item => item.id === trackId) ?? tracks[0];
  const busy = captionBusy(caption);
  const revision = caption?.revision ?? 0;
  const base = useMemo(() => document ? editable(document) : [], [document]);
  const changed = !!draft && draft.revision === document?.revision;
  const cues = changed ? draft.cues : base;
  const first = page * pageSize;
  const previewCues = useMemo(() => cues.flatMap(cue => {
    const startMs = milliseconds(cue.start);
    const endMs = milliseconds(cue.end);
    return startMs != null && endMs != null && endMs > startMs ? [{ startMs, endMs, text: cue.text }] : [];
  }), [cues]);

  useEffect(() => {
    let active = true;
    void window.publisher.request<CaptionDocument>('materials.caption.get', { id: asset.id }).then(result => {
      if (active) setDocument(result);
    }).catch(cause => { if (active) setError(errorMessage(cause)); });
    return () => { active = false; };
  }, [asset.id, revision]);

  const focusEditor = useCallback((element: HTMLTextAreaElement | null) => {
    if (!element) return;
    const frame = requestAnimationFrame(() => {
      element.scrollIntoView({ block: 'nearest' });
      element.focus({ preventScroll: true });
      setFocusCue(undefined);
    });
    return () => cancelAnimationFrame(frame);
  }, []);

  function openCue(index: number) {
    setPage(Math.floor(index / pageSize));
    setFocusCue(index);
    setRightTab('timeline');
  }

  function discardDraft() {
    drafts.current.delete(asset.id);
    setDraft(undefined);
    setError('');
  }

  function edit(index: number, field: keyof EditableCue, value: string) {
    if (!document) return;
    const next = { revision: document.revision, cues: cues.map((cue, position) => position === index ? { ...cue, [field]: value } : cue) };
    drafts.current.set(asset.id, next);
    setDraft(next);
    setNotice('');
  }

  async function act(action: 'extract' | 'speech' | 'cancel' | 'save' | 'export') {
    setPending(true);
    setError('');
    setNotice('');
    try {
      if (action === 'export') {
        const file = await window.publisher.materialAction<string | null>('export-caption', { id: asset.id });
        if (file) setNotice('已导出 ' + fileName(file));
      } else if (action === 'cancel') {
        await window.publisher.request('materials.caption.cancel', { id: asset.id });
      } else if (action === 'save') {
        if (!document) return;
        const edited = cues.map((cue, index) => {
          const startMs = milliseconds(cue.start);
          const endMs = milliseconds(cue.end);
          if (startMs == null || endMs == null || endMs <= startMs) {
            throw new Error('请检查第 ' + (index + 1) + ' 条的时间，格式为 00:00:00,000。');
          }
          return { startMs, endMs, text: cue.text };
        });
        const result = await window.publisher.request<CaptionDocument>('materials.caption.save',
          { id: asset.id, revision: document.revision, cues: edited });
        discardDraft();
        setDocument(result);
        setNotice('字幕已保存。');
      } else {
        await window.publisher.request('materials.caption.start', { id: asset.id, mode: action, track: track?.id, language, replace });
        setReplace(false);
        setPage(0);
      }
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setPending(false); }
  }

  const canStart = asset.available && !busy && !pending && !!document && !changed && (!revision || replace);
  const readOnly = busy || pending;
  const canExport = !!cues.length && !changed && !readOnly && document?.revision === revision;
  const subtitleDetection = track
    ? (track.id.startsWith('stream:') ? '检测到内封文字字幕，可直接提取。' : '检测到同名文字字幕文件，可直接读取。')
    : asset.subtitles.length ? '检测到图像字幕轨，可从音轨生成文字字幕。' : '未检测到可提取的文字字幕轨。';

  return <div className="grid min-h-0 gap-4 lg:h-full lg:grid-cols-[minmax(0,.9fr)_minmax(0,1.2fr)]">
    <div className="min-w-0 space-y-3 lg:overflow-y-auto">
      <VideoPreview asset={asset} video={video} cues={previewCues} />
      <Card className="workspace-panel">
        <CardHeader><CardTitle>字幕来源</CardTitle><CardDescription>{subtitleDetection}</CardDescription></CardHeader>
        <CardContent className="grid gap-3">
          {track && <div className="flex flex-wrap items-center gap-2">
            <WorkspaceSelect label="选择字幕轨" value={track.id} onValueChange={setTrackId} disabled={readOnly}
              options={tracks.map(item => ({ value: item.id, label: item.label }))} />
            <Button type="button" size="sm" disabled={!canStart} onClick={() => void act('extract')}>
              <FileText data-icon="inline-start" />提取已有字幕
            </Button>
          </div>}
          {asset.has_audio !== false && <div className="flex flex-wrap items-center gap-2">
            <WorkspaceSelect label="语音语言" value={language} onValueChange={setLanguage} options={languages} disabled={readOnly} />
            <Button type="button" size="sm" variant={track ? 'outline' : 'default'} disabled={!canStart} onClick={() => void act('speech')}>
              <Mic data-icon="inline-start" />从语音生成
            </Button>
          </div>}
          {!track && asset.has_audio === false && <p className="text-xs text-muted-foreground">此视频没有可用的音轨或文本字幕。</p>}
          {!!revision && !busy && <label className="flex items-center gap-2 text-xs">
            <Checkbox checked={replace} onCheckedChange={value => setReplace(value === true)} disabled={changed || pending} />
            允许替换已保存字幕
          </label>}
          {busy && <div className="grid gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p role="status" className="flex items-center gap-2 text-xs"><LoaderCircle className="size-3.5 animate-spin" />
                {caption?.detail}{caption?.progress != null && ' · ' + caption.progress + '%'}</p>
              <Button type="button" size="sm" variant="ghost" disabled={pending} onClick={() => void act('cancel')}>取消处理</Button>
            </div>
            {caption?.progress != null && <progress value={caption.progress} max={100} aria-label="字幕处理进度"
              className="h-1.5 w-full accent-primary" />}
          </div>}
          {caption?.status === 'failed' && <ErrorNotice>{caption.detail}</ErrorNotice>}
          {caption?.status === 'canceled' && <p className="text-xs text-muted-foreground">{caption.detail}</p>}
        </CardContent>
      </Card>
    </div>
    <Card className="workspace-panel min-h-0 min-w-0 gap-0 lg:overflow-hidden">
      <Tabs value={rightTab} onValueChange={setRightTab} className="grid min-h-0 gap-0 lg:h-full lg:grid-rows-[auto_minmax(0,1fr)]">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <TabsList aria-label="字幕核对工具">
            <TabsTrigger value="timeline">时间轴</TabsTrigger>
            <TabsTrigger value="script">脚本核对</TabsTrigger>
          </TabsList>
          {!!cues.length && <Badge variant="secondary">{caption?.source === 'extract' ? '已有字幕' : '语音识别'} · {cues.length} 条</Badge>}
        </div>
      </CardHeader>
      <TabsContent value="timeline" className="min-h-0 grid-rows-[minmax(0,1fr)_auto] data-active:grid">
      <CardContent aria-label="字幕列表" className="min-h-0 space-y-2 lg:overflow-y-auto">
        {cues.length ? <ol className="grid gap-2">
          {cues.slice(first, first + pageSize).map((cue, offset) => {
            const index = first + offset;
            const number = index + 1;
            return <li key={index} className="grid gap-2 rounded-lg bg-muted/45 p-2.5">
              <div className="grid grid-cols-[auto_minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2">
                <Button type="button" variant="ghost" size="icon-sm" disabled={!asset.available}
                  aria-label={'播放第 ' + number + ' 条'} onClick={() => {
                    const position = milliseconds(cue.start);
                    if (position != null) playFrom(video.current, position);
                  }}><Play /></Button>
                <Input value={cue.start} className="font-mono text-xs" aria-label={'第 ' + number + ' 条开始时间'}
                  disabled={readOnly} onChange={event => edit(index, 'start', event.target.value)} />
                <span className="text-xs text-muted-foreground">至</span>
                <Input value={cue.end} className="font-mono text-xs" aria-label={'第 ' + number + ' 条结束时间'}
                  disabled={readOnly} onChange={event => edit(index, 'end', event.target.value)} />
              </div>
              <Textarea ref={index === focusCue ? focusEditor : undefined} value={cue.text} rows={2} maxLength={2000} className="min-h-12 resize-y"
                aria-label={'第 ' + number + ' 条字幕'} disabled={readOnly} onChange={event => edit(index, 'text', event.target.value)} />
            </li>;
          })}
        </ol> : <p className="grid min-h-32 place-items-center rounded-lg bg-muted/40 px-4 text-center text-sm text-muted-foreground">
          {busy ? '处理完成后，字幕会显示在这里。' : '提取已有字幕或从语音生成后，即可在这里校对。'}
        </p>}
        {cues.length > pageSize && <div className="flex items-center justify-end gap-2 text-xs text-muted-foreground">
          {first + 1}–{Math.min(first + pageSize, cues.length)} / {cues.length}
          <Button type="button" variant="outline" size="icon-sm" aria-label="上一页字幕" disabled={page === 0}
            onClick={() => setPage(page - 1)}><ChevronLeft /></Button>
          <Button type="button" variant="outline" size="icon-sm" aria-label="下一页字幕"
            disabled={first + pageSize >= cues.length} onClick={() => setPage(page + 1)}><ChevronRight /></Button>
        </div>}
      </CardContent>
      <CardFooter className="mt-3 flex flex-wrap items-center justify-end gap-2 border-t pt-3">
        {(error || notice || changed) && <div className="w-full">
          {error ? <ErrorNotice>{error}</ErrorNotice>
            : <p role="status" className="text-xs text-muted-foreground">{notice || '有未保存的字幕修改'}</p>}
        </div>}
        {changed && <Button type="button" variant="ghost" size="sm" disabled={readOnly} onClick={discardDraft}>放弃修改</Button>}
        <Button type="button" variant={changed ? 'default' : 'outline'} size="sm" disabled={!changed || readOnly}
          onClick={() => void act('save')}>保存字幕</Button>
        <Button type="button" variant="outline" size="sm" disabled={!canExport} onClick={() => void act('export')}>
          <Download data-icon="inline-start" />导出 SRT
        </Button>
        <Button type="button" variant="outline" size="sm" disabled={!canExport} onClick={onUseForSynthesis}>
          <Film data-icon="inline-start" />用此字幕合成
        </Button>
      </CardFooter>
      </TabsContent>
      <TabsContent value="script" className="min-h-0 lg:overflow-y-auto">
        <CardContent className="pb-2">
          <ScriptReviewPanel assetId={asset.id} revision={revision} hasDraft={changed} caption={caption}
            hasTextTrack={!!track} hasAudio={asset.has_audio !== false}
            onPlay={ms => playFrom(video.current, ms)} onEdit={openCue} />
        </CardContent>
      </TabsContent>
      </Tabs>
    </Card>
  </div>;
}
