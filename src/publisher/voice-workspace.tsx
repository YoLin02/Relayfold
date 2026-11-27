import { AudioLines, Download, FolderOpen, Mic, Pencil, Play, Trash2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { errorMessage, fileName } from './model';
import { ErrorNotice, WorkspaceSelect } from './workspace-ui';

type Voice = { id: string; name: string; model: string; available: boolean; hasReference: boolean; compatible: boolean };
type Output = { id: string; voiceName: string; duration: number; text: string; available: boolean };
type Reference = { id: string; name: string; duration: number };
type Job = {
  id: string; kind: 'model' | 'runtime' | 'transcribe' | 'clone' | 'import' | 'generate';
  status: 'running' | 'ready' | 'failed' | 'canceled'; progress: number | null; detail: string;
  result: { transcript?: string; reference?: string; profile?: string; output?: string } | null;
};
type VoiceSnapshot = {
  directory: string; runtime: { ready: boolean; device: string };
  models: { id: string; bytes: number; ready: boolean }[];
  profiles: Voice[]; outputs: Output[]; reference: Reference | null; job: Job | null;
};
type Player = { id: string; url: string; label: string };
type Edit = { id: string; name: string; action: 'rename' | 'profile.delete' | 'output.delete' };

const completed = {
  model: '模型已就绪。', runtime: '配音环境已就绪。', transcribe: '识别完成，请核对参考原文。',
  clone: '音色已保存。', import: '旧音色已导入。', generate: '配音已生成，可试听或导出。',
};
const languages = [
  ['Chinese', '普通话'], ['Auto', '自动'], ['English', '英语'], ['Japanese', '日语'], ['Korean', '韩语'],
  ['German', '德语'], ['French', '法语'], ['Russian', '俄语'], ['Portuguese', '葡萄牙语'],
  ['Spanish', '西班牙语'], ['Italian', '意大利语'],
].map(([value, label]) => ({ value, label }));
const modes = [{ value: 'icl', label: '参考音色和语气' }, { value: 'timbre', label: '主要参考音色' }];

function useVoiceSnapshot() {
  const [snapshot, setSnapshot] = useState<VoiceSnapshot>();
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    let revision = 0;
    function load() {
      const ticket = ++revision;
      void window.publisher.request<VoiceSnapshot>('voice.snapshot').then(data => {
        if (active && revision === ticket) { setSnapshot(data); setError(''); }
      }).catch(cause => { if (active && revision === ticket) setError(errorMessage(cause)); });
    }
    const stop = window.publisher.subscribeVoice(load);
    load();
    return () => { active = false; stop(); };
  }, []);
  return { snapshot, error };
}

export function VoiceWorkspace() {
  const { snapshot, error: loadError } = useVoiceSnapshot();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [modelId, setModelId] = useState('');
  const [profileId, setProfileId] = useState('');
  const [name, setName] = useState('');
  const [referenceText, setReferenceText] = useState('');
  const [trim, setTrim] = useState<{ id: string; start: string; end: string }>();
  const [text, setText] = useState('');
  const [language, setLanguage] = useState('Chinese');
  const [mode, setMode] = useState('icl');
  const [player, setPlayer] = useState<Player>();
  const [edit, setEdit] = useState<Edit>();
  const latestResult = useRef('');
  const job = snapshot?.job;
  const busy = job?.status === 'running';
  const locked = pending || busy;
  const reference = snapshot?.reference;
  const clip = reference && (trim?.id === reference.id ? trim : {
    id: reference.id, start: '0', end: String(Math.floor(Math.min(12, reference.duration) * 100) / 100),
  });
  const settings = clip ? { reference: clip.id, start: Number(clip.start), end: Number(clip.end) } : undefined;
  const validClip = !!(clip?.start && clip.end && settings && reference && settings.start >= 0 &&
    settings.end <= reference.duration + 0.01 && settings.end - settings.start >= 3 && settings.end - settings.start <= 30);
  const models = snapshot?.models ?? [];
  const readyModels = models.filter(model => model.ready);
  const selectedModel = readyModels.some(model => model.id === modelId) ? modelId : readyModels[0]?.id ?? '';
  const profiles = snapshot?.profiles ?? [];
  const readyProfiles = profiles.filter(profile => profile.available && profile.compatible &&
    readyModels.some(model => model.id === profile.model));
  const selection = readyProfiles.some(profile => profile.id === profileId) ? profileId : readyProfiles[0]?.id ?? '';
  const runtime = snapshot?.runtime;

  useEffect(() => {
    if (job?.status !== 'ready' || latestResult.current === job.id) return;
    latestResult.current = job.id;
    if (job.result?.transcript && job.result.reference === reference?.id) setReferenceText(job.result.transcript);
    if (job.result?.profile) setProfileId(job.result.profile);
  }, [job, reference?.id]);

  async function run(action: () => Promise<unknown>) {
    setError('');
    setNotice('');
    setPending(true);
    try { await action(); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setPending(false); }
  }

  function request(action: string, args?: Record<string, unknown>) {
    return window.publisher.request('voice.' + action, args);
  }

  function changeClip(field: 'start' | 'end', value: string) {
    if (!clip) return;
    setTrim({ ...clip, [field]: value });
    setReferenceText('');
  }

  async function preview(id: string, label: string, kind: 'reference' | 'output') {
    const url = await window.publisher.voiceAction<string>('preview', { id, kind });
    if (url) setPlayer({ id, url, label });
  }

  function onEdit() {
    if (!edit) return;
    void run(async () => {
      await request(edit.action === 'rename' ? 'profile.rename' : edit.action, { id: edit.id, name: edit.name });
      if (edit.action !== 'rename' && player?.id === edit.id) setPlayer(undefined);
      setEdit(undefined);
    });
  }

  return <div className="grid gap-3 pr-0.5">
    {(error || loadError) && <ErrorNotice>{error || loadError}</ErrorNotice>}
    {(job || notice) && <div className="workspace-panel sticky top-0 z-10 flex flex-wrap items-center gap-3 rounded-lg bg-card px-4 py-2.5">
      <div className="min-w-40 flex-1">
        {job && <div role={job.status === 'failed' ? 'alert' : 'status'}>
          <p className={job.status === 'failed' ? 'text-sm text-destructive' : 'text-sm'}>
            {job.status === 'ready' ? completed[job.kind] : job.detail}
          </p>
          {busy && job.progress !== null && <progress className="h-1.5 w-full accent-primary" max={100} value={job.progress} aria-label="配音任务进度" />}
        </div>}
        {notice && <p role="status" className="text-sm text-muted-foreground">{notice}</p>}
      </div>
      {busy && <Button type="button" size="sm" variant="outline" disabled={pending} onClick={() => void run(() => request('cancel'))}>取消任务</Button>}
    </div>}

    <Card className="workspace-panel gap-3 py-4">
      <CardHeader className="gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>本地模型与运行环境</CardTitle>
          <Button type="button" variant="outline" size="sm" disabled={!snapshot || locked} onClick={() => void run(() => window.publisher.voiceAction('directory'))}>
            <FolderOpen data-icon="inline-start" />更改下载目录
          </Button>
        </div>
        <p className="break-all text-xs text-muted-foreground" title={snapshot?.directory}>{snapshot?.directory}</p>
      </CardHeader>
      <CardContent className="grid gap-3">
        <div className="grid gap-2 md:grid-cols-2">
          {models.map(model => <div key={model.id} className="grid gap-2 rounded-lg bg-muted/45 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-medium">Qwen3‑TTS {model.id} Base</span>
              <Badge variant="secondary">{model.ready ? '已就绪' : `${(model.bytes / 1e9).toFixed(2)} GB`}</Badge>
            </div>
            <div className="flex flex-wrap gap-2">
              {!model.ready && <Button type="button" size="sm" disabled={locked} aria-label={`下载 ${model.id} 模型`}
                onClick={() => void run(() => request('model.download', { model: model.id }))}>
                <Download data-icon="inline-start" />下载模型
              </Button>}
              <Button type="button" size="sm" variant="outline" disabled={locked} aria-label={`选择 ${model.id} 本机目录`}
                onClick={() => void run(() => window.publisher.voiceAction('model', { model: model.id }))}>选择本机目录</Button>
            </div>
          </div>)}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3">
          <div className="min-w-40">
            <p className="text-sm font-medium">配音环境</p>
            <p className="text-xs text-muted-foreground">{runtime?.ready ? runtime.device : 'Windows x64 · NVIDIA CUDA · 首次安装需 12 GiB 可用空间'}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {!runtime?.ready && <Button type="button" size="sm" variant="outline" disabled={!snapshot || locked}
              onClick={() => void run(() => request('runtime.install'))}>安装配音环境</Button>}
            <Button type="button" size="sm" variant="outline" disabled={!snapshot || locked}
              onClick={() => void run(() => window.publisher.voiceAction('runtime'))}>选择已有环境</Button>
          </div>
        </div>
      </CardContent>
    </Card>

    <div className="grid items-start gap-3 lg:grid-cols-2">
      <Card className="workspace-panel">
        <CardHeader><CardTitle>克隆音色</CardTitle></CardHeader>
        <CardContent className="grid gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" disabled={!snapshot || locked} onClick={() => void run(async () => {
              await window.publisher.voiceAction('reference');
              const next = await window.publisher.request<VoiceSnapshot>('voice.snapshot');
              if (next.reference?.id !== reference?.id) { setReferenceText(''); setTrim(undefined); }
            })}><FolderOpen data-icon="inline-start" />选择参考录音</Button>
            {reference && <span className="min-w-0 break-all text-xs text-muted-foreground">{reference.name} · {reference.duration.toFixed(1)} 秒</span>}
          </div>
          {clip && <div className="grid grid-cols-2 gap-2">
            <div className="grid gap-1.5"><Label htmlFor="voice-trim-start">片段起点（秒）</Label>
              <Input id="voice-trim-start" type="number" min="0" step="0.01" value={clip.start} disabled={locked}
                onChange={event => changeClip('start', event.target.value)} /></div>
            <div className="grid gap-1.5"><Label htmlFor="voice-trim-end">片段终点（秒）</Label>
              <Input id="voice-trim-end" type="number" min="3" step="0.01" value={clip.end} disabled={locked}
                onChange={event => changeClip('end', event.target.value)} /></div>
            {!validClip && <p className="col-span-2 text-xs text-destructive">请选择录音内 3 到 30 秒的片段。</p>}
          </div>}
          <div className="grid gap-1.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Label htmlFor="voice-reference-text">参考录音原文</Label>
              <Button type="button" size="sm" variant="ghost" disabled={!validClip || locked}
                onClick={() => void run(() => request('transcribe', settings))}>自动识别</Button>
            </div>
            <Textarea id="voice-reference-text" rows={3} maxLength={2000} value={referenceText} disabled={locked}
              placeholder="填写参考片段中说的话，或用本地识别生成原文" onChange={event => setReferenceText(event.target.value)} />
          </div>
          <div className="grid gap-1.5"><Label htmlFor="voice-name">音色名称</Label>
            <Input id="voice-name" maxLength={80} value={name} disabled={locked} onChange={event => setName(event.target.value)} /></div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <WorkspaceSelect label="克隆模型" value={selectedModel} className="min-w-36" disabled={locked || !readyModels.length}
              options={readyModels.length ? readyModels.map(model => ({ value: model.id, label: `${model.id} Base` })) : [{ value: '', label: '先下载模型' }]}
              onValueChange={setModelId} />
            <Button type="button" disabled={locked || !runtime?.ready || !selectedModel || !validClip || !name.trim() || !referenceText.trim()}
              onClick={() => void run(() => request('clone', { ...settings, model: selectedModel, name, referenceText }))}>
              <Mic data-icon="inline-start" />克隆并保存
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card className="workspace-panel">
        <CardHeader><CardTitle>生成配音</CardTitle></CardHeader>
        <CardContent className="grid gap-3">
          <WorkspaceSelect label="配音音色" value={selection} disabled={locked || !readyProfiles.length}
            options={readyProfiles.length ? readyProfiles.map(profile => ({ value: profile.id, label: `${profile.name} · ${profile.model}` })) :
              [{ value: '', label: '选择已保存的音色' }]} onValueChange={setProfileId} />
          <div className="grid grid-cols-2 gap-2">
            <WorkspaceSelect label="配音语言" value={language} options={languages} disabled={locked} onValueChange={setLanguage} />
            <WorkspaceSelect label="配音方式" value={mode} options={modes} disabled={locked} onValueChange={setMode} />
          </div>
          <div className="grid gap-1.5"><Label htmlFor="voice-copy">配音文案</Label>
            <Textarea id="voice-copy" rows={5} maxLength={1200} value={text} disabled={locked}
              onChange={event => setText(event.target.value)} /></div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs tabular-nums text-muted-foreground">{text.length} / 1200</span>
            <Button type="button" disabled={locked || !runtime?.ready || !selection || !text.trim()}
              onClick={() => void run(() => request('generate', { id: selection, text, language, mode }))}>
              <AudioLines data-icon="inline-start" />生成配音
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>

    <div className="grid items-start gap-3 lg:grid-cols-2">
      <Card className="workspace-panel">
        <CardHeader className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>音色库</CardTitle>
          <Button type="button" size="sm" variant="outline" disabled={locked || !runtime?.ready || !readyModels.some(model => model.id === '1.7B')}
            title="导入知行或本机旧预设需要 1.7B Base" onClick={() => void run(() => window.publisher.voiceAction('import'))}>导入旧音色</Button>
        </CardHeader>
        <CardContent>
          {profiles.length ? <ul className="grid gap-2">{profiles.map(profile => <li key={profile.id}
            className="flex flex-wrap items-center gap-2 rounded-lg bg-muted/45 p-2.5">
            <div className="min-w-24 flex-1">
              <p className="break-words text-sm font-medium">{profile.name}</p>
              <p className="text-xs text-muted-foreground">{profile.model} Base · {profile.compatible && profile.available ? '已保存' : '需要重新创建'}</p>
            </div>
            {profile.hasReference && <Button type="button" size="sm" variant="ghost" disabled={pending}
              onClick={() => void run(() => preview(profile.id, `${profile.name} · 参考录音`, 'reference'))}>试听参考录音</Button>}
            <Button type="button" size="icon-sm" variant="ghost" aria-label={`重命名 ${profile.name}`} disabled={locked}
              onClick={() => setEdit({ id: profile.id, name: profile.name, action: 'rename' })}><Pencil /></Button>
            <Button type="button" size="icon-sm" variant="ghost" aria-label={`删除 ${profile.name}`} disabled={locked}
              onClick={() => setEdit({ id: profile.id, name: profile.name, action: 'profile.delete' })}><Trash2 /></Button>
            {player?.id === profile.id && <audio key={player.url} src={player.url} controls autoPlay
              className="w-full basis-full" aria-label={player.label} />}
          </li>)}</ul> : <p className="text-sm text-muted-foreground">克隆后可以在这里找到并复用音色。</p>}
        </CardContent>
      </Card>
      <Card className="workspace-panel">
        <CardHeader><CardTitle>配音记录</CardTitle></CardHeader>
        <CardContent className="grid gap-2">
          {snapshot?.outputs.length ? <ul className="grid gap-2">{snapshot.outputs.map(output => <li key={output.id}
            className="grid gap-2 rounded-lg bg-muted/45 p-2.5">
            <div className="min-w-0">
              <p className="line-clamp-2 break-words text-sm font-medium">{output.text}</p>
              <p className="text-xs text-muted-foreground">{output.voiceName} · {output.duration.toFixed(1)} 秒{output.available ? '' : ' · 文件缺失'}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button type="button" size="sm" variant="outline" disabled={pending || !output.available}
                onClick={() => void run(() => preview(output.id, `${output.voiceName} · 生成配音`, 'output'))}><Play data-icon="inline-start" />试听配音</Button>
              <Button type="button" size="sm" variant="outline" disabled={pending || !output.available} onClick={() => void run(async () => {
                const file = await window.publisher.voiceAction<string>('export', { id: output.id });
                if (file) setNotice('已导出 ' + fileName(file));
              })}><Download data-icon="inline-start" />导出 WAV</Button>
              <Button type="button" size="icon-sm" variant="ghost" aria-label={`删除配音 ${output.voiceName}`} disabled={locked}
                onClick={() => setEdit({ id: output.id, name: output.voiceName, action: 'output.delete' })}><Trash2 /></Button>
            </div>
            {player?.id === output.id && <audio key={player.url} src={player.url} controls autoPlay className="w-full" aria-label={player.label} />}
          </li>)}</ul> : <p className="text-sm text-muted-foreground">生成的配音可在这里试听和导出。</p>}
        </CardContent>
      </Card>
    </div>
    <Dialog open={!!edit} onOpenChange={open => { if (!open && !pending) setEdit(undefined); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{edit?.action === 'rename' ? '重命名音色' : edit?.action === 'profile.delete' ? '删除音色' : '删除配音记录'}</DialogTitle>
          <DialogDescription>{edit?.action === 'rename' ? '新名称会显示在音色库和配音选择中。' : `确认删除「${edit?.name ?? ''}」的这条本地记录？`}</DialogDescription>
        </DialogHeader>
        {edit?.action === 'rename' && <Input aria-label="新音色名称" maxLength={80} value={edit.name} disabled={pending}
          onChange={event => setEdit({ ...edit, name: event.target.value })} />}
        <DialogFooter>
          <Button type="button" variant="outline" disabled={pending} onClick={() => setEdit(undefined)}>取消</Button>
          <Button type="button" disabled={pending || !edit?.name.trim()} variant={edit?.action === 'rename' ? 'default' : 'destructive'}
            onClick={onEdit}>{edit?.action === 'rename' ? '保存名称' : '确认删除'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>;
}
