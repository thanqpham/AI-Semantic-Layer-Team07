'use client';

import { useReactFlow } from '@xyflow/react';
import { Eye, EyeOff, GitFork, LayoutGrid, Maximize2, Sparkles } from 'lucide-react';

import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';
import type { LayoutMode } from '@/lib/relationshipGraph';
import { cn } from '@/lib/utils';

interface Props {
  mode: LayoutMode;
  onModeChange: (mode: LayoutMode) => void;
  hideIsolated: boolean;
  onToggleIsolated: () => void;
  isolatedCount: number;
}

const pill = 'inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[11px] font-medium transition-colors';

/** Controls panel for diagram layout mode, isolated table filter, and zoom presets. */
export function DiagramControls({ mode, onModeChange, hideIsolated, onToggleIsolated, isolatedCount }: Props) {
  const { translate: t } = useLanguage();
  const { zoomTo, fitView } = useReactFlow();

  const handleFitReadable = () => {
    void fitView({ padding: 0.2, minZoom: 0.65, maxZoom: 1.0, duration: 300 });
  };

  const handleFitAll = () => {
    void fitView({ padding: 0.1, duration: 300 });
  };

  return (
    <div className="flex max-w-[calc(100vw-4rem)] flex-wrap items-center gap-1.5 rounded-lg border border-border bg-card/95 p-1 text-xs shadow-sm backdrop-blur">
      <div role="group" aria-label={t('Chế độ sắp xếp')} className="flex items-center gap-0.5 rounded-md bg-muted/60 p-0.5">
        <button
          type="button"
          title={t('Sắp xếp cân bằng nhiều cột (chống rối)')}
          aria-pressed={mode === 'balanced'}
          onClick={() => onModeChange('balanced')}
          className={cn(pill, mode === 'balanced' ? 'bg-background text-foreground shadow-xs font-semibold' : 'text-muted-foreground hover:text-foreground')}
        >
          <Sparkles className="size-3.5 text-amber-500" />
          <Translated text="Cân bằng" />
        </button>
        <button
          type="button"
          title={t('Sắp xếp phân tầng từ trái sang phải')}
          aria-pressed={mode === 'hierarchical'}
          onClick={() => onModeChange('hierarchical')}
          className={cn(pill, mode === 'hierarchical' ? 'bg-background text-foreground shadow-xs font-semibold' : 'text-muted-foreground hover:text-foreground')}
        >
          <GitFork className="size-3.5 text-sky-500" />
          <Translated text="Phân tầng" />
        </button>
        <button
          type="button"
          title={t('Sắp xếp dạng lưới ô vuông')}
          aria-pressed={mode === 'grid'}
          onClick={() => onModeChange('grid')}
          className={cn(pill, mode === 'grid' ? 'bg-background text-foreground shadow-xs font-semibold' : 'text-muted-foreground hover:text-foreground')}
        >
          <LayoutGrid className="size-3.5 text-emerald-500" />
          <Translated text="Lưới" />
        </button>
      </div>

      {isolatedCount > 0 && (
        <button
          type="button"
          aria-pressed={hideIsolated}
          onClick={onToggleIsolated}
          title={t(hideIsolated ? 'Hiện tất cả các bảng' : 'Ẩn các bảng không có liên kết nào')}
          className={cn(
            'inline-flex h-7 items-center gap-1.5 rounded-md border border-border px-2 text-[11px] font-medium transition-colors',
            hideIsolated ? 'bg-primary text-primary-foreground' : 'bg-background text-muted-foreground hover:text-foreground'
          )}
        >
          {hideIsolated ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
          <span>{hideIsolated ? t('Đang ẩn bảng rời') : t('Ẩn bảng rời')} ({isolatedCount})</span>
        </button>
      )}

      <span className="h-3.5 w-px bg-border" aria-hidden="true" />

      <button
        type="button"
        onClick={() => void zoomTo(1.0, { duration: 250 })}
        title={t('Phóng to mức 100% chuẩn')}
        className="inline-flex h-7 items-center rounded-md border border-border bg-background px-2 font-mono text-[11px] font-medium text-foreground hover:bg-muted"
      >
        100%
      </button>

      <button
        type="button"
        onClick={handleFitReadable}
        title={t('Căn vừa vùng nhìn phóng to rõ nét')}
        className="inline-flex h-7 items-center gap-1 rounded-md border border-border bg-background px-2 text-[11px] font-medium text-foreground hover:bg-muted"
      >
        <Maximize2 className="size-3" />
        <Translated text="To rõ" />
      </button>

      <button
        type="button"
        onClick={handleFitAll}
        title={t('Xem bao quát toàn bộ sơ đồ')}
        className="inline-flex h-7 items-center rounded-md px-1.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        <Translated text="Toàn cảnh" />
      </button>
    </div>
  );
}
