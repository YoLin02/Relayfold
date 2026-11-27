import { AudioLines, Captions, Download, FileCheck2, Film, History, Image, LayoutDashboard, MessageSquareText, Send, UserRound, Video } from 'lucide-react';
import type { Binding, Draft, Group, GroupMode, Kind, PlatformRegion, PublishContent, Task, TaskStatus } from '@/types';

export const contentKinds = {
  video: { label: '视频', extension: /\.(mp4|mov)$/i, maxFiles: 1, formats: 'MP4、MOV', choose: '选择本地视频' },
  image: { label: '图文', extension: /\.(jpg|jpeg|png|webp)$/i, maxFiles: 18, formats: 'JPG、PNG、WebP · 最多 18 张', choose: '选择本地图片' },
  article: { label: '文章', extension: /\.(jpg|jpeg|png|webp)$/i, maxFiles: 18, formats: 'JPG、PNG、WebP · 最多 18 张', choose: '选择本地图片' },
} satisfies Record<Kind, { label: string; extension: RegExp; maxFiles: number; formats: string; choose: string }>;

export const publishTabs = [
  { id: 'video', label: '视频', icon: Video }, { id: 'image', label: '图文', icon: Image },
] as const;
export type PublishTab = typeof publishTabs[number]['id'];
export const graphicFormats = [{ id: 'image', label: '多图' }, { id: 'article', label: '长文章' }] as const;
export type GraphicFormat = typeof graphicFormats[number]['id'];
export const accountCategories = [
  { id: 'all', label: '全部' }, { id: 'video', label: '视频' }, { id: 'graphic', label: '图文' },
] as const;
export type AccountCategory = typeof accountCategories[number]['id'];
export const accountStates = [
  { id: 'all', label: '全部状态' }, { id: 'bound', label: '已绑定' },
  { id: 'unbound', label: '待绑定' }, { id: 'attention', label: '需重新验证' },
] as const;
export type AccountState = typeof accountStates[number]['id'];
export const groupModes = {
  regular: { label: '常规组', description: '一个内容 IP 对应一个组，每个平台一个账号。' },
  custom: { label: '自定义组', description: '自己选择平台，同一个平台可添加多个账号。' },
} satisfies Record<GroupMode, { label: string; description: string }>;
export const maxAccountsPerAdd = 100;
export const platformRegions = {
  domestic: { label: '国内平台', category: '国内', examples: '抖音、小红书、知乎等' },
  international: { label: '国外平台', category: '海外', examples: 'TikTok、YouTube、Medium 等' },
} satisfies Record<PlatformRegion, { label: string; category: string; examples: string }>;

export const workbench = { id: 'workbench', label: '工作台', icon: LayoutDashboard } as const;
export const editingTools = [
  { id: 'video-download', label: '视频下载', icon: Download },
  { id: 'subtitle-extract', label: '提取字幕', icon: Captions },
  { id: 'script-review', label: '脚本核对', icon: FileCheck2 },
  { id: 'subtitle-synthesis', label: '合成字幕', icon: Film },
  { id: 'voice', label: '配音与音色', icon: AudioLines },
] as const;
export const publishingTools = [
  { id: 'publish', label: '新建发布', icon: Send },
  { id: 'accounts', label: '平台账号', icon: UserRound },
  { id: 'history', label: '发布记录', icon: History },
  { id: 'comments', label: '消息', icon: MessageSquareText },
] as const;
export const navigation = [workbench, ...editingTools, ...publishingTools] as const;
export type WorkspaceView = typeof navigation[number]['id'];
export type View = WorkspaceView | 'settings';

export const emptyDraft: Draft = {
  files: [], title: '', description: '', tags: '', cover: '', declaration: '', targets: [], options: {}, overrides: {},
};
export const openStatuses: TaskStatus[] = ['queued', 'running', 'submitting', 'verifying'];
export const loginLabels = {
  unbound: ['待绑定', 'neutral'], ready: ['已绑定', 'green'], saved: ['会话已保存', 'green'], attention: ['需重新验证', 'amber'],
} as const satisfies Record<Binding['login_status'], readonly [string, string]>;
export const taskLabels = {
  scheduled: ['待定时', 'neutral'], missed: ['已错过', 'amber'], canceled: ['已取消', 'neutral'],
  queued: ['排队中', 'neutral'], running: ['准备上传', 'neutral'], submitting: ['正在提交', 'neutral'],
  verifying: ['核对作品中', 'neutral'],
  submitted: ['已提交', 'green'], draft_ready: ['已存草稿', 'neutral'], needs_review: ['待核对', 'amber'],
  action_required: ['需验证账号', 'amber'], failed: ['失败', 'red'],
} as const satisfies Record<TaskStatus, readonly [string, string]>;

export const declarations = ['无需添加自主声明', '内容由AI生成', '内容为个人观点或见解', '内容为转载信息', '内容含营销推广信息', '虚构演绎，仅供娱乐'];
export const customPlatforms = new Set(['douyin', 'xiaohongshu']);
export const isConnected = (binding: Binding) => binding.login_status === 'ready' || binding.login_status === 'saved';
export const fileName = (path: string) => path.split(/[/\\]/).at(-1) || path;
export const parseTags = (value: string) => [...new Set(value.split(/[,，、\r\n]+/).map(
  tag => tag.trim().replace(/^[#＃]+|[#＃]+$/g, '').trim(),
).filter(Boolean))];
export const textLength = (value: string) => Array.from(value).length;
export const errorMessage = (error: unknown) => String(error instanceof Error ? error.message : error)
  .replace(/^Error invoking remote method '[^']+': Error: /, '');

export type Destination = { binding: Binding; name: string; custom: boolean; content: PublishContent };
export type Confirmation =
  | { type: 'publish'; group: Group; kind: Kind; draft: Draft; destinations: Destination[]; scheduledFor?: string }
  | { type: 'schedule-change'; task: Task; scheduledFor: string }
  | { type: 'schedule-cancel'; task: Task }
  | { type: 'review'; task: Task; result: 'found' | 'missing' }
  | { type: 'delete-group'; group: Group }
  | { type: 'delete-account'; binding: Binding }
  | { type: 'delete-task'; task: Task }
  | { type: 'replace'; binding: Binding };

export function effectiveContent(draft: Draft, binding: Binding): PublishContent {
  const { title, description, tags, cover } = draft;
  return customPlatforms.has(binding.platform)
    ? { title, description, tags, cover, ...draft.overrides[binding.id] }
    : { title, description, tags: '', cover: '' };
}

export function coverName(kind: Kind, value: string, files: string[]) {
  if (value) return fileName(value);
  return kind === 'image' && files.length ? `首图 · ${fileName(files[0])}` : '平台自动封面';
}

type OptionField = { key: string; label: string; placeholder?: string; choices?: readonly { value: string; label: string }[]; required?: boolean; when?: [string, string] };
export const platformOptions: Record<string, readonly OptionField[]> = {
  bilibili: [
    { key: 'bili_category', label: '分区', placeholder: '输入创作中心显示的分区名称', required: true },
    { key: 'bili_source', label: '稿件类型', choices: ['自制', '转载'].map(value => ({ value, label: value })), required: true },
    { key: 'bili_origin', label: '转载来源', when: ['bili_source', '转载'], required: true },
    { key: 'bili_tags', label: '标签', placeholder: '用逗号分隔，最多 10 个', required: true },
  ],
  youtube: [
    { key: 'youtube_visibility', label: '可见范围', choices: [{value: 'PRIVATE', label: '私密'}, {value: 'UNLISTED', label: '不公开列出'}, {value: 'PUBLIC', label: '公开'}], required: true },
    { key: 'youtube_kids', label: '面向儿童', choices: [{value: 'yes', label: '是'}, {value: 'no', label: '否'}], required: true },
  ],
  reddit: [{ key: 'reddit_target', label: 'Reddit 目标', placeholder: 'r/example 或 user/example', required: true }],
  csdn: [{ key: 'csdn_keywords', label: 'CSDN 标签', placeholder: '用逗号分隔' }],
};
