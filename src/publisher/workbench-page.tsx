import { ArrowRight, ClipboardList, Clock3, ShieldAlert, UsersRound } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import type { TaskStatus } from '@/types';
import { editingTools, errorMessage, isConnected, loginLabels, openStatuses, taskLabels } from './model';
import type { PublisherWorkspace } from './use-workspace';
import { ErrorNotice, PlatformMark, StatusBadge, WorkspaceHeading } from './workspace-ui';

type Activity = { day: string; status: TaskStatus; count: number };
const series = [
  { name: '已提交', color: 'bg-emerald-600', match: (status: TaskStatus) => status === 'submitted' },
  { name: '待执行', color: 'bg-primary/75', match: (status: TaskStatus) => status === 'scheduled' || openStatuses.includes(status) },
  { name: '需处理', color: 'bg-amber-500', match: (status: TaskStatus) => ['failed', 'needs_review', 'action_required', 'missed'].includes(status) },
  { name: '草稿或取消', color: 'bg-muted-foreground/45', match: () => true },
];

function recentDays(period: number) {
  const today = new Date();
  return Array.from({ length: period }, (_, index) => {
    const date = new Date(today.getFullYear(), today.getMonth(), today.getDate() - period + index + 1);
    const month = date.getMonth() + 1;
    const day = date.getDate();
    return { key: [date.getFullYear(), month, day].map(part => String(part).padStart(2, '0')).join('-'), label: `${month}/${day}` };
  });
}

function PublicationActivity({ groupId }: { groupId: string }) {
  const [period, setPeriod] = useState(7);
  const [selected, setSelected] = useState('');
  const [result, setResult] = useState<{ groupId: string; rows: Activity[]; error: string }>();
  useEffect(() => {
    let revision = 0;
    let active = true;
    function load() {
      const version = ++revision;
      void window.publisher.request<Activity[]>('workbench.activity', { group_id: groupId }).then(rows => {
        if (active && version === revision) setResult({ groupId, rows, error: '' });
      }).catch(cause => {
        if (active && version === revision) setResult({ groupId, rows: [], error: errorMessage(cause) });
      });
    }
    const stop = window.publisher.subscribe(load);
    load();
    return () => { active = false; stop(); };
  }, [groupId]);

  const snapshot = result?.groupId === groupId ? result : undefined;
  const byDay = new Map<string, number[]>();
  for (const row of snapshot?.rows ?? []) {
    const counts = byDay.get(row.day) ?? [0, 0, 0, 0];
    counts[series.findIndex(item => item.match(row.status))] += row.count;
    byDay.set(row.day, counts);
  }
  const days = recentDays(period).map(date => {
    const counts = byDay.get(date.key) ?? [0, 0, 0, 0];
    return { ...date, counts, total: counts.reduce((sum, count) => sum + count, 0) };
  });
  const maximum = Math.max(...days.map(day => day.total), 1);
  const focus = days.find(day => day.key === selected) ?? days.filter(day => day.total > 0).at(-1) ?? days.at(-1)!;

  return <Card className="workspace-panel gap-4">
    <CardHeader className="flex flex-wrap items-start justify-between gap-3">
      <div className="space-y-1"><CardTitle>发布任务趋势</CardTitle><p className="text-xs text-muted-foreground">按任务创建日统计当前状态</p></div>
      <div className="flex gap-0.5 rounded-lg border bg-muted/40 p-0.5" role="group" aria-label="统计时段">
        {[7, 30].map(days => <Button key={days} type="button" size="sm" variant={period === days ? 'outline' : 'ghost'}
          aria-pressed={period === days} onClick={() => { setPeriod(days); setSelected(''); }}>近 {days} 天</Button>)}
      </div>
    </CardHeader>
    <CardContent className="grid gap-3">
      {snapshot?.error ? <ErrorNotice>{snapshot.error}</ErrorNotice>
        : !snapshot || !days.some(day => day.total > 0)
          ? <p className="grid h-28 place-items-center rounded-lg border border-dashed text-sm text-muted-foreground">
            {snapshot ? `近 ${period} 天暂无发布任务` : '正在读取发布数据…'}
          </p>
          : <>
            <div className="flex gap-2" role="group" aria-label="每日发布任务分布">
              <div aria-hidden="true" className="flex w-6 flex-col justify-between pb-5 text-right text-[10px] tabular-nums text-muted-foreground">
                <span>{maximum}</span><span>0</span>
              </div>
              {days.map((day, index) => <button key={day.key} type="button" aria-pressed={focus.key === day.key}
                aria-label={`${day.label}，${day.total} 条任务`} onClick={() => setSelected(day.key)}
                className="group flex min-w-0 flex-1 flex-col items-center gap-1 rounded-sm focus-visible:ring-2">
                <span className={cn('flex h-28 w-full items-end justify-center rounded-t border-b px-0.5',
                  focus.key === day.key ? 'bg-muted/70' : 'group-hover:bg-muted/45')}>
                  <span className="flex w-full max-w-8 flex-col-reverse overflow-hidden rounded-t" style={{ height: `${day.total * 100 / maximum}%` }}>
                    {day.counts.map((count, position) => count > 0 && <span key={series[position].name} aria-hidden="true"
                      className={cn('min-h-px', series[position].color)} style={{ flexGrow: count }} />)}
                  </span>
                </span>
                {(period === 7 || index % 6 === 0) && <span aria-hidden="true" className="text-[10px] tabular-nums text-muted-foreground">{day.label}</span>}
              </button>)}
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t pt-2 text-xs" aria-live="polite">
              <span className="font-medium tabular-nums">{focus.label} · {focus.total} 条</span>
              {series.map((item, index) => <span key={item.name} className="flex items-center gap-1.5 text-muted-foreground">
                <span aria-hidden="true" className={cn('size-2 rounded-sm', item.color)} />{item.name} {focus.counts[index]}
              </span>)}
            </div>
          </>}
    </CardContent>
  </Card>;
}

export function WorkbenchPage({ workspace }: { workspace: PublisherWorkspace }) {
  const { group, bindings, tasks, bindingName, changeView } = workspace;
  if (!group) return null;
  const metrics = [
    { label: '已连接账号', value: bindings.filter(isConnected).length, icon: UsersRound },
    { label: '需重新验证', value: bindings.filter(binding => binding.login_status === 'attention').length, icon: ShieldAlert },
    { label: '待执行任务', value: workspace.activeTasks, icon: ClipboardList },
  ];
  const accounts = bindings.filter(binding => binding.label || isConnected(binding) || binding.login_status === 'attention')
    .sort((left, right) => Number(right.login_status === 'attention') - Number(left.login_status === 'attention')).slice(0, 4);

  return <>
    <WorkspaceHeading title="工作台" description={`当前发布组 · ${group.name}`} />
    <div className="grid gap-3 sm:grid-cols-3">
      {metrics.map(({ label, value, icon: Icon }) => <Card key={label} className="workspace-panel gap-2 py-4" aria-label={label}>
        <CardContent className="flex items-center justify-between gap-3">
          <div className="grid gap-1">
            <p className="text-xs font-medium text-muted-foreground">{label}</p>
            <p className="text-2xl font-semibold tabular-nums" aria-label={label + '数量'}>{value}</p>
          </div>
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground"><Icon aria-hidden="true" className="size-4" /></span>
        </CardContent>
      </Card>)}
    </div>
    <section aria-labelledby="workbench-tools" className="grid gap-2">
      <h2 id="workbench-tools" className="text-sm font-semibold">常用工具</h2>
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        {editingTools.slice(1).map(({ id, label, icon: Icon }) => <Button key={id} type="button" variant="outline"
          aria-label={`打开${label}`} className="workspace-panel h-11 justify-start gap-2 bg-card px-2.5 sm:px-3" onClick={() => changeView(id)}>
          <Icon aria-hidden="true" className="text-muted-foreground" /><span className="flex-1 text-left">{label}</span><ArrowRight aria-hidden="true" className="text-muted-foreground" />
        </Button>)}
      </div>
    </section>
    <div className="grid min-w-0 items-start gap-3 lg:grid-cols-[minmax(0,1.55fr)_minmax(15.5rem,1fr)]">
      <PublicationActivity groupId={group.id} />
      <Card className="workspace-panel gap-3">
        <CardHeader className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>账号状态</CardTitle>
          <Button type="button" variant="ghost" size="sm" onClick={() => changeView('accounts')}>管理账号<ArrowRight data-icon="inline-end" /></Button>
        </CardHeader>
        <CardContent>
          {accounts.length ? <ul className="divide-y">{accounts.map(binding => <li key={binding.id}>
            <div className="flex items-center gap-2 px-1 py-2">
              <PlatformMark platform={binding.platform} />
              <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{bindingName(binding)}</span>
                {binding.label && <span className="block truncate text-xs text-muted-foreground">{binding.label}</span>}</span>
              <StatusBadge value={loginLabels[binding.login_status]} />
            </div>
          </li>)}</ul> : <p className="rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground">当前发布组还没有绑定账号。</p>}
        </CardContent>
      </Card>
    </div>
    <Card className="workspace-panel gap-3">
      <CardHeader className="flex flex-wrap items-center justify-between gap-2">
        <CardTitle>最近发布</CardTitle>
        <Button type="button" variant="ghost" size="sm" onClick={() => changeView('history')}>查看发布记录<ArrowRight data-icon="inline-end" /></Button>
      </CardHeader>
      <CardContent>
        {tasks.length ? <ul className="divide-y">{tasks.slice(0, 5).map(task => <li key={task.id}
          className="flex flex-wrap items-center gap-2 py-2.5">
          <PlatformMark platform={task.platform} />
          <div className="min-w-28 flex-1"><p className="truncate text-sm font-medium">{task.title}</p>
            <p className="truncate text-xs text-muted-foreground">{task.target_label || workspace.nameOf(task.platform)}</p></div>
          <StatusBadge value={taskLabels[task.status]} />
        </li>)}</ul> : <p className="flex items-center gap-2 rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground">
          <Clock3 aria-hidden="true" className="size-4" />当前发布组还没有发布记录。
        </p>}
      </CardContent>
    </Card>
  </>;
}
