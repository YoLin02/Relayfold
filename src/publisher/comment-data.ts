import { useEffect, useState } from 'react';
import type { CommentDestination } from '@/types';
import type { NoteComment, NoteScope } from './comment-thread';
import { errorMessage } from './model';

export type Note = { id: string; title: string; has_cover: boolean; unread: number };
export type OriginalComment = CommentDestination & { note_title: string };
export type CommentSync = { running: boolean; done: number; total: number; error: string };
export type CommentSnapshot = {
  notes: Note[] | null;
  notes_at: number | null;
  note: Note | null;
  deleted: boolean;
  thread: { comments: NoteComment[]; has_more: boolean; updated_at: number } | null;
  notes_sync: CommentSync | null;
  thread_sync: CommentSync | null;
};
export type InboxSnapshot = Record<string, {
  entries: {
    note_id: string; note_title: string; kind: 'comment' | 'follow_up'; open_target: 'full' | 'web'; comment: NoteComment;
  }[];
  updated_at: number | null;
  sync: CommentSync | null;
}>;

export function useCommentSnapshot<T>(method: 'comments.snapshot' | 'comments.inboxSnapshot', groupId: string, bindingId?: string, noteId?: string) {
  const key = JSON.stringify([method, groupId, bindingId, noteId]);
  const [result, setResult] = useState<{ key: string; data?: T; error: string }>();
  useEffect(() => {
    let active = true;
    let revision = 0;
    function load() {
      const current = ++revision;
      void window.publisher.request<T>(method, { group_id: groupId, binding_id: bindingId, note_id: noteId })
        .then(data => {
          if (active && current === revision) setResult({ key, data, error: '' });
        }).catch(error => {
          if (active && current === revision) setResult(previous => ({
            key, data: previous?.key === key ? previous.data : undefined, error: errorMessage(error),
          }));
        });
    }
    const unsubscribe = window.publisher.subscribeComments(group => { if (group === groupId) load(); });
    load();
    return () => { active = false; unsubscribe(); };
  }, [method, key, groupId, bindingId, noteId]);
  return result?.key === key ? result : undefined;
}

export function commentSyncTime(seconds: number) {
  return new Date(seconds * 1000).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export async function markCommentRead(scope: NoteScope, commentId: string) {
  await window.publisher.request('comments.read', { ...scope, comment_id: commentId });
}
