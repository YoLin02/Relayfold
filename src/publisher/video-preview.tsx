import { Film } from 'lucide-react';
import { useEffect, useState, type RefObject } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { Cue, MaterialAsset } from './video-materials';

export function playFrom(video: HTMLVideoElement | null, startMs: number) {
  if (!video || video.readyState < 1) return;
  video.currentTime = Math.min(startMs / 1000, video.duration);
  void video.play().catch(() => undefined);
}

export function VideoPreview({ asset, video, cues }: {
  asset: MaterialAsset; video: RefObject<HTMLVideoElement | null>; cues: Cue[];
}) {
  const [url, setUrl] = useState('');
  const [unavailable, setUnavailable] = useState(!asset.available);
  const [playback, setPlayback] = useState(0);
  const [aspect, setAspect] = useState(16 / 9);
  const active = cues.find(cue => cue.startMs <= playback && playback < cue.endMs);

  useEffect(() => {
    let active = true;
    void window.publisher.materialAction<string | null>('preview', { id: asset.id }).then(result => {
      if (active) {
        setUrl(result || '');
        setUnavailable(!result);
      }
    }).catch(() => { if (active) setUnavailable(true); });
    return () => { active = false; };
  }, [asset.id, asset.available]);

  return <Card className="workspace-panel min-w-0">
    <CardHeader><CardTitle className="flex min-w-0 items-center gap-2"><Film className="size-4 shrink-0" />
      <span className="truncate" title={asset.title}>{asset.title}</span>
    </CardTitle></CardHeader>
    <CardContent>
      {unavailable ? <p className="rounded-lg bg-muted px-3 py-3 text-sm text-muted-foreground">
        {asset.available ? '这个视频格式无法在窗口内预览，仍可生成 MP4。' : '视频文件已移动或删除。'}
      </p> : <div className="relative mx-auto overflow-hidden rounded-lg bg-black"
        style={{ aspectRatio: aspect, width: 'min(100%, ' + (aspect * 43) + 'vh)' }}>
        {url && <video ref={video} controls src={url} preload="metadata" className="block size-full"
          onError={() => setUnavailable(true)}
          onLoadedMetadata={event => {
            const element = event.currentTarget;
            if (element.videoWidth && element.videoHeight) setAspect(element.videoWidth / element.videoHeight);
          }}
          onTimeUpdate={event => setPlayback(Math.round(event.currentTarget.currentTime * 1000))}
          onSeeked={event => setPlayback(Math.round(event.currentTarget.currentTime * 1000))} />}
        {url && active && <p aria-label="实时字幕" className="pointer-events-none absolute inset-x-2 bottom-11 mx-auto w-fit max-w-[calc(100%-1rem)] whitespace-pre-line rounded bg-black/75 px-2 py-1 text-center text-sm text-white">
          {active.text.replace(/<\/?(i|b|u)>/gi, '')}
        </p>}
      </div>}
    </CardContent>
  </Card>;
}
