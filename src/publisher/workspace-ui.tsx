import { cloneElement, useId, type ReactElement, type ReactNode } from 'react';
import {
  BookOpen, BriefcaseBusiness, Camera, CircleAlert, CircleHelp, CodeXml, FileText, Globe, Link2,
  MessageCircle, MessageSquareText, MessagesSquare, Monitor, Music2, Newspaper, PenLine, Play,
  Video, X, type LucideIcon,
} from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Field, FieldLabel } from '@/components/ui/field';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { cn } from '@/lib/utils';
import { productName } from '../../package.json';
import relayfoldMark from '@/assets/relayfold-mark.png';

const emptySelectValue = '__relayfold_empty__';

export function WorkspaceSelect({ id, label, value, options, onValueChange, className, disabled, showScrollButtons }: {
  id?: string;
  label?: string;
  value: string;
  options: readonly { label: string; value: string }[];
  onValueChange: (value: string) => void;
  className?: string;
  disabled?: boolean;
  showScrollButtons?: boolean;
}) {
  return <Select value={value || emptySelectValue} disabled={disabled}
    onValueChange={value => onValueChange(value === emptySelectValue ? '' : value)}>
    <SelectTrigger id={id} aria-label={label} className={cn('min-w-0 bg-background shadow-xs hover:bg-muted/60', className)}>
      <SelectValue />
    </SelectTrigger>
    <SelectContent position="popper" align="start" showScrollButtons={showScrollButtons}
      className="w-(--radix-select-trigger-width) max-w-(--radix-select-content-available-width) p-1">
      {options.map(option => <SelectItem key={option.value} value={option.value || emptySelectValue}>
        <span className="min-w-0 truncate" title={option.label}>{option.label}</span>
      </SelectItem>)}
    </SelectContent>
  </Select>;
}

export function WorkspaceBrand({ className }: { className?: string }) {
  return <div data-slot="workspace-brand" className={cn('flex shrink-0 select-none items-center gap-2.5', className)}>
    <img src={relayfoldMark} alt="" width={24} height={24} draggable={false} className="size-6 object-contain" />
    <span className="text-base/none font-semibold tracking-tight group-data-[collapsible=icon]:sr-only">{productName}</span>
  </div>;
}

export function WorkspaceHeading({ title, description }: { title: string; description?: string }) {
  return <div className="space-y-1.5">
    <h1 className="workspace-title">{title}</h1>
    {description && <p className="text-sm text-muted-foreground">{description}</p>}
  </div>;
}

export function WorkspaceField({ label, hint, children }: {
  label: string; hint?: ReactNode; children: ReactElement<{ id?: string }>;
}) {
  const id = useId();
  return <Field className="gap-1.5">
    <div className="flex items-baseline justify-between gap-2">
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      {hint && <span className="text-right text-xs tabular-nums text-muted-foreground">{hint}</span>}
    </div>
    {cloneElement(children, { id })}
  </Field>;
}

const platformIcons: Partial<Record<string, LucideIcon>> = {
  douyin: Music2,
  xiaohongshu: BookOpen,
  kuaishou: Video,
  shipinghao: MessagesSquare,
  bilibili: Monitor,
  zhihu: MessageSquareText,
  toutiao: Newspaper,
  csdn: CodeXml,
  jianshu: PenLine,
  sohu: Newspaper,
  wechat_mp: MessagesSquare,
  baijiahao: FileText,
  wangyi: Newspaper,
  tiktok: Music2,
  youtube: Play,
  facebook: MessageCircle,
  instagram: Camera,
  twitter: X,
  reddit: MessagesSquare,
  medium: BookOpen,
  linkedin: BriefcaseBusiness,
  blogger: PenLine,
  quora: CircleHelp,
  devto: CodeXml,
  company_website_v2: Link2,
};

export function PlatformIcon({ platform, className }: { platform: string; className?: string }) {
  const Icon = platformIcons[platform] ?? Globe;
  return <Icon aria-hidden="true" className={cn('size-4 shrink-0', className)} />;
}

export function PlatformMark({ platform }: { platform: string }) {
  return <span aria-hidden="true" className="grid size-8 shrink-0 place-items-center rounded-md bg-muted">
    <PlatformIcon platform={platform} />
  </span>;
}

const statusColors: Record<string, string> = {
  neutral: 'bg-muted text-muted-foreground',
  green: 'bg-emerald-600/10 text-emerald-800 dark:text-emerald-400',
  amber: 'bg-amber-600/10 text-amber-800 dark:text-amber-400',
  red: 'bg-destructive/10 text-destructive',
};

export function StatusBadge({ value: [label, tone] }: { value: readonly [string, string] }) {
  return <Badge variant="secondary" className={cn('h-6 shrink-0 gap-1.5 rounded-md px-2 text-xs', statusColors[tone])}>
    <span className="size-1.5 rounded-full bg-current" />{label}
  </Badge>;
}

export function ErrorNotice({ children }: { children: ReactNode }) {
  return <Alert variant="destructive" role="alert">
    <CircleAlert /><AlertDescription>{children}</AlertDescription>
  </Alert>;
}
