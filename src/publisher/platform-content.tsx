import { useId, useState, type ReactNode } from 'react';
import { Image, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { Kind, PublishContent } from '@/types';
import { MediaPreview } from './media-preview';
import { contentKinds, errorMessage, fileName, parseTags, textLength, type Destination } from './model';
import type { PublisherWorkspace } from './use-workspace';
import { WorkspaceSelect } from './workspace-ui';

function ComposerField({ label, accessory, children }: { label: string; accessory?: ReactNode; children: (id: string) => ReactNode }) {
  const id = useId();
  return <div className="grid min-w-0 gap-1.5 @min-[32rem]:grid-cols-[3rem_minmax(0,1fr)] @min-[32rem]:gap-2.5">
    <label htmlFor={id} className="text-sm font-medium @min-[32rem]:pt-1.5">{label}</label>
    <div className="grid min-w-0 gap-1.5">
      {children(id)}
      {accessory && <div className="flex min-h-5 flex-wrap items-center justify-end gap-2">{accessory}</div>}
    </div>
  </div>;
}

function TagInput({ value, onChange, id, label }: { value: string; onChange: (value: string) => void; id: string; label: string }) {
  const [pending, setPending] = useState('');
  const tags = parseTags(value);
  function commit() {
    if (!parseTags(pending).length) return;
    onChange(parseTags([value, pending].filter(Boolean).join(',')).join('，'));
    setPending('');
  }
  return <div className="flex min-h-9 min-w-0 flex-wrap items-center gap-1.5 rounded-lg border bg-background px-2 py-1 focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/30">
    {tags.map(tag => <Badge key={tag} variant="secondary" className="max-w-full items-center gap-1 whitespace-normal wrap-anywhere">
      #{tag}<button type="button" aria-label={`移除标签 ${tag}`} className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground"
        onClick={() => onChange(tags.filter(item => item !== tag).join('，'))}><X className="size-3" /></button>
    </Badge>)}
    <input id={id} aria-label={label} className="min-w-23 flex-1 bg-transparent py-0.5 text-sm outline-none placeholder:text-muted-foreground"
      value={pending} placeholder={tags.length ? '添加标签' : '用逗号分隔标签'} onChange={event => setPending(event.target.value)}
      onBlur={commit} onKeyDown={event => {
        if (event.nativeEvent.isComposing || !['Enter', ',', '，'].includes(event.key)) return;
        event.preventDefault();
        commit();
      }} />
  </div>;
}

function CoverField({ kind, value, files, onChange, onError, label, id }: {
  kind: Kind; value: string; files: string[]; onChange: (value: string) => void;
  onError: (error: string) => void; label: string; id: string;
}) {
  if (kind === 'image') {
    const image = value || files[0];
    return <div className="flex min-w-0 items-center gap-2 rounded-lg bg-muted/55 p-1.5">
      {image && <MediaPreview path={image} className="w-12" />}
      <WorkspaceSelect id={id} label={label} className="min-w-0 flex-1" value={value}
        options={[{ value: '', label: '使用素材首图' }, ...[...new Set(files)].map(file => ({ value: file, label: fileName(file) }))]}
        onValueChange={onChange} />
    </div>;
  }
  return <div className="flex min-h-10 min-w-0 items-center gap-2 rounded-lg bg-muted/55 p-1.5">
    {value ? <MediaPreview path={value} className="w-15" /> : <Image className="ml-1 size-4 shrink-0 text-muted-foreground" />}
    <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground" title={value || undefined}>
      {value ? fileName(value) : '平台自动封面'}
    </span>
    <Button id={id} type="button" variant="outline" size="xs" aria-label={label} onClick={() => {
      void window.publisher.selectMedia('cover').then(([file]) => { if (file) onChange(file); }).catch(error => onError(errorMessage(error)));
    }}>{value ? '更换' : '选择'}</Button>
    {value && <Button type="button" variant="ghost" size="icon-xs" aria-label={`移除${label}`} onClick={() => onChange('')}><X /></Button>}
  </div>;
}

export function EditorFields({ workspace, destination }: { workspace: PublisherWorkspace; destination?: Destination }) {
  const { draft, kind } = workspace;
  if (destination && !destination.custom) {
    return <div className="grid gap-1 rounded-lg bg-muted/50 p-3">
      <div className="text-sm font-medium">使用通用文案</div>
      <p className="text-xs text-muted-foreground">此平台沿用「通用」中的标题和正文。</p>
    </div>;
  }
  const binding = destination?.binding;
  const overrides = binding ? draft.overrides[binding.id] || {} : {};
  const content = destination?.content || draft;
  const titleLimit = binding ? workspace.platforms[binding.platform].title_limit : workspace.titleLimit;
  const hasExtras = !!binding || workspace.customized.length > 0;
  const name = destination?.name || '';
  const change = (key: keyof PublishContent, value: string) => {
    if (binding) workspace.changeOverride(binding.id, key, value);
    else workspace.changeDraft({ [key]: value });
  };
  const accessory = (key: keyof PublishContent, label: string, hint?: string) => !binding && !hint ? undefined : <>
    {hint && <span className="text-xs tabular-nums text-muted-foreground">{hint}</span>}
    {binding && (Object.hasOwn(overrides, key)
      ? <Button type="button" variant="ghost" size="xs" aria-label={`恢复通用${name}${label}`}
        onClick={() => workspace.changeOverride(binding.id, key, undefined)}>恢复通用</Button>
      : <span className="text-xs text-muted-foreground">沿用通用</span>)}
  </>;
  return <div className="grid gap-3">
    <ComposerField label="标题" accessory={accessory('title', '标题', titleLimit ? `${textLength(content.title)} / ${titleLimit}` : undefined)}>
      {id => <Input id={id} aria-label={binding ? `${name}标题` : undefined} placeholder={`输入${contentKinds[kind].label}标题`}
        maxLength={200} value={content.title} onChange={event => change('title', event.target.value)} />}
    </ComposerField>
    <ComposerField label="正文" accessory={accessory('description', '正文', !binding && kind === 'article' ? '支持 Markdown' : undefined)}>
      {id => <Textarea id={id} aria-label={binding ? `${name}正文` : undefined} placeholder="输入正文" rows={kind === 'article' ? 8 : 3}
        className="min-h-20 resize-y" maxLength={kind === 'article' ? 50000 : 1000} value={content.description}
        onChange={event => change('description', event.target.value)} />}
    </ComposerField>
    {hasExtras && <>
      <ComposerField label="标签" accessory={accessory('tags', '标签')}>
        {id => <TagInput id={id} label={binding ? `${name}标签` : '通用标签'} value={content.tags} onChange={value => change('tags', value)} />}
      </ComposerField>
      <ComposerField label="封面" accessory={accessory('cover', '封面')}>
        {id => <CoverField id={id} kind={kind} files={draft.files} value={content.cover} label={binding ? `${name}封面` : '通用封面'}
          onChange={value => change('cover', value)} onError={error => workspace.update({ error })} />}
      </ComposerField>
    </>}
  </div>;
}
