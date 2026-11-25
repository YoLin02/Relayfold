import { useEffect, useState } from 'react';
import { CalendarClock, CalendarX, ChevronDown, CircleCheck, CircleX, Ellipsis, ExternalLink, History, LoaderCircle, Plus, RotateCcw, ScanLine, Search, Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Input } from '@/components/ui/input';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { Binding, PlatformInfo, Task } from '@/types';
import { accountCategories, accountStates, contentKinds, errorMessage, groupModes, isConnected, loginLabels, openStatuses, platformRegions, taskLabels, type AccountCategory, type AccountState } from './model';
import { defaultHistoryFilter, historyBounds, historyPeriods, type HistoryFilter } from './history';
import type { PublisherWorkspace } from './use-workspace';
import { formatSchedule, scheduleInput } from './schedule';
import { PlatformIcon, PlatformMark, StatusBadge, WorkspaceField, WorkspaceHeading, WorkspaceSelect } from './workspace-ui';

function AccountActions({ workspace, info, binding }: { workspace: PublisherWorkspace; info: PlatformInfo; binding: Binding }) {
  const busy = workspace.isBusy;
  const name = workspace.bindingName(binding);
  if (!binding.label) {
    return <Button type="button" variant="outline" className="w-25" disabled={busy} onClick={() => workspace.chooseLogin(binding)}>
      {info.mode === 'api' ? '配置 API' : '绑定账号'}
    </Button>;
  }
  return <DropdownMenu modal={false}>
    <DropdownMenuTrigger asChild>
      <Button type="button" variant="outline" className="w-25" disabled={busy} aria-label={`管理${name}`}>
        {workspace.state.pending === binding.id && <LoaderCircle className="animate-spin" data-icon="inline-start" />}
        管理<ChevronDown data-icon="inline-end" />
      </Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="end" className="w-40">
      <DropdownMenuItem onSelect={() => void workspace.run(binding.id, () => window.publisher.request('accounts.check', { id: binding.id }),
        () => workspace.update({ notice: `${name} · ${binding.label} 登录有效。` }))}><CircleCheck />检查登录</DropdownMenuItem>
      {info.mode !== 'api' && <>
        <DropdownMenuItem onSelect={() => workspace.chooseLogin(binding)}><ScanLine />验证或重新登录</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => void workspace.run(binding.id, () => window.publisher.request('accounts.manage', { id: binding.id }))}>
          <ExternalLink />打开后台
        </DropdownMenuItem>
      </>}
      <DropdownMenuSeparator />
      <DropdownMenuItem variant="destructive" onSelect={() => workspace.showConfirmation({ type: 'replace', binding })}>
        <RotateCcw />新建会话
      </DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>;
}

function AccountRow({ workspace, info, binding }: { workspace: PublisherWorkspace; info: PlatformInfo; binding: Binding }) {
  const name = workspace.bindingName(binding);
  const canDelete = workspace.group?.mode === 'custom' || !!binding.label;
  return <article aria-label={name}
    className="account-card grid min-h-16 min-w-0 items-center rounded-lg bg-card px-3.5 py-3 transition-colors">
    <div className="account-platform flex min-w-0 items-center gap-3">
      <PlatformIcon platform={info.id} className="size-5.5" />
      <span className="truncate text-sm font-semibold" title={name}>{name}</span>
    </div>
    <div className="account-alias truncate text-sm text-muted-foreground" title={binding.label || undefined}>{binding.label || '—'}</div>
    <div aria-label="支持内容" className="account-kinds flex flex-wrap gap-1.5">
      {info.kinds.includes('video') && <Badge variant="secondary" className="h-6 rounded-md px-2 text-muted-foreground">视频</Badge>}
      {info.kinds.some(kind => kind !== 'video') && <Badge variant="secondary" className="h-6 rounded-md px-2 text-muted-foreground">图文</Badge>}
    </div>
    <div className="account-status"><StatusBadge value={loginLabels[binding.login_status]} /></div>
    <div className="account-action flex items-center gap-1">
      <AccountActions workspace={workspace} info={info} binding={binding} />
      {canDelete && <Button type="button" size="icon-sm" variant="ghost" aria-label={`删除${name}`} title="删除平台账号"
        className="text-destructive hover:bg-destructive/10 hover:text-destructive" disabled={workspace.isBusy}
        onClick={() => workspace.showConfirmation({ type: 'delete-account', binding })}>
        <Trash2 />
      </Button>}
    </div>
    {info.note && <span className="sr-only">{info.note}</span>}
  </article>;
}

export function AccountsPage({ workspace }: { workspace: PublisherWorkspace }) {
  const { group, bindings, visibleBindings, platforms, state, region } = workspace;
  const emptyGroup = group?.mode === 'custom' && !bindings.length;
  return <div className="grid gap-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <WorkspaceHeading title="平台账号" description={group && `${group.name} · ${groupModes[group.mode].label} · ${platformRegions[region].label}`} />
      {group?.mode === 'custom' && <Button type="button" disabled={workspace.isBusy} onClick={workspace.openAccountAdder}>
        <Plus data-icon="inline-start" />添加平台账号
      </Button>}
    </div>
    <Card className="workspace-panel @container">
      <CardContent className="grid gap-4">
        <div className="flex flex-col items-start gap-3 @min-[34rem]:flex-row @min-[34rem]:items-center @min-[34rem]:justify-between">
          <Tabs value={state.category} onValueChange={category => workspace.update({ category: category as AccountCategory })}>
            <TabsList aria-label="平台内容分类" className="workspace-segmented">
              {accountCategories.map(item => <TabsTrigger key={item.id} value={item.id}>{item.label}</TabsTrigger>)}
            </TabsList>
          </Tabs>
          <div className="flex w-full min-w-0 flex-wrap items-center gap-2 @min-[34rem]:w-auto">
            <WorkspaceSelect label="绑定状态" value={state.accountState} className="data-[size=default]:h-9"
              options={accountStates.map(item => ({ label: item.label, value: item.id }))}
              onValueChange={value => workspace.update({ accountState: value as AccountState })} />
            <div className="relative min-w-36 flex-1 @min-[34rem]:w-49 @min-[34rem]:flex-initial">
              <Search aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input aria-label="搜索平台" className="h-9 bg-background pl-9 shadow-xs" placeholder="搜索平台" value={state.search}
                onChange={event => workspace.update({ search: event.target.value })} />
            </div>
          </div>
        </div>
        {!visibleBindings.length ? <Empty>
          <EmptyHeader><EmptyMedia variant="icon"><Search /></EmptyMedia>
            <EmptyTitle>{emptyGroup ? '暂无平台账号' : '没有匹配的平台'}</EmptyTitle>
            <EmptyDescription>{emptyGroup ? '添加平台账号后，可以逐个绑定登录。' : '可以调整筛选条件或搜索名称。'}</EmptyDescription></EmptyHeader>
        </Empty> : <div className="grid gap-2">
          {visibleBindings.map(binding =>
            <AccountRow key={binding.id} workspace={workspace} info={platforms[binding.platform]} binding={binding} />)}
        </div>}
      </CardContent>
    </Card>
  </div>;
}

function HistoryFilters({ filter, onChange }: { filter: HistoryFilter; onChange: (filter: HistoryFilter) => void }) {
  return <div className="flex flex-wrap items-end gap-2.5 [&>[data-slot=field]]:w-36" role="group" aria-label="按创建时间筛选">
    <WorkspaceField label="创建时间">
      <WorkspaceSelect label="创建时间" value={filter.period} options={historyPeriods}
        onValueChange={period => onChange({ ...filter, period: period as HistoryFilter['period'] })} />
    </WorkspaceField>
    {filter.period === 'custom' && <>
      <WorkspaceField label="开始日期">
        <Input type="date" value={filter.from} onChange={event => onChange({ ...filter, from: event.target.value })} />
      </WorkspaceField>
      <WorkspaceField label="结束日期">
        <Input type="date" value={filter.to} onChange={event => onChange({ ...filter, to: event.target.value })} />
      </WorkspaceField>
    </>}
    {filter.period !== 'all' && <Button variant="ghost" onClick={() => onChange(defaultHistoryFilter)}>清除筛选</Button>}
  </div>;
}

export function HistoryPage({ workspace }: { workspace: PublisherWorkspace }) {
  const { group, state, update } = workspace;
  const filter = state.historyFilter;
  const bounds = historyBounds(filter);
  const reset = () => update({ historyFilter: defaultHistoryFilter });
  return <div className="grid gap-5">
    <WorkspaceHeading title="发布记录" description={`查看「${group?.name}」各平台账号的任务状态和结果。`} />
    <HistoryFilters filter={filter} onChange={historyFilter => update({ historyFilter })} />
    {!bounds ? <p className="text-sm text-destructive" role="alert">开始日期不能晚于结束日期。</p> :
      group && <HistoryResults key={JSON.stringify([group.id, filter.period, bounds.start, bounds.end])}
        workspace={workspace} groupId={group.id} start={bounds.start} end={bounds.end}
        filtered={!!(bounds.start || bounds.end)} onReset={reset} />}
  </div>;
}

type HistoryResult = { tasks: Task[]; has_more: boolean };

function HistoryActions({ workspace, task, manageSchedule }: {
  workspace: PublisherWorkspace; task: Task; manageSchedule: boolean;
}) {
  const binding = workspace.bindings.find(item => item.id === task.binding_id);
  const browserAccount = workspace.platforms[task.platform]?.mode !== 'api';
  const needsReview = binding && (task.status === 'needs_review' || task.status === 'draft_ready');
  const canVerify = binding && browserAccount && task.status === 'action_required';
  const canRetry = binding && isConnected(binding) && (task.status === 'failed' || task.status === 'action_required');
  const canDelete = task.status !== 'scheduled' && !openStatuses.includes(task.status);
  const otherActions = manageSchedule || needsReview || canVerify || canRetry;
  if (!otherActions && !canDelete) return null;

  return <DropdownMenu modal={false}>
    <DropdownMenuTrigger asChild>
      <Button size="icon-sm" variant="ghost" aria-label="更多操作" disabled={workspace.isBusy}>
        <Ellipsis />
      </Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="end" className="w-36">
      {manageSchedule && <>
        <DropdownMenuItem onSelect={() => workspace.showConfirmation({ type: 'schedule-change', task, scheduledFor: scheduleInput(5) })}>
          <CalendarClock />改期
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => workspace.showConfirmation({ type: 'schedule-cancel', task })}>
          <CalendarX />取消预约
        </DropdownMenuItem>
      </>}
      {needsReview && <>
        {browserAccount && <DropdownMenuItem
          onSelect={() => void workspace.run(task.id, () => window.publisher.request('accounts.manage', { id: task.binding_id }))}>
          <ExternalLink />打开后台
        </DropdownMenuItem>}
        <DropdownMenuItem onSelect={() => workspace.showConfirmation({ type: 'review', task, result: 'found' })}>
          <CircleCheck />已收稿
        </DropdownMenuItem>
        {task.status === 'needs_review' && <DropdownMenuItem
          onSelect={() => workspace.showConfirmation({ type: 'review', task, result: 'missing' })}>
          <CircleX />未收稿
        </DropdownMenuItem>}
      </>}
      {canVerify && <DropdownMenuItem onSelect={() => workspace.chooseLogin(binding)}><ScanLine />验证账号</DropdownMenuItem>}
      {canRetry && <DropdownMenuItem onSelect={() => void workspace.run(task.id, () => window.publisher.request('tasks.retry', { id: task.id }))}>
        <RotateCcw />重试
      </DropdownMenuItem>}
      {otherActions && canDelete && <DropdownMenuSeparator />}
      {canDelete && <DropdownMenuItem variant="destructive" onSelect={() => workspace.showConfirmation({ type: 'delete-task', task })}>
        <Trash2 />删除记录
      </DropdownMenuItem>}
    </DropdownMenuContent>
  </DropdownMenu>;
}

function HistoryResults({ workspace, groupId, start, end, filtered, onReset }: {
  workspace: PublisherWorkspace; groupId: string; start: string | null; end: string | null;
  filtered: boolean; onReset: () => void;
}) {
  const { tasks: workspaceTasks } = workspace;
  const source = workspace.state.data;
  const [page, setPage] = useState(0);
  const [state, setState] = useState<{ page: number; result?: HistoryResult; error?: string }>();
  const [diagnosticTask, setDiagnosticTask] = useState<Task>();
  useEffect(() => {
    let current = true;
    void window.publisher.request<HistoryResult>('tasks.history', { group_id: groupId, start, end, page })
      .then(result => {
        if (!current) return;
        if (!result.tasks.length && page > 0) setPage(page - 1);
        else setState({ page, result });
      })
      .catch(error => { if (current) setState({ page, error: errorMessage(error) }); });
    return () => { current = false; };
  }, [groupId, start, end, page, source]);

  if (state?.page !== page) return <p role="status" className="text-sm text-muted-foreground">正在读取发布记录…</p>;
  if (state.error || !state.result) return <p role="alert" className="text-sm text-destructive">
    {state.error || '无法读取发布记录。'}
  </p>;
  const { tasks, has_more } = state.result;
  if (!tasks.length) return <Empty className="rounded-xl border">
    <EmptyHeader><EmptyMedia variant="icon"><History /></EmptyMedia>
      <EmptyTitle>{filtered ? '所选日期没有发布记录' : '暂无发布记录'}</EmptyTitle>
      {!filtered && <EmptyDescription>提交群发后，任务会出现在这里。</EmptyDescription>}
    </EmptyHeader>
    <EmptyContent><Button variant="outline" onClick={filtered ? onReset : () => workspace.changeView('publish')}>
      {filtered ? '查看全部记录' : '新建发布'}
    </Button></EmptyContent>
  </Empty>;

  const scheduledBatches = new Map(workspaceTasks.filter(task => task.status === 'scheduled' || task.status === 'missed')
    .map(task => [task.batch_id, task.id]));
  return <>
    <Card className="workspace-panel py-0">
      <CardContent className="divide-y">
        {tasks.map(task => {
          const name = workspace.bindingName(task);
          const hasDiagnostics = task.platform === 'douyin' || (task.platform === 'xiaohongshu' && task.kind === 'video');
          const manageSchedule = scheduledBatches.get(task.batch_id) === task.id;
          return <article key={task.id} aria-label={`${name} · ${task.target_label}`} className="flex flex-wrap items-start gap-3 py-3.5">
            <PlatformMark platform={task.platform} />
            <div className="min-w-0 flex-1 basis-40 space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <strong className="min-w-0 text-sm font-medium wrap-break-word">{task.title}</strong><StatusBadge value={taskLabels[task.status]} />
              </div>
              <div className="text-xs text-muted-foreground">
                {name} · {task.target_label} · {contentKinds[task.kind].label} · <time dateTime={task.created_at}
                  title={`最近更新 ${new Date(task.updated_at).toLocaleString('zh-CN', { hour12: false })}`}>
                  {new Date(task.created_at).toLocaleString('zh-CN', { hour12: false })}
                </time>
              </div>
              <p className="text-xs text-muted-foreground">{task.detail}</p>
              {task.scheduled_at !== null && <p className="text-xs text-muted-foreground">预约时间 {formatSchedule(task.scheduled_at)}</p>}
              {task.receipt && <p className="text-xs break-all text-muted-foreground">作品回执 {task.receipt}</p>}
            </div>
            <div className="flex shrink-0 items-center gap-1 empty:hidden">
              {hasDiagnostics &&
                <Button size="sm" variant="ghost" onClick={() => setDiagnosticTask(task)}>诊断记录</Button>}
              <HistoryActions workspace={workspace} task={task} manageSchedule={manageSchedule} />
            </div>
          </article>;
        })}
      </CardContent>
    </Card>
    {(page > 0 || has_more) && <nav className="flex flex-wrap items-center justify-end gap-2" aria-label="发布记录分页">
      <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(page - 1)}>上一页</Button>
      <span className="px-1 text-xs text-muted-foreground">第 {page + 1} 页</span>
      <Button size="sm" variant="outline" disabled={!has_more} onClick={() => setPage(page + 1)}>下一页</Button>
    </nav>}
    {diagnosticTask && <TaskDiagnostics key={diagnosticTask.id} task={diagnosticTask}
      onClose={() => setDiagnosticTask(undefined)} />}
  </>;
}

function TaskDiagnostics({ task, onClose }: { task: Task; onClose: () => void }) {
  const [events, setEvents] = useState<{ at: string; detail: string }[]>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    let revision = 0;
    const refresh = () => {
      const request = ++revision;
      void window.publisher.request<{ at: string; detail: string }[]>('tasks.diagnostics', { id: task.id })
        .then(result => {
          if (active && request === revision) { setEvents(result); setFailed(false); }
        })
        .catch(() => { if (active && request === revision) setFailed(true); });
    };
    const unsubscribe = window.publisher.subscribe(refresh);
    refresh();
    return () => { active = false; unsubscribe(); };
  }, [task.id]);

  return <Dialog open onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent className="sm:max-w-xl">
      <DialogHeader>
        <DialogTitle>诊断记录</DialogTitle>
        <DialogDescription>{task.title}</DialogDescription>
      </DialogHeader>
      {failed ? <p role="alert" className="text-sm text-destructive">无法读取这条任务的诊断记录。</p> :
        !events?.length ? <p role="status" className="text-sm text-muted-foreground">
          {events ? '这条任务暂无诊断记录。' : '正在读取诊断记录…'}
        </p> : <ol className="max-h-96 space-y-3 overflow-y-auto pr-1" aria-label="任务事件">
          {events.map((event, index) => <li key={`${event.at}-${index}`} className="text-sm">
            <time dateTime={event.at} className="block text-xs tabular-nums text-muted-foreground">
              {new Date(event.at).toLocaleString('zh-CN', { hour12: false })}
            </time>
            <span className="wrap-break-word">{event.detail}</span>
          </li>)}
        </ol>}
    </DialogContent>
  </Dialog>;
}
