import { useRef, useState, type Ref } from 'react';
import { ArrowRight, FolderOpen, Layers2, Upload, UsersRound, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';
import { contentKinds, declarations, errorMessage, fileName, publishTabs, type Destination, type GraphicFormat, type PublishTab } from './model';
import { MediaPreview } from './media-preview';
import { EditorFields } from './platform-content';
import type { PublisherWorkspace } from './use-workspace';
import { PlatformIcon, PlatformMark, WorkspaceField, WorkspaceHeading, WorkspaceSelect } from './workspace-ui';

function MediaStrip({ workspace }: { workspace: PublisherWorkspace }) {
  const { draft, kind, group } = workspace;
  const config = contentKinds[kind];
  const [dragging, setDragging] = useState(false);
  const first = draft.files[0];
  const choose = () => {
    void window.publisher.selectMedia(kind === 'video' ? 'video' : 'image')
      .then(files => { if (files.length) workspace.chooseFiles(files, group?.id, kind); })
      .catch(error => workspace.update({ error: errorMessage(error) }));
  };
  if (kind === 'article' && !workspace.has('wangyi') && !draft.files.length) return null;
  return <div className={cn('flex min-h-22 flex-wrap items-center gap-x-3.5 gap-y-3 rounded-lg border border-dashed border-border bg-muted/45 px-3.5 py-3 transition-colors',
    dragging && 'border-ring bg-accent')}
    onDragOver={event => { event.preventDefault(); setDragging(true); }}
    onDragLeave={event => {
      if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) setDragging(false);
    }}
    onDrop={event => {
      event.preventDefault();
      setDragging(false);
      workspace.chooseFiles(Array.from(event.dataTransfer.files, file => window.publisher.filePath(file)));
    }}>
    {first ? <MediaPreview path={first} video={kind === 'video'} className="w-21 @min-[31rem]:w-26" />
      : <span aria-hidden="true" className="grid size-9 shrink-0 place-items-center rounded-md border bg-background shadow-xs"><Upload className="size-4" /></span>}
    <div className="min-w-28 flex-1 space-y-0.5">
      <div className="truncate text-sm font-semibold" title={first ? draft.files.map(fileName).join('、') : undefined}>{draft.files.length > 1
        ? `已选择 ${draft.files.length} 张图片` : first ? fileName(first) : '将文件拖放到这里'}</div>
      <div className="truncate text-xs text-muted-foreground">{draft.files.length > 1
        ? draft.files.map(fileName).join('、') : first ? (first.split('.').at(-1) || '').toUpperCase()
          : `${kind === 'article' ? '网易号配图' : '共享素材'} · ${config.formats}`}</div>
    </div>
    <div className="ml-auto flex items-center gap-1">
      <Button type="button" variant="outline" className="gap-2 px-3" onClick={choose}>
        <FolderOpen aria-hidden="true" className="size-4" />{first ? '更换素材' : config.choose}
      </Button>
      {first && <Button type="button" size="icon" variant="ghost" aria-label="移除素材" onClick={() => workspace.changeFiles([])}><X /></Button>}
    </div>
  </div>;
}

function PlatformSettings({ workspace, destination }: { workspace: PublisherWorkspace; destination: Destination }) {
  const { draft } = workspace;
  const id = destination.binding.platform;
  const options = workspace.optionGroups.find(group => group.id === id)?.fields || [];
  if (id !== 'douyin' && !options.length) return null;
  return <div className="grid gap-3 rounded-lg bg-muted/45 p-3">
    {id === 'douyin' && <WorkspaceField label="抖音作品声明">
      <WorkspaceSelect className="w-full" value={draft.declaration}
        options={[{ value: '', label: '选择适用的声明' }, ...declarations.map(value => ({ value, label: value }))]}
        onValueChange={declaration => workspace.changeDraft({ declaration })} />
    </WorkspaceField>}
    {options.map(({ key, label, placeholder, choices }) => {
      const value = draft.options[key] || '';
      const change = (value: string) => workspace.changeDraft(current => ({ options: { ...current.options, [key]: value } }));
      return <WorkspaceField key={key} label={label}>
        {choices ? <WorkspaceSelect className="w-full" value={value}
          options={[{ value: '', label: '请选择' }, ...choices]} onValueChange={change} />
          : <Input value={value} placeholder={placeholder} onChange={event => change(event.target.value)} />}
      </WorkspaceField>;
    })}
  </div>;
}

function Composer({ workspace }: { workspace: PublisherWorkspace }) {
  const [tab, setTab] = useState('shared');
  const { destinations } = workspace;
  const active = destinations.some(({ binding }) => binding.id === tab) ? tab : 'shared';
  return <Card className="workspace-panel @container min-w-0 self-start [--card-spacing:--spacing(5)]">
    <CardHeader><CardTitle className="text-base font-semibold">素材与文案</CardTitle></CardHeader>
    <CardContent className="grid gap-4">
      <MediaStrip workspace={workspace} />
      <Tabs value={active} onValueChange={setTab} className="min-w-0 gap-4">
        <TabsList aria-label="平台文案" variant="line" className="workspace-editor-tabs">
          <TabsTrigger value="shared"><Layers2 aria-hidden="true" className="size-4" />通用</TabsTrigger>
          {destinations.map(({ binding, name }) => <TabsTrigger key={binding.id} value={binding.id}>
            <PlatformIcon platform={binding.platform} />
            {name}
            {!!Object.keys(workspace.draft.overrides[binding.id] || {}).length && <span className="size-1.5 rounded-full bg-current" aria-label="已自定义" />}
          </TabsTrigger>)}
        </TabsList>
        <TabsContent value="shared"><EditorFields workspace={workspace} /></TabsContent>
        {destinations.map(destination =>
            <TabsContent key={destination.binding.id} value={destination.binding.id} className="data-[state=active]:grid gap-3">
              <EditorFields workspace={workspace} destination={destination} />
              <PlatformSettings workspace={workspace} destination={destination} />
            </TabsContent>)}
      </Tabs>
    </CardContent>
  </Card>;
}

function PublishButton({ workspace }: { workspace: PublisherWorkspace }) {
  return <Button type="submit" size="lg" disabled={!workspace.canSubmit} className="w-full">
    核对并群发<ArrowRight data-icon="inline-end" />
  </Button>;
}

function TargetPanel({ workspace, panelRef }: { workspace: PublisherWorkspace; panelRef: Ref<HTMLDivElement> }) {
  const { connected, destinations } = workspace;
  const selected = new Set(destinations.map(({ binding }) => binding.id));
  const all = connected.length > 0 && connected.every(binding => selected.has(binding.id));
  return <Card ref={panelRef} tabIndex={-1} className="workspace-panel min-w-0 scroll-mt-17 focus-visible:ring-2 focus-visible:ring-ring [--card-spacing:--spacing(5)]">
    <CardHeader>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <CardTitle className="text-base font-semibold">发布目标</CardTitle>
        <span className="text-xs text-muted-foreground">已选 {selected.size} 个</span>
      </div>
    </CardHeader>
    <CardContent className="grid gap-2.5">
      {connected.length ? <>
        {connected.length > 1 && <Button type="button" size="xs" variant="ghost" className="-mt-2 justify-self-end text-muted-foreground"
          onClick={() => workspace.changeDraft(current => ({ targets: all
            ? current.targets.filter(id => !connected.some(binding => binding.id === id))
            : [...new Set([...current.targets, ...connected.map(binding => binding.id)])] }))}>
          {all ? '取消全选' : '全选'}
        </Button>}
        <div className="grid max-h-[min(44vh,24rem)] gap-2 overflow-auto p-0.5" aria-label="发布账号">
          {connected.map(binding => {
            const name = workspace.bindingName(binding);
            const alias = binding.label === name ? '' : binding.label;
            const checked = selected.has(binding.id);
            return <label key={binding.id} className={cn(
              'grid cursor-pointer grid-cols-[auto_auto_minmax(0,1fr)] items-center gap-2.5 rounded-xl px-3 py-2.5 transition-colors hover:bg-accent/65',
              checked ? 'bg-[var(--workspace-selection,var(--muted))]' : 'bg-muted/35',
            )}>
              <Checkbox checked={checked} aria-label={`选择${name} ${alias}`.trim()}
                onCheckedChange={value => workspace.changeDraft(current => ({ targets: value
                  ? [...new Set([...current.targets, binding.id])]
                  : current.targets.filter(id => id !== binding.id) }))} />
              <PlatformMark platform={binding.platform} />
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium">{name}</span>
                {(alias || binding.platform === 'wechat_mp') && <span className="block truncate text-xs text-muted-foreground">
                  {alias}{alias && binding.platform === 'wechat_mp' && ' · '}{binding.platform === 'wechat_mp' && '草稿'}
                </span>}
              </span>
            </label>;
          })}
        </div>
      </> : <Empty className="gap-3 rounded-lg bg-muted/45 p-4 md:p-5">
        <EmptyHeader className="gap-2">
          <EmptyMedia variant="icon"><UsersRound /></EmptyMedia>
          <EmptyTitle className="text-sm">暂无可用账号</EmptyTitle>
          <EmptyDescription className="text-xs">请先为当前组绑定支持此内容类型的平台。</EmptyDescription>
        </EmptyHeader>
        <EmptyContent><Button type="button" variant="outline" size="sm" onClick={() => workspace.changeView('accounts')}>
          前往绑定<ArrowRight data-icon="inline-end" />
        </Button></EmptyContent>
      </Empty>}
    </CardContent>
    <CardFooter className="mt-auto hidden flex-col items-stretch gap-2 border-0 bg-transparent pt-0 lg:flex">
      {workspace.blockedReason && <p className="text-xs text-muted-foreground">{workspace.blockedReason}</p>}
      <PublishButton workspace={workspace} />
    </CardFooter>
  </Card>;
}

export function PublishPage({ workspace }: { workspace: PublisherWorkspace }) {
  const targets = useRef<HTMLDivElement>(null);
  const { draft, kind, state: { publishTab }, group, destinations, formats } = workspace;
  return <Tabs value={publishTab} onValueChange={value => workspace.update({ publishTab: value as PublishTab, error: '' })} className="gap-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <WorkspaceHeading title="新建发布" />
      <div className="flex flex-wrap items-center gap-2">
        <TabsList aria-label="内容类型" className="workspace-segmented">
          {publishTabs.map(({ id, label, icon: Icon }) => <TabsTrigger key={id} value={id}>
            <Icon aria-hidden="true" className="size-4" />{label}
          </TabsTrigger>)}
        </TabsList>
        <Button type="button" variant="outline" size="sm" className="lg:hidden" onClick={() => {
          targets.current?.scrollIntoView({ block: 'start' });
          targets.current?.focus({ preventScroll: true });
        }}><UsersRound data-icon="inline-start" />选择账号</Button>
      </div>
    </div>
    <TabsContent value={publishTab} className="grid gap-4">
      {publishTab === 'image' && formats.length > 0 && <div className="w-full max-w-52">
        <WorkspaceField label="图文格式">
          <WorkspaceSelect value={kind} disabled={formats.length === 1} className="w-full"
            options={formats.map(format => ({ value: format.id, label: format.label }))}
            onValueChange={value => workspace.update({ graphicFormat: value as GraphicFormat, error: '' })} />
        </WorkspaceField>
      </div>}
      <form className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1.56fr)_minmax(15.5rem,1fr)] xl:gap-5"
        onSubmit={event => {
          event.preventDefault();
          if (group && workspace.canSubmit) workspace.showConfirmation({ type: 'publish', group, kind, draft, destinations });
        }}>
        <Composer key={`${group?.id}:${kind}`} workspace={workspace} />
        <TargetPanel workspace={workspace} panelRef={targets} />
        <div className="sticky bottom-0 z-10 -mx-4 flex items-center justify-between gap-3 border-t bg-background px-4 py-2.5 sm:-mx-6 sm:px-6 lg:hidden">
          <span className="min-w-0 text-xs text-muted-foreground">{workspace.blockedReason || `已选择 ${destinations.length} 个账号`}</span>
          <div className="shrink-0"><PublishButton workspace={workspace} /></div>
        </div>
      </form>
    </TabsContent>
  </Tabs>;
}
