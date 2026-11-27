import type { SynthesisSource } from './publisher/video-materials';

export type Platform = string;
export type Kind = 'video' | 'image' | 'article';
export type PlatformRegion = 'domestic' | 'international';
export type AccentTheme = 'neutral' | 'sky' | 'cyan' | 'violet';
export type CommentMode = 'notes' | 'inbox';
export type CommentDestination = { group_id: string; binding_id: string; note_id: string; comment_id: string };
export type CommentSettings = { directory: string; default_directory: string; notifications: boolean; error: string; unread: number };
export type PlatformInfo = { id: Platform; label: string; kinds: Kind[]; mode: 'browser' | 'api' | 'custom_browser'; category: string; note: string; title_limit: number };
export type GroupMode = 'regular' | 'custom';
export type Group = { id: string; name: string; mode: GroupMode };
export type Binding = {
  id: string;
  group_id: string;
  platform: Platform;
  slot: number;
  label: string;
  login_status: 'unbound' | 'ready' | 'saved' | 'attention';
  checked_at: string | null;
};
export type TaskStatus = 'scheduled' | 'missed' | 'canceled' | 'queued' | 'running' | 'submitting' | 'verifying' | 'submitted' | 'draft_ready' | 'needs_review' | 'action_required' | 'failed';
export type Task = {
  id: string;
  batch_id: string;
  binding_id: string;
  group_id: string;
  platform: Platform;
  slot: number;
  target_label: string;
  title: string;
  kind: Kind;
  media_name: string;
  status: TaskStatus;
  detail: string;
  receipt: string | null;
  created_at: string;
  updated_at: string;
  scheduled_at: number | null;
  active: 0 | 1;
};
export type State = {
  groups: Group[]; active_group_id: string; platform_region: PlatformRegion;
  accent_theme: AccentTheme;
  comment_mode: CommentMode;
  comment_accounts: Record<string, string>;
  bindings: Binding[]; tasks: Task[]; platforms: PlatformInfo[];
};

export type PublishContent = { title: string; description: string; tags: string; cover: string };
export type Draft = PublishContent & {
  files: string[];
  declaration: string;
  targets: string[];
  options: Record<string, string>;
  overrides: Record<string, Partial<PublishContent>>;
};

export type UpdateStatus = {
  current: string;
  phase: 'idle' | 'unsupported' | 'checking' | 'current' | 'available' | 'downloading' | 'ready' | 'error';
  available: string | null;
  progress: number;
  error: string;
};

declare global {
  interface Window {
    publisher: {
      request<T = void>(method: string, args?: Record<string, unknown>): Promise<T>;
      selectMedia(kind: 'video' | 'image' | 'cover'): Promise<string[]>;
      materialAction<T = void>(action: 'select' | 'directory' | 'reveal' | 'publish' | 'preview' | 'export-caption' | 'synthesize' | 'import-srt' | 'import-word',
        args?: { id: string; source?: SynthesisSource }): Promise<T>;
      subscribeMaterials(callback: () => void): () => void;
      selectCommentCache(): Promise<string | null>;
      takeCommentDestination(): Promise<CommentDestination | null>;
      openCommentSource(destination: CommentDestination): Promise<void>;
      openDouyinMessages(kind: 'private' | 'comments'): Promise<void>;
      douyinPane(action: 'open' | 'close' | 'layout' | 'reload' | 'notifications', args: Record<string, unknown>): Promise<void>;
      subscribeDouyinPane(callback: (token: string, status: 'loading' | 'ready' | 'error') => void): () => void;
      subscribeCommentDestination(callback: () => void): () => void;
      subscribeComments(callback: (groupId: string) => void): () => void;
      filePath(file: File): string;
      mediaPreview(path: string): Promise<string | null>;
      update(action: 'status' | 'check' | 'download' | 'install'): Promise<UpdateStatus>;
      subscribeUpdates(callback: (status: UpdateStatus) => void): () => void;
      subscribe(callback: () => void): () => void;
    };
  }
}
