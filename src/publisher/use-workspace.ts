import { useCallback, useEffect, useReducer, useRef } from 'react';
import type { AccentTheme, Binding, CommentDestination, CommentSettings, Draft, Group, GroupMode, Kind, PlatformInfo, PlatformRegion, PublishContent, State } from '@/types';
import { accentThemes } from './appearance';
import { defaultHistoryFilter, type HistoryFilter } from './history';
import { scheduleTimestamp } from './schedule';
import type { CaptionDraft, VideoProcessingState } from './video-materials';
import {
  contentKinds, customPlatforms, effectiveContent, emptyDraft, errorMessage, graphicFormats, isConnected, openStatuses,
  parseTags, platformOptions, platformRegions, textLength,
  type AccountCategory, type AccountState, type Confirmation, type Destination, type GraphicFormat,
  type PublishTab, type View,
} from './model';

type AccountDialog = { binding: Binding; label: string; settings: Record<string, string>; opened: boolean };
type WorkspaceState = {
  data?: State;
  view: View;
  publishTab: PublishTab;
  graphicFormat: GraphicFormat;
  drafts: Record<string, Draft>;
  videoProcessing: VideoProcessingState;
  category: AccountCategory;
  accountState: AccountState;
  search: string;
  historyFilter: HistoryFilter;
  utility: 'help' | 'search' | null;
  groupEditor: { name: string; mode: GroupMode; group?: Group } | null;
  accountAdder?: { groupId: string; platform: string; count: string };
  settingsRegion: PlatformRegion | null;
  settingsTheme: AccentTheme | null;
  commentSettings?: CommentSettings;
  commentDestination?: CommentDestination;
  queuedCommentDestination?: CommentDestination;
  account?: AccountDialog;
  confirmation?: Confirmation;
  pending: string | null;
  error: string;
  connectionError: string;
  notice: string;
};
const initial: WorkspaceState = {
  view: 'publish', publishTab: 'video', graphicFormat: 'image', drafts: {},
  videoProcessing: { tool: 'extract' },
  category: 'all', accountState: 'all', search: '', utility: null, historyFilter: defaultHistoryFilter,
  groupEditor: null, settingsRegion: null, settingsTheme: null,
  pending: null, error: '', connectionError: '', notice: '',
};
type Update = Partial<WorkspaceState> | ((current: WorkspaceState) => Partial<WorkspaceState>);
type DraftUpdate = Partial<Draft> | ((current: Draft) => Partial<Draft>);

function workspaceReducer(current: WorkspaceState, update: Update): WorkspaceState {
  return { ...current, ...(typeof update === 'function' ? update(current) : update) };
}

function checkContent(destinations: Destination[], kind: Kind, platforms: Record<string, PlatformInfo>) {
  return destinations.flatMap(({ binding, content, name }) => {
    const limit = platforms[binding.platform].title_limit;
    const tags = parseTags(content.tags);
    if (textLength(content.title.trim()) > limit) return [`${name}标题最多 ${limit} 个字符。`];
    if (tags.length > 10 || tags.some(tag => textLength(tag) > 30 || /[#＃]/.test(tag))) {
      return [`${name}最多 10 个标签，每个最多 30 个字符。`];
    }
    const length = textLength(content.description.trim()) + tags.reduce((sum, tag) => sum + textLength(tag) + 2, 0);
    return length > (kind === 'article' ? 50000 : 1000) ? [`${name}正文和标签总长度超出限制。`] : [];
  });
}

export function usePublisherWorkspace() {
  const [state, update] = useReducer(workspaceReducer, initial);
  const requestVersion = useRef(0);
  const commentSettingsVersion = useRef(0);
  const actionLock = useRef(false);
  const captionDrafts = useRef(new Map<string, CaptionDraft>());

  const refresh = useCallback(async () => {
    const version = ++requestVersion.current;
    try {
      const data = await window.publisher.request<State>('state');
      if (version === requestVersion.current) update({ data, connectionError: '' });
    } catch (error) {
      if (version === requestVersion.current) update({ connectionError: errorMessage(error) });
    }
  }, []);

  useEffect(() => {
    void refresh();
    return window.publisher.subscribe(() => void refresh());
  }, [refresh]);

  const refreshCommentSettings = useCallback(async () => {
    const version = ++commentSettingsVersion.current;
    try {
      const commentSettings = await window.publisher.request<CommentSettings>('comments.summary');
      if (version === commentSettingsVersion.current) update({ commentSettings });
    } catch {
      // The base workspace can still load independently of the comment cache.
    }
  }, []);

  useEffect(() => {
    void refreshCommentSettings();
    const takeDestination = () => {
      void window.publisher.takeCommentDestination().then(destination => {
        if (destination) update({ queuedCommentDestination: destination });
      }).catch(() => {});
    };
    takeDestination();
    const unsubscribe = window.publisher.subscribe(() => void refreshCommentSettings());
    const unsubscribeComments = window.publisher.subscribeComments(() => void refreshCommentSettings());
    const unsubscribeDestination = window.publisher.subscribeCommentDestination(takeDestination);
    return () => { unsubscribe(); unsubscribeComments(); unsubscribeDestination(); };
  }, [refreshCommentSettings]);

  async function run(key: string, operation: () => Promise<void>, onSuccess?: () => void) {
    if (actionLock.current) return;
    actionLock.current = true;
    update({ pending: key, error: '', notice: '' });
    try {
      await operation();
      onSuccess?.();
      await refresh();
    } catch (error) {
      update({ error: errorMessage(error) });
    } finally {
      actionLock.current = false;
      update({ pending: null });
    }
  }

  const { data, search, category, accountState, pending, connectionError } = state;
  const groups = data?.groups || [];
  const group = groups.find(item => item.id === data?.active_group_id);
  const destination = state.queuedCommentDestination;
  useEffect(() => {
    if (!destination || !data || pending || actionLock.current) return;
    const valid = data.bindings.some(binding => binding.id === destination.binding_id &&
      binding.group_id === destination.group_id && isConnected(binding));
    if (!valid) {
      update({ queuedCommentDestination: undefined });
      return;
    }
    const show = () => update({
      queuedCommentDestination: undefined, commentDestination: destination, view: 'comments', utility: null,
      notice: '', error: '', settingsTheme: null,
    });
    if (group?.id === destination.group_id) show();
    else {
      update({ queuedCommentDestination: undefined });
      void run('comment-destination', () => window.publisher.request('groups.select', { id: destination.group_id }), show);
    }
  }, [data, destination, group?.id, pending]);
  const region: PlatformRegion = data?.platform_region ?? 'domestic';
  const theme: AccentTheme = data?.accent_theme ?? 'neutral';
  const visibleTheme = state.view === 'settings' ? state.settingsTheme ?? theme : theme;
  const regionCategory = platformRegions[region].category;
  const regionPlatforms = (data?.platforms || []).filter(item => item.category === regionCategory || item.category === '自定义');
  const formats = graphicFormats.filter(({ id }) => regionPlatforms.some(platform => platform.kinds.includes(id)));
  const graphic = formats.some(({ id }) => id === state.graphicFormat) ? state.graphicFormat : formats[0]?.id || 'image';
  const kind: Kind = state.publishTab === 'video' ? 'video' : graphic;
  const draft = (group && state.drafts[`${group.id}:${kind}`]) || emptyDraft;
  const platforms = Object.fromEntries((data?.platforms || []).map(platform => [platform.id, platform]));
  const nameOf = (id: string) => platforms[id]?.label || id;
  const customGroups = new Set(groups.filter(item => item.mode === 'custom').map(item => item.id));
  const bindingName = ({ group_id, platform, slot }: Pick<Binding, 'group_id' | 'platform' | 'slot'>) =>
    customGroups.has(group_id) ? `${nameOf(platform)} ${slot}` : nameOf(platform);
  const bindings = data?.bindings.filter(binding => binding.group_id === group?.id) || [];
  const regionPlatformIds = new Set(regionPlatforms.map(platform => platform.id));
  const platformOrder = new Map(regionPlatforms.map((platform, index) => [platform.id, index]));
  const regionBindings = bindings.filter(binding => regionPlatformIds.has(binding.platform));
  const tasks = data?.tasks.filter(task => task.group_id === group?.id) || [];
  const searchableBindings = data?.bindings.filter(binding => binding.label && regionPlatformIds.has(binding.platform)) || [];
  const boundGroups = new Set(data?.bindings.filter(binding => binding.label).map(binding => binding.group_id));
  const visibleBindings = regionBindings.filter(binding => {
    const platform = platforms[binding.platform];
    const matchesCategory = category === 'all' || (category === 'video'
      ? platform.kinds.includes('video') : platform.kinds.some(kind => kind !== 'video'));
    const matchesState = accountState === 'all'
      || (accountState === 'bound' && !!binding.label)
      || (accountState === 'unbound' && !binding.label)
      || (accountState === 'attention' && binding.login_status === 'attention');
    return matchesCategory && matchesState
      && `${bindingName(binding)} ${platform.id} ${binding.label}`.toLowerCase().includes(search.trim().toLowerCase());
  }).sort((left, right) => Number(!!right.label) - Number(!!left.label)
    || (platformOrder.get(left.platform) ?? 0) - (platformOrder.get(right.platform) ?? 0));
  const connected = regionBindings.filter(binding => platforms[binding.platform].kinds.includes(kind) && isConnected(binding));
  const destinations = connected.filter(binding => draft.targets.includes(binding.id)).map(binding => ({
    binding, name: bindingName(binding), custom: customPlatforms.has(binding.platform), content: effectiveContent(draft, binding),
  }));
  const customized = destinations.filter(destination => destination.custom);
  const optionGroups = [...new Set(destinations.map(({ binding }) => binding.platform))].flatMap(platform => {
    const fields = platformOptions[platform];
    return fields ? [{ id: platform, name: nameOf(platform), fields: fields.filter(field => !field.when || draft.options[field.when[0]] === field.when[1]) }] : [];
  });
  const has = (platform: string) => destinations.some(destination => destination.binding.platform === platform);
  const limits = destinations.filter(({ binding, custom }) => !custom || draft.overrides[binding.id]?.title === undefined)
    .map(({ binding }) => platforms[binding.platform].title_limit);
  const titleLimit = limits.length ? Math.min(...limits) : undefined;
  const validation = checkContent(destinations, kind, platforms);
  const blockedReason = !destinations.length ? '请先选择发布账号'
    : kind !== 'article' && !draft.files.length ? '请先选择素材'
    : destinations.some(({ content }) => !content.title.trim()) ? '请填写所选平台的标题'
    : kind === 'article' && !draft.description.trim() ? '请填写文章正文'
    : kind === 'article' && draft.files.length && !has('wangyi') ? '文章配图需选择网易号'
    : has('douyin') && !draft.declaration ? '请选择抖音作品声明'
    : optionGroups.some(({ fields }) => fields.some(field => field.required && !draft.options[field.key]?.trim())) ? '请填写必需的平台设置'
    : validation[0];
  const isBusy = !!pending || !!connectionError;
  const canSubmit = !!group && !isBusy && !blockedReason;

  function changeDraft(edit: DraftUpdate, groupId = group?.id, contentKind = kind) {
    if (!groupId) return;
    const key = `${groupId}:${contentKind}`;
    update(current => {
      const draft = current.drafts[key] || emptyDraft;
      return { drafts: { ...current.drafts, [key]: { ...draft, ...(typeof edit === 'function' ? edit(draft) : edit) } } };
    });
  }

  function changeOverride(bindingId: string, key: keyof PublishContent, value: string | undefined) {
    changeDraft(current => {
      const next = { ...current.overrides[bindingId] };
      if (value === undefined) delete next[key];
      else next[key] = value;
      return { overrides: { ...current.overrides, [bindingId]: next } };
    });
  }

  function changeFiles(files: string[], groupId = group?.id, contentKind = kind) {
    changeDraft(current => {
      if (contentKind !== 'image') return { files };
      return {
        files, cover: files.includes(current.cover) ? current.cover : '',
        overrides: Object.fromEntries(Object.entries(current.overrides).map(([id, content]) => [
          id, content.cover && !files.includes(content.cover) ? { ...content, cover: '' } : content,
        ])),
      };
    }, groupId, contentKind);
  }

  function chooseFiles(files: string[], groupId = group?.id, contentKind = kind) {
    const config = contentKinds[contentKind];
    if (!files.length || files.some(file => !config.extension.test(file)) || files.length > config.maxFiles) {
      update({ error: contentKind === 'video' ? '请选择一个 MP4 或 MOV 视频。' : '请选择 1–18 张 JPG、PNG 或 WebP 图片。' });
      return;
    }
    update({ error: '' });
    changeFiles(files, groupId, contentKind);
  }

  function selectGroup(id: string) {
    if (id !== group?.id) {
      update({ commentDestination: undefined });
      void run('group', () => window.publisher.request('groups.select', { id }));
    }
  }

  function jumpToGroup(id: string, binding?: Binding) {
    const navigate = () => update({
      utility: null, view: binding ? 'accounts' : 'publish', category: 'all', accountState: 'all',
      search: binding ? binding.label : '', error: '', notice: '', settingsTheme: null,
    });
    if (id === group?.id) navigate();
    else void run('group', () => window.publisher.request('groups.select', { id }), navigate);
  }

  function changeView(view: View) {
    update(current => view === current.view ? { utility: null, commentDestination: undefined } : {
      view, utility: null, error: '', notice: '', settingsRegion: null, settingsTheme: null, commentDestination: undefined,
    });
  }
  function useMaterial(file: string, groupId = group?.id) {
    if (!groupId) return;
    chooseFiles([file], groupId, 'video');
    update(current => current.data?.active_group_id === groupId
      ? { view: 'publish', publishTab: 'video', utility: null, notice: '', commentDestination: undefined } : {});
  }
  function changeVideoProcessing(patch: Partial<VideoProcessingState>) {
    update(current => ({ videoProcessing: { ...current.videoProcessing, ...patch } }));
  }
  function processDownloadedVideo(id: string) {
    update(current => ({
      view: 'video-processing', utility: null, error: '', notice: '', commentDestination: undefined,
      videoProcessing: { ...current.videoProcessing, tool: 'extract', extractId: id },
    }));
  }
  function saveRegion() {
    const selected = state.settingsRegion;
    if (!selected || selected === region) return;
    void run('settings-region', () => window.publisher.request('settings.region', { region: selected }), () => {
      update(current => ({
        data: current.data && { ...current.data, platform_region: selected },
        settingsRegion: null, category: 'all', accountState: 'all', search: '',
        notice: `当前范围为${platformRegions[selected].label}。`,
      }));
    });
  }
  function saveTheme() {
    const selected = accentThemes.find(option => option.id === state.settingsTheme);
    if (!selected || selected.id === theme) return;
    void run('settings-theme', () => window.publisher.request('settings.theme', { theme: selected.id }), () => {
      update(current => ({
        data: current.data && { ...current.data, accent_theme: selected.id },
        settingsTheme: null,
        notice: `已保存「${selected.name}」主题。`,
      }));
    });
  }
  function selectCommentAccount(binding: Binding) {
    update({ commentDestination: undefined });
    void run('comment-account', () => window.publisher.request('settings.commentAccount', {
      group_id: binding.group_id, binding_id: binding.id,
    }), () => {
      update(current => ({ data: current.data && {
        ...current.data, comment_accounts: { ...current.data.comment_accounts, [binding.group_id]: binding.id },
      } }));
    });
  }
  function updateCommentSettings(change: { directory?: string | null; notifications?: boolean }) {
    void run('comment-cache', async () => {
      const settings = await window.publisher.request<CommentSettings>('settings.commentCache', change);
      commentSettingsVersion.current += 1;
      update({ commentSettings: settings });
    }, () => update({ notice: change.directory !== undefined ? '已保存评论缓存目录。' : '已保存评论提醒设置。' }));
  }
  function chooseCommentCache() {
    void window.publisher.selectCommentCache().then(directory => {
      if (directory) updateCommentSettings({ directory });
    }).catch(error => update({ error: errorMessage(error) }));
  }
  function openAccountAdder() {
    if (group?.mode !== 'custom') return;
    update({ error: '', notice: '', accountAdder: { groupId: group.id, platform: '', count: '1' } });
  }
  function chooseLogin(binding: Binding) {
    const label = binding.label || (customGroups.has(binding.group_id) ? bindingName(binding) : '');
    update({ error: '', notice: '', account: { binding, label, settings: {}, opened: false } });
  }
  function showConfirmation(confirmation: Confirmation) { update({ confirmation, error: '', notice: '' }); }

  function confirm() {
    const confirmation = state.confirmation;
    if (!confirmation) return;
    const close = () => update({ confirmation: undefined });
    if (confirmation.type === 'replace') {
      void run('confirm', () => window.publisher.request('accounts.replace', { id: confirmation.binding.id }), close);
    } else if (confirmation.type === 'review') {
      void run('confirm', () => window.publisher.request('tasks.review', { id: confirmation.task.id, result: confirmation.result }), close);
    } else if (confirmation.type === 'schedule-change' || confirmation.type === 'schedule-cancel') {
      const rescheduling = confirmation.type === 'schedule-change';
      const scheduledAt = rescheduling ? scheduleTimestamp(confirmation.scheduledFor) : null;
      if (rescheduling && scheduledAt === null) {
        update({ error: '请选择将来的发布时间。' });
        return;
      }
      void run('confirm', () => window.publisher.request(rescheduling ? 'tasks.reschedule' : 'tasks.cancelSchedule', {
        batch_id: confirmation.task.batch_id, scheduled_at: scheduledAt,
      }), () => update({ confirmation: undefined, notice: rescheduling ? '定时发布已改期。' : '定时发布已取消。' }));
    } else if (confirmation.type === 'delete-group') {
      const deleted = confirmation.group;
      void run('confirm', () => window.publisher.request('groups.delete', { id: deleted.id }), () => {
        update(current => ({
          confirmation: undefined,
          drafts: Object.fromEntries(Object.entries(current.drafts).filter(([key]) => !key.startsWith(`${deleted.id}:`))),
          ...(group?.id === deleted.id && { category: 'all', accountState: 'all', search: '' }),
          notice: `已删除「${deleted.name}」。`,
        }));
      });
    } else if (confirmation.type === 'delete-account') {
      const { binding } = confirmation;
      void run('confirm', () => window.publisher.request('accounts.delete', { id: binding.id }), () => {
        update(current => ({
          confirmation: undefined,
          drafts: Object.fromEntries(Object.entries(current.drafts).map(([key, draft]) => [key,
            key.startsWith(`${binding.group_id}:`) ? {
              ...draft,
              targets: draft.targets.filter(id => id !== binding.id),
              overrides: Object.fromEntries(Object.entries(draft.overrides).filter(([id]) => id !== binding.id)),
            } : draft,
          ])),
          notice: `已删除${bindingName(binding)}的本地账号。`,
        }));
      });
    } else if (confirmation.type === 'delete-task') {
      void run('confirm', () => window.publisher.request('tasks.delete', { id: confirmation.task.id }),
        () => update({ confirmation: undefined, notice: '已删除这条发布记录。' }));
    } else {
      const { group, kind, draft, destinations, scheduledFor } = confirmation;
      const scheduledAt = scheduledFor === undefined ? null : scheduleTimestamp(scheduledFor);
      if (scheduledFor !== undefined && scheduledAt === null) {
        update({ error: '请选择将来的发布时间。' });
        return;
      }
      void run('confirm', () => window.publisher.request('tasks.create', {
        group_id: group.id, binding_ids: destinations.map(({ binding }) => binding.id), kind, media_paths: draft.files,
        scheduled_at: scheduledAt,
        title: draft.title, description: draft.description, tags: draft.tags, cover: draft.cover,
        declaration: destinations.some(({ binding }) => binding.platform === 'douyin') ? draft.declaration : null,
        overrides: Object.fromEntries(destinations.filter(({ custom, binding }) => custom && draft.overrides[binding.id])
          .map(({ binding }) => [binding.id, draft.overrides[binding.id]])),
        options: { ...draft.options, youtube_kids: draft.options.youtube_kids === 'yes' },
      }), () => {
        changeDraft(emptyDraft, group.id, kind);
        update({ confirmation: undefined, view: 'history', notice: scheduledAt
          ? `已为「${group.name}」预约定时发布。` : `已将任务加入「${group.name}」的发布记录。` });
      });
    }
  }

  return {
    state, update, run, groups, group, draft, platforms, nameOf, bindingName, bindings, tasks, visibleBindings,
    boundGroups, searchableBindings, jumpToGroup,
    region, regionPlatforms, formats, kind, saveRegion, theme, visibleTheme, saveTheme,
    selectCommentAccount, updateCommentSettings, chooseCommentCache,
    connected, destinations, customized, optionGroups, has, titleLimit, canSubmit, blockedReason, isBusy,
    activeTasks: tasks.filter(task => openStatuses.includes(task.status) || task.status === 'scheduled').length,
    othersInProgress: data?.tasks.filter(task => task.group_id !== group?.id && openStatuses.includes(task.status)).length || 0,
    changeDraft, changeOverride, changeFiles, chooseFiles, selectGroup, changeView, useMaterial, openAccountAdder, chooseLogin, showConfirmation, confirm,
    captionDrafts, changeVideoProcessing, processDownloadedVideo,
  };
}

export type PublisherWorkspace = ReturnType<typeof usePublisherWorkspace>;
