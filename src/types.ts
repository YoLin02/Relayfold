export type Platform = string;
export type Kind = 'video' | 'image' | 'article';
export type PlatformRegion = 'domestic' | 'international';
export type AccentTheme = 'neutral' | 'sky' | 'cyan' | 'violet';
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
      filePath(file: File): string;
      mediaPreview(path: string): Promise<string | null>;
      update(action: 'status' | 'check' | 'download' | 'install'): Promise<UpdateStatus>;
      subscribeUpdates(callback: (status: UpdateStatus) => void): () => void;
      subscribe(callback: () => void): () => void;
    };
  }
}
