import { useEffect, useState } from 'react';
import { errorMessage } from './model';

export type SubtitleTrack = { id: string; label: string; codec: string; convertible: boolean };
export type MaterialAsset = {
  id: string; title: string; path: string; source: 'local' | 'bilibili' | 'captioned'; available: boolean;
  size: number; duration: number | null; width: number | null; height: number | null; subtitles: SubtitleTrack[];
  has_audio?: boolean;
};
export type Cue = { startMs: number; endMs: number; text: string };
export type CaptionDocument = { revision: number; cues: Cue[] };
export type EditableCue = { start: string; end: string; text: string };
export type CaptionDraft = { revision: number; cues: EditableCue[] };
export type ImportedSubtitle = { id: string; name: string; cues: Cue[] };
export type SynthesisSource = { kind: 'saved'; id: string; revision: number } | { kind: 'srt'; id: string };
export type SubtitleSelection = { kind: 'saved'; id: string } | { kind: 'srt'; file: ImportedSubtitle };
export type ProcessingTool = 'extract' | 'synthesize';
export type VideoProcessingState = {
  tool: ProcessingTool; extractId?: string; synthesizeId?: string; subtitle?: SubtitleSelection;
};
export type CaptionSummary = {
  status: string; progress: number | null; detail: string; source: 'extract' | 'speech' | '';
  revision: number; count: number;
};
export type RenderSummary = {
  status: 'queued' | 'rendering' | 'ready' | 'failed' | 'canceled';
  progress: number | null; detail: string; destination: string; output_id: string | null; source_key: string;
};
export type DownloadJob = {
  id: string; title: string; height: number; status: 'queued' | 'downloading' | 'completed' | 'failed' | 'canceled';
  progress: number | null; detail: string; asset_id: string | null;
};
export type MaterialSnapshot = {
  directory: string; assets: MaterialAsset[]; downloads: DownloadJob[];
  captions: Record<string, CaptionSummary>; renders: Record<string, RenderSummary>;
};

const captionStages = ['queued', 'extracting', 'setup', 'audio', 'recognizing'];
export const captionBusy = (caption?: CaptionSummary) => !!caption && captionStages.includes(caption.status);
export const renderBusy = (job?: RenderSummary) => job?.status === 'queued' || job?.status === 'rendering';
export const sourceLabels = { local: '本地', bilibili: 'B 站', captioned: '字幕版' };

export function durationLabel(seconds: number | null) {
  if (seconds === null) return '';
  const total = Math.floor(seconds);
  return String(Math.floor(total / 60)).padStart(2, '0') + ':' + String(total % 60).padStart(2, '0');
}

export function useMaterialSnapshot() {
  const [snapshot, setSnapshot] = useState<MaterialSnapshot>();
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    let revision = 0;
    function load() {
      const requested = ++revision;
      void window.publisher.request<MaterialSnapshot>('materials.snapshot').then(data => {
        if (active && requested === revision) { setSnapshot(data); setError(''); }
      }).catch(cause => { if (active && requested === revision) setError(errorMessage(cause)); });
    }
    const stop = window.publisher.subscribeMaterials(load);
    load();
    return () => { active = false; stop(); };
  }, []);
  return { snapshot, error };
}
