import { useEffect, useState } from 'react';
import { Film, Image } from 'lucide-react';
import { cn } from '@/lib/utils';

export function MediaPreview({ path, video, className }: { path?: string; video?: boolean; className?: string }) {
  const [preview, setPreview] = useState<{ path: string; url: string }>();
  useEffect(() => {
    if (!path) return;
    let active = true;
    void window.publisher.mediaPreview(path).then(url => {
      if (active && url) setPreview({ path, url });
    }).catch(() => {});
    return () => { active = false; };
  }, [path]);
  const url = preview?.path === path ? preview?.url : undefined;
  const Icon = video ? Film : Image;
  return <span aria-hidden="true" className={cn(
    'relative grid aspect-video w-21 shrink-0 place-items-center overflow-hidden rounded-md bg-background text-muted-foreground ring-1 ring-foreground/5',
    className,
  )}>
    {url ? <img src={url} alt="" className="absolute inset-0 size-full object-cover" /> : <Icon className="size-4.5" />}
  </span>;
}
