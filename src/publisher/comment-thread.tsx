import { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronUp, LoaderCircle } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { errorMessage } from './model';
import { ErrorNotice, WorkspaceField } from './workspace-ui';
import { markCommentRead } from './comment-data';

export type ReplyStatus = { status: 'sending' | 'sent' | 'failed' | 'needs_review'; detail: string };
export type NoteComment = {
  id: string; author: string; body: string; created_at: number | null; reply: ReplyStatus | null; unread: boolean;
  by_owner?: boolean; replied?: boolean; reply_to?: string; ip_location?: string;
  children?: NoteComment[]; children_count?: number; children_more?: boolean;
};
export type NoteScope = { group_id: string; binding_id: string; note_id: string };
type Confirmation = {
  confirmation: string; account: string; group: string; note: string; author: string; comment: string; body: string;
  previous_attempt_unknown?: boolean;
};
export type ReplyTarget = { scope: NoteScope; commentId: string; confirmation: Confirmation };
export type SendResult = { target: ReplyTarget; reply: ReplyStatus };
export type ReplyControls = { onConfirm: (target: ReplyTarget) => void; result: SendResult | null; sending: boolean };

export const replyLabels = { sending: '正在发送', sent: '已回复', failed: '发送失败', needs_review: '待核对' };

export function commentTimestamp(value: number | null) {
  if (value === null) return 0;
  return value > 100_000_000_000 ? value : value * 1000;
}

export function commentTime(value: number | null) {
  if (value === null) return '';
  const date = new Date(commentTimestamp(value));
  if (Number.isNaN(date.getTime())) return '';
  const now = new Date();
  const minutes = Math.max(0, Math.floor((now.getTime() - date.getTime()) / 60_000));
  if (!minutes) return '刚刚';
  if (minutes < 60) return `${minutes} 分钟前`;
  if (date.toDateString() === now.toDateString()) return `${Math.floor(minutes / 60)} 小时前`;
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return date.getFullYear() === now.getFullYear() ? `${month}-${day}` : `${date.getFullYear()}-${month}-${day}`;
}

export function currentReply(scope: NoteScope, comment: NoteComment, result: SendResult | null) {
  if (!result) return comment.reply;
  const { target } = result;
  return target.commentId === comment.id && target.scope.group_id === scope.group_id &&
    target.scope.binding_id === scope.binding_id && target.scope.note_id === scope.note_id ? result.reply : comment.reply;
}

export function CommentThread({ comments, account, scope, onConfirm, result, sending, received = false, beginReply, focusComment }: ReplyControls & {
  comments: NoteComment[]; account: string; scope: NoteScope; received?: boolean; beginReply?: number; focusComment?: string;
}) {
  const [answer, setAnswer] = useState<{ id: string; rootId: string; text: string }>();
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [childErrors, setChildErrors] = useState<Record<string, string>>({});
  const active = useRef(false);
  const expandedFocus = useRef<string>(undefined);

  useEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);

  useEffect(() => {
    if (!beginReply || !received || !comments[0]) return;
    const { id } = comments[0];
    setAnswer({ id, rootId: id, text: '' });
  }, [beginReply, received, comments[0]?.id]);

  useEffect(() => {
    if (!focusComment || expandedFocus.current === focusComment) return;
    const parent = comments.find(comment => comment.children?.some(child => child.id === focusComment));
    if (parent) {
      expandedFocus.current = focusComment;
      setExpanded(current => current[parent.id] ? current : { ...current, [parent.id]: true });
    }
  }, [comments, focusComment]);

  useEffect(() => {
    if (!result || !['sent', 'needs_review'].includes(result.reply.status)) return;
    const { target } = result;
    if (target.scope.group_id !== scope.group_id || target.scope.binding_id !== scope.binding_id || target.scope.note_id !== scope.note_id) return;
    setAnswer(current => current?.id === target.commentId && current.text.trim() === target.confirmation.body ? undefined : current);
  }, [result, scope.group_id, scope.binding_id, scope.note_id]);

  async function review() {
    if (!answer?.text.trim() || preparing || sending) return;
    setPreparing(true);
    setError('');
    try {
      const confirmation = await window.publisher.request<Confirmation>('comments.prepare', {
        ...scope, comment_id: answer.id, root_comment_id: answer.rootId, received, body: answer.text,
      });
      if (active.current) onConfirm({ scope, commentId: answer.id, confirmation });
    } catch (cause) {
      if (active.current) setError(errorMessage(cause));
    } finally {
      if (active.current) setPreparing(false);
    }
  }

  async function loadChildren(id: string) {
    if (loading[id]) return;
    setLoading(current => ({ ...current, [id]: true }));
    setChildErrors(current => ({ ...current, [id]: '' }));
    try {
      await window.publisher.request('comments.children', { ...scope, comment_id: id });
    } catch (cause) {
      if (active.current) setChildErrors(current => ({ ...current, [id]: errorMessage(cause) }));
    } finally {
      if (active.current) setLoading(current => ({ ...current, [id]: false }));
    }
  }

  function renderComment(comment: NoteComment, rootId: string) {
    const reply = currentReply(scope, comment, result);
    return <>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          <span className="font-medium">{comment.author || '小红书用户'}</span>
          {comment.by_owner && <Badge variant="secondary">作者</Badge>}
          {comment.reply_to && <span className="text-xs text-muted-foreground">回复 {comment.reply_to}</span>}
          {comment.unread && <Button type="button" size="xs" variant="ghost" className="ml-auto text-primary"
            aria-label="将评论标为已读" onClick={() => void markCommentRead(scope, comment.id).catch(cause => setError(errorMessage(cause)))}>
            未读
          </Button>}
        </div>
        <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">{comment.body || '此评论没有可显示的文字。'}</p>
        <div className="flex min-h-7 items-center gap-2 text-xs text-muted-foreground">
          <span>{commentTime(comment.created_at)}</span>
          {comment.ip_location && <span>{comment.ip_location}</span>}
          {reply && <Badge variant={reply.status === 'failed' ? 'outline' : 'secondary'} title={reply.detail}>{replyLabels[reply.status]}</Badge>}
          {answer?.id !== comment.id && <Button variant="ghost" type="button" size="sm" className="ml-auto"
            disabled={preparing || sending || reply?.status === 'sending'}
            onClick={() => { setError(''); setAnswer({ id: comment.id, rootId, text: '' }); }}>
            {comment.replied || reply?.status === 'sent' ? '继续回复' : '回复'}
          </Button>}
        </div>
        {reply && ['failed', 'needs_review'].includes(reply.status) && <p className="text-xs text-muted-foreground">{reply.detail}</p>}
        {answer?.id === comment.id ? <div className="grid gap-2 pt-1">
          <WorkspaceField label={`以「${account}」回复`}>
            <Textarea placeholder="输入回复" value={answer.text} maxLength={500} disabled={preparing || sending}
              onChange={event => setAnswer({ ...answer, text: event.target.value })} />
          </WorkspaceField>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" disabled={preparing} onClick={() => setAnswer(undefined)}>取消</Button>
            <Button size="sm" disabled={preparing || sending || !answer.text.trim()} onClick={() => void review()}>核对回复</Button>
          </div>
        </div> : null}
    </>;
  }

  return <>
    {error && <ErrorNotice>{error}</ErrorNotice>}
    {comments.map(comment => {
      const children = comment.children ?? [];
      const count = comment.children_count ?? children.length;
      const isExpanded = !!expanded[comment.id];
      const childId = `comment-replies-${comment.id}`;
      return <article key={comment.id} id={`comment-thread-${comment.id}`} tabIndex={focusComment === comment.id ? -1 : undefined}
        className={received ? 'grid gap-1.5 rounded-lg bg-muted/45 p-3' : 'grid gap-1.5 border-b border-border/70 px-1 pb-3 last:border-b-0'}>
        {renderComment(comment, comment.id)}
        {!received && (count > 0 || comment.children_more) && <Button variant="ghost" type="button" size="sm" className="justify-self-start"
          aria-expanded={isExpanded} aria-controls={childId}
          onClick={() => {
            setExpanded(current => ({ ...current, [comment.id]: !isExpanded }));
            if (!isExpanded && !children.length && comment.children_more) void loadChildren(comment.id);
          }}>
          {isExpanded ? <ChevronUp data-icon="inline-start" /> : <ChevronDown data-icon="inline-start" />}
          {isExpanded ? '收起回复' : count ? `展开 ${count} 条回复` : '展开回复'}
        </Button>}
        {!received && <div id={childId} hidden={!isExpanded}>
          {isExpanded && <div className="ml-2 grid gap-3 border-l border-border pl-3">
            {children.map(child => <article key={child.id} id={`comment-thread-${child.id}`}
              tabIndex={focusComment === child.id ? -1 : undefined} className="grid gap-1.5 py-1">
              {renderComment(child, comment.id)}
            </article>)}
            {childErrors[comment.id] && <ErrorNotice>{childErrors[comment.id]}</ErrorNotice>}
            {comment.children_more && <Button type="button" variant="ghost" size="sm" className="justify-self-start"
              disabled={loading[comment.id]} onClick={() => void loadChildren(comment.id)}>
              {loading[comment.id] && <LoaderCircle className="animate-spin" data-icon="inline-start" />}
              {loading[comment.id] ? '正在加载回复…' : '加载更多回复'}
            </Button>}
          </div>}
        </div>}
      </article>;
    })}
  </>;
}
