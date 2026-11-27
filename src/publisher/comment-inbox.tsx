import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowUpRight, RefreshCw } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { Binding, CommentDestination } from '@/types';
import {
  CommentThread, commentTime, commentTimestamp, currentReply, replyLabels,
  type NoteScope, type ReplyControls,
} from './comment-thread';
import { commentSyncTime, markCommentRead, useCommentSnapshot, type InboxSnapshot, type OriginalComment } from './comment-data';
import { errorMessage } from './model';
import { ErrorNotice, WorkspaceSelect } from './workspace-ui';

type Filter = { account: string; status: 'pending' | 'unread' | 'all'; selected?: string };
const defaultFilter: Filter = { account: '', status: 'all' };

export function CommentInbox({ groupId, accounts, accountName, destination, onOpenThread, onConfirm, result, sending }: ReplyControls & {
  groupId: string; accounts: Binding[]; accountName: (binding: Binding) => string;
  destination?: CommentDestination; onOpenThread: (destination: OriginalComment) => void;
}) {
  const resultSnapshot = useCommentSnapshot<InboxSnapshot>('comments.inboxSnapshot', groupId);
  const snapshots = resultSnapshot?.data;
  const [filters, setFilters] = useState<Record<string, Filter>>({});
  const [requestError, setRequestError] = useState<{ groupId: string; message: string }>();
  const [sourceError, setSourceError] = useState<{ key: string; message: string }>();
  const [openingSource, setOpeningSource] = useState<string>();
  const [beginReply, setBeginReply] = useState<{ key: string; version: number }>();
  const handled = useRef<CommentDestination>(undefined);
  const filter = filters[groupId] ?? defaultFilter;
  const progress = Object.values(snapshots ?? {}).map(snapshot => snapshot.sync).filter(run => run?.running);
  const syncing = progress.length > 0;

  function updateFilter(change: Partial<Filter>) {
    setFilters(current => ({ ...current, [groupId]: { ...(current[groupId] ?? defaultFilter), ...change } }));
  }

  async function sync() {
    if (!accounts.length || syncing) return;
    setRequestError(undefined);
    try {
      await window.publisher.request('comments.inbox', { group_id: groupId });
    } catch (error) {
      setRequestError({ groupId, message: errorMessage(error) });
    }
  }

  const selectedAccount = accounts.some(account => account.id === filter.account) ? filter.account : '';
  const visibleAccounts = accounts.filter(binding => !selectedAccount || binding.id === selectedAccount);
  const rows = visibleAccounts.flatMap(binding => (snapshots?.[binding.id]?.entries ?? []).map(entry => {
    const scope: NoteScope = { group_id: groupId, binding_id: binding.id, note_id: entry.note_id };
    return { ...entry, binding, scope, key: `${binding.id}:${entry.note_id}:${entry.comment.id}`,
      reply: currentReply(scope, entry.comment, result) };
  })).sort((a, b) => commentTimestamp(b.comment.created_at) - commentTimestamp(a.comment.created_at));
  const visible = rows.filter(row => filter.status === 'all' ||
    (filter.status === 'unread' ? row.comment.unread
      : !row.comment.replied && (!row.reply || row.reply.status === 'failed')));
  const selected = rows.find(row => row.key === filter.selected);
  const syncErrors = visibleAccounts.some(binding => snapshots?.[binding.id]?.sync?.error);
  const updated = Math.max(0, ...visibleAccounts.map(binding => snapshots?.[binding.id]?.updated_at ?? 0));

  function openMessage(row: typeof rows[number], edit = false) {
    updateFilter({ selected: row.key });
    if (edit) setBeginReply(current => ({ key: row.key, version: (current?.version ?? 0) + 1 }));
    if (row.comment.unread) void markCommentRead(row.scope, row.comment.id)
      .catch(error => setRequestError({ groupId, message: errorMessage(error) }));
  }

  async function openSource(row: typeof rows[number]) {
    const destination = { ...row.scope, comment_id: row.comment.id };
    if (row.open_target === 'full') {
      onOpenThread({ ...destination, note_title: row.note_title });
      return;
    }
    setSourceError(undefined);
    setOpeningSource(row.key);
    try {
      await window.publisher.openCommentSource(destination);
    } catch (cause) {
      setSourceError({ key: row.key, message: errorMessage(cause) });
    } finally {
      setOpeningSource(current => current === row.key ? undefined : current);
    }
  }

  useEffect(() => {
    if (!destination || handled.current === destination) return;
    if (!snapshots?.[destination.binding_id]?.entries.some(entry =>
      entry.note_id === destination.note_id && entry.comment.id === destination.comment_id)) return;
    handled.current = destination;
    const key = `${destination.binding_id}:${destination.note_id}:${destination.comment_id}`;
    updateFilter({ account: '', status: 'all', selected: key });
    void markCommentRead(destination, destination.comment_id)
      .catch(error => setRequestError({ groupId, message: errorMessage(error) }));
  }, [destination, snapshots, groupId]);

  return <div className="received-comments">
    <div className="received-comment-layout" data-detail-open={!!selected}>
    <Card className="workspace-panel comment-panel received-comment-list">
      <CardHeader className="shrink-0 gap-3 max-sm:gap-2">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
          <CardTitle>消息收件箱</CardTitle>
          <Button type="button" variant="outline" size="sm" disabled={!accounts.length || !!syncing}
            onClick={() => void sync()}>
            <RefreshCw data-icon="inline-start" className={syncing ? 'animate-spin' : ''} />
            {syncing ? '同步中' : '同步收到的评论'}
          </Button>
        </div>
        <CardDescription className="max-sm:hidden">
          {updated ? `最近同步 ${commentSyncTime(updated)}` : '收取新留言和别人对你的追回复。'}
        </CardDescription>
        {accounts.length > 0 && <div className="flex flex-wrap items-center gap-2">
          <Tabs value={filter.status} onValueChange={value => updateFilter({ status: value as Filter['status'], selected: undefined })}>
            <TabsList aria-label="评论状态">
              <TabsTrigger value="pending" title="根据本机记录和本次读取到的站内回复判断">待回复</TabsTrigger>
              <TabsTrigger value="unread">未读</TabsTrigger>
              <TabsTrigger value="all">全部</TabsTrigger>
            </TabsList>
          </Tabs>
          <WorkspaceSelect label="筛选收件箱账号" value={selectedAccount} className="w-44 min-w-28 max-w-full max-sm:flex-1"
            options={[{ value: '', label: '全部账号' }, ...accounts.map(binding => ({ value: binding.id, label: accountName(binding) }))]}
            onValueChange={account => updateFilter({ account, selected: undefined })} />
        </div>}
      </CardHeader>
      <CardContent role="region" aria-label="收件箱评论列表" tabIndex={0} className="comment-list-scroll grid gap-1">
        {resultSnapshot?.error && <ErrorNotice>{resultSnapshot.error}</ErrorNotice>}
        {requestError?.groupId === groupId && <ErrorNotice>{requestError.message}</ErrorNotice>}
        {visibleAccounts.map(binding => {
          const snapshot = snapshots?.[binding.id];
          return snapshot?.sync?.error ? <ErrorNotice key={binding.id}>{accountName(binding)} · {snapshot.sync.error}</ErrorNotice> : null;
        })}
        {!visible.length && <p className="py-6 text-center text-sm text-muted-foreground">
          {!accounts.length ? '在平台账号页绑定小红书后即可同步评论。' : syncing ? '正在读取各账号的评论…'
            : syncErrors ? '部分内容未能读取，可重新同步。' : updated || rows.length
              ? ({ pending: '当前没有待回复的评论。', unread: '当前没有未读评论。', all: '没有读到评论。' }[filter.status])
              : '同步后选择一条评论查看详情。'}
        </p>}
        {visible.map(row => <div key={row.key} data-slot="received-comment-row" data-selected={row.key === selected?.key}
          className="grid w-full min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-1 rounded-lg pr-1.5 hover:bg-muted/55 data-[selected=true]:bg-secondary">
          <Button type="button" aria-pressed={row.key === selected?.key}
            variant="ghost" onClick={() => openMessage(row)}
            className="flex h-auto w-full min-w-0 flex-col items-start justify-start gap-1 whitespace-normal p-2.5 text-left hover:bg-transparent">
            <span className="flex w-full min-w-0 items-center gap-2">
              <span className="min-w-0 flex-1 truncate" data-slot="received-comment-author">{row.comment.author || '小红书用户'}</span>
              {row.comment.unread && <span className="size-1.5 shrink-0 rounded-full bg-primary" aria-label="未读" />}
              <span className="shrink-0 text-xs text-muted-foreground">{row.kind === 'follow_up' ? '追回复' : '新留言'}</span>
              {row.reply && <Badge variant="outline">{replyLabels[row.reply.status]}</Badge>}
            </span>
            <span className="line-clamp-2 w-full break-words text-sm">{row.comment.body || '此评论没有可显示的文字。'}</span>
            <span className="w-full truncate text-xs text-muted-foreground">
              {accountName(row.binding)} · {row.note_title}{row.comment.created_at !== null && ` · ${commentTime(row.comment.created_at)}`}
            </span>
          </Button>
          <Button type="button" variant="ghost" size="sm" className="justify-self-end" disabled={sending}
            aria-label={`回复 ${row.comment.author || '小红书用户'}`} onClick={() => openMessage(row, true)}>回复</Button>
        </div>)}
      </CardContent>
    </Card>
    {selected && <Card className="workspace-panel comment-panel received-comment-detail">
      <CardHeader className="flex shrink-0 flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2">
          <Button type="button" variant="ghost" size="icon-sm" aria-label="返回消息列表" title="返回消息列表"
            onClick={() => { setBeginReply(undefined); updateFilter({ selected: undefined }); }}><ArrowLeft /></Button>
          <div className="min-w-0 space-y-1">
            <CardTitle className="line-clamp-2 break-words" title={selected.note_title}>{selected.note_title}</CardTitle>
            <CardDescription>小红书 · {accountName(selected.binding)}</CardDescription>
          </div>
        </div>
        <Button type="button" variant="outline" size="sm" disabled={openingSource === selected.key}
          onClick={() => void openSource(selected)}>
          {selected.open_target === 'full' ? '查看原帖评论' : '在网页查看原帖'}
          <ArrowUpRight data-icon="inline-end" />
        </Button>
      </CardHeader>
      <CardContent role="region" aria-label="评论详情" tabIndex={0} className="comment-list-scroll grid gap-3">
        {sourceError?.key === selected.key && <ErrorNotice>{sourceError.message}</ErrorNotice>}
        <CommentThread key={selected.key} comments={[selected.comment]} scope={selected.scope} account={accountName(selected.binding)}
          received beginReply={beginReply?.key === selected.key ? beginReply.version : undefined}
          onConfirm={onConfirm} result={result} sending={sending} />
      </CardContent>
    </Card>}
    </div>
  </div>;
}
