'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Plus, RefreshCw, RotateCcw, Pencil } from 'lucide-react';

import {
  MetricRecord,
  SemanticCatalog,
  TimeGrain,
} from '@/lib/api';
import {
  buildStarterDashboardWidgets,
  colSpanToWidth,
  DashboardDatePreset,
  DashboardLayout,
  DashboardLayoutState,
  DashboardWidgetConfig,
  rowSpanToHeight,
} from '@/lib/dashboard';
import {
  DashboardVersionConflictError,
  loadDashboardApi,
  saveDashboardApi,
} from '@/lib/dashboardApi';
import { selectExecutableMetrics, GRAIN_LABELS } from '@/components/dashboard/widgetConfigForm';
import { DashboardGrid } from '@/components/dashboard/DashboardGrid';
import { WidgetConfigModal } from '@/components/dashboard/WidgetConfigModal';
import { clearDashboardPayloadCache } from '@/components/dashboard/useDashboardWidgetData';
import { ViewHeader } from '@/components/workspace/ViewHeader';
import { WorkspaceDatabase } from '@/components/workspace/shared';
import { Button } from '@/components/ui/button';
import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';

const DATE_PRESET_LABELS: Record<DashboardDatePreset, string> = {
  last_7_days: '7 ngày qua',
  last_30_days: '30 ngày qua',
  last_90_days: '90 ngày qua',
  this_month: 'Tháng này',
  this_quarter: 'Quý này',
  this_year: 'Năm này',
};

export interface MetricsDashboardViewProps {
  dbId: number | string;
  metrics: MetricRecord[];
  catalog: SemanticCatalog | null;
  database?: WorkspaceDatabase | null;
  canEdit?: boolean;
  onOpenCatalog?: () => void;
  onDrillDown?: (widget: DashboardWidgetConfig, datePreset: DashboardDatePreset | null) => void;
}

export function MetricsDashboardView(props: MetricsDashboardViewProps) {
  const { translate } = useLanguage();
  const { dbId, metrics, catalog, database, canEdit = true, onOpenCatalog, onDrillDown } = props;
  const querySupported = catalog?.query_supported ?? false;
  const executable = useMemo(() => selectExecutableMetrics(metrics), [metrics]);

  const [working, setWorking] = useState<DashboardLayout | null>(null);
  const [version, setVersion] = useState(0);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [updatedBy, setUpdatedBy] = useState<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [datePreset, setDatePreset] = useState<DashboardDatePreset | null>(null);
  const [refreshGeneration, setRefreshGeneration] = useState(0);
  const [lastDataRefresh, setLastDataRefresh] = useState<Date | null>(null);
  const [conflict, setConflict] = useState(false);
  const [pending, setPending] = useState<DashboardLayout | null>(null);
  const [conflictVersion, setConflictVersion] = useState<number | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingWidget, setEditingWidget] = useState<DashboardWidgetConfig | null>(null);

  const versionRef = useRef(version);
  const conflictRef = useRef(conflict);
  useEffect(() => {
    versionRef.current = version;
  }, [version]);
  useEffect(() => {
    conflictRef.current = conflict;
  }, [conflict]);

  const applyServerState = useCallback((state: DashboardLayoutState) => {
    setWorking(state.layout ?? { widgets: [] });
    setVersion(state.version);
    setUpdatedAt(state.updated_at);
    setUpdatedBy(state.updated_by);
    setConflict(false);
    setPending(null);
    setConflictVersion(null);
  }, []);

  const load = useCallback(async () => {
    if (!catalog || !catalog.query_supported) return;
    if (selectExecutableMetrics(metrics).length === 0) return;
    setLoadError(null);
    try {
      const state = await loadDashboardApi(dbId);
      if (state.layout === null) {
        const starter: DashboardLayout = {
          widgets: buildStarterDashboardWidgets({ metrics, catalog }),
        };
        try {
          const saved = await saveDashboardApi(dbId, starter, 0);
          applyServerState(saved);
        } catch (error) {
          if (error instanceof DashboardVersionConflictError) {
            applyServerState(await loadDashboardApi(dbId));
          } else {
            throw error;
          }
        }
      } else {
        applyServerState(state);
      }
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Không thể tải bảng điều khiển.');
    }
  }, [dbId, metrics, catalog, applyServerState]);

  const mutate = useCallback(
    async (next: DashboardLayout) => {
      setWorking(next);
      if (conflictRef.current) {
        setPending(next);
        return;
      }
      try {
        const saved = await saveDashboardApi(dbId, next, versionRef.current);
        applyServerState(saved);
      } catch (error) {
        if (error instanceof DashboardVersionConflictError) {
          setConflict(true);
          setPending(next);
          setConflictVersion(error.currentVersion);
        } else {
          setLoadError(error instanceof Error ? error.message : 'Lưu bảng điều khiển thất bại.');
        }
      }
    },
    [dbId, applyServerState],
  );

  useEffect(() => {
    if (catalog && catalog.query_supported && executable.length > 0) void load();
  }, [catalog, executable.length, load]);

  if (!catalog) return <LoadingState />;
  if (!querySupported) return <SqlDumpState />;
  if (executable.length === 0) return <NoMetricsState onOpenCatalog={onOpenCatalog} />;

  const handleReorder = (next: DashboardWidgetConfig[]) => void mutate({ widgets: next });
  const handleResizeWidget = (widgetId: string, colSpan: number, rowSpan: number) => {
    const current = working?.widgets ?? [];
    const nextWidgets = current.map((w) => {
      if (w.id !== widgetId) return w;
      return {
        ...w,
        col_span: colSpan,
        row_span: rowSpan,
        width: colSpanToWidth(colSpan),
        height: rowSpanToHeight(rowSpan),
      };
    });
    void mutate({ widgets: nextWidgets });
  };
  const handleEditWidget = (widget: DashboardWidgetConfig) => {
    setEditingWidget(widget);
    setModalOpen(true);
  };
  const handleDeleteWidget = (widget: DashboardWidgetConfig) => {
    const current = working?.widgets ?? [];
    void mutate({ widgets: current.filter((w) => w.id !== widget.id) });
  };
  const handleAddSave = (widget: DashboardWidgetConfig) => {
    const current = working?.widgets ?? [];
    const next: DashboardLayout = editingWidget
      ? { widgets: current.map((w) => (w.id === widget.id ? widget : w)) }
      : { widgets: [...current, widget] };
    setModalOpen(false);
    setEditingWidget(null);
    void mutate(next);
  };
  const handleReset = () => {
    if (typeof window !== 'undefined' && !window.confirm('Đặt lại bảng điều khiển về mặc định?')) return;
    void mutate({ widgets: buildStarterDashboardWidgets({ metrics, catalog }) });
  };
  const handleRefreshAll = () => {
    clearDashboardPayloadCache();
    setRefreshGeneration((value) => value + 1);
    setLastDataRefresh(new Date());
  };
  const handleLoadNew = async () => {
    applyServerState(await loadDashboardApi(dbId));
  };
  const handleOverwrite = async () => {
    const server = await loadDashboardApi(dbId);
    if (pending) applyServerState(await saveDashboardApi(dbId, pending, server.version));
  };

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-background text-foreground">
      <ViewHeader
        eyebrow="Bảng điều khiển"
        title={translate("Bảng điều khiển chỉ số")}
        description="Theo dõi các chỉ số đã duyệt qua các widget có thể sắp xếp."
        database={database}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" size="sm" onClick={handleRefreshAll}>
              <RefreshCw className="h-4 w-4" />
              <Translated text={"Làm mới tất cả"} />
            </Button>
            {canEdit && (
              <Button type="button" variant="outline" size="sm" onClick={() => setEditMode((v) => !v)}>
                <Pencil className="h-4 w-4" />
                <Translated text={editMode ? 'Xong' : 'Chỉnh sửa'} />
              </Button>
            )}
            {canEdit && editMode && (
              <>
                <Button type="button" size="sm" onClick={() => { setEditingWidget(null); setModalOpen(true); }}>
                  <Plus className="h-4 w-4" />
                  <Translated text={"Thêm widget"} />
                </Button>
                <Button type="button" variant="outline" size="sm" onClick={handleReset}>
                  <RotateCcw className="h-4 w-4" />
                  <Translated text={"Đặt lại"} />
                </Button>
              </>
            )}
          </div>
        }
      />

      <GlobalControls
        datePreset={datePreset}
        setDatePreset={setDatePreset}
        lastDataRefresh={lastDataRefresh}
        updatedAt={updatedAt}
        updatedBy={updatedBy}
      />

      {conflict && (
        <ConflictBanner
          conflictVersion={conflictVersion}
          onLoadNew={handleLoadNew}
          onOverwrite={handleOverwrite}
        />
      )}

      <div className="flex-1 overflow-auto p-4">
        {loadError ? (
          <ErrorState message={loadError} onRetry={() => void load()} />
        ) : working === null ? (
          <LoadingState />
        ) : working.widgets.length === 0 ? (
          <EmptyDashboardState canEdit={canEdit} editMode={editMode} onAdd={() => { setEditingWidget(null); setModalOpen(true); }} />
        ) : (
          <DashboardGrid
            widgets={working.widgets}
            dbId={dbId}
            globalGrain={null}
            datePreset={datePreset}
            refreshGeneration={refreshGeneration}
            querySupported={querySupported}
            editMode={canEdit && editMode}
            metrics={metrics}
            catalog={catalog}
            onReorder={handleReorder}
            onResizeWidget={handleResizeWidget}
            onEditWidget={handleEditWidget}
            onDeleteWidget={handleDeleteWidget}
            onDrillDown={onDrillDown}
          />
        )}
      </div>

      <WidgetConfigModal
        open={modalOpen}
        dbId={dbId}
        querySupported={querySupported}
        metrics={metrics}
        editingWidget={editingWidget}
        onSave={handleAddSave}
        onCancel={() => { setModalOpen(false); setEditingWidget(null); }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Presentational subcomponents
// ---------------------------------------------------------------------------

function LoadingState() {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-2 p-12 text-center text-muted-foreground">
      <span className="h-5 w-5 animate-spin rounded-full border-2 border-border border-t-primary" />
      <p className="text-sm"><Translated text={"Đang tải bảng điều khiển…"} /></p>
    </div>
  );
}

function SqlDumpState() {
  const { translate } = useLanguage();
  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-background text-foreground">
      <ViewHeader
        eyebrow="Bảng điều khiển"
        title={translate("Bảng điều khiển chỉ số")}
        description="Theo dõi các chỉ số đã duyệt qua các widget có thể sắp xếp."
      />
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-12 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-500">
          <AlertTriangle className="h-6 w-6" />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-foreground"><Translated text={"Chế độ xem Technical Preview"} /></h2>
          <p className="mt-1 max-w-md text-xs text-muted-foreground">
            <Translated text={"SQL Dump chỉ chứa metadata DDL và không hỗ trợ query. Hãy chọn Live DB."} />
          </p>
        </div>
      </div>
    </div>
  );
}

function NoMetricsState({ onOpenCatalog }: { onOpenCatalog?: () => void }) {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-3 p-12 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-border bg-secondary text-muted-foreground">
        <AlertTriangle className="h-6 w-6" />
      </div>
      <h2 className="text-sm font-semibold text-foreground"><Translated text={"Chưa có chỉ số đã duyệt"} /></h2>
      <p className="max-w-md text-xs text-muted-foreground">
        <Translated text={"Bảng điều khiển cần ít nhất một chỉ số đã duyệt (canonical v2, không lỗi) để hiển thị dữ liệu."} />
      </p>
      {onOpenCatalog && (
        <Button type="button" variant="outline" size="sm" onClick={onOpenCatalog}>
          <Translated text={"Đi tới Catalog"} />
        </Button>
      )}
    </div>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center justify-center gap-3 p-12 text-center">
      <p className="text-sm text-destructive">{message}</p>
      <Button type="button" variant="outline" size="sm" onClick={onRetry}>
        <Translated text={"Thử lại"} />
      </Button>
    </div>
  );
}

function EmptyDashboardState({
  canEdit,
  editMode,
  onAdd,
}: {
  canEdit: boolean;
  editMode: boolean;
  onAdd: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 p-12 text-center text-muted-foreground">
      <p className="text-sm"><Translated text={"Chưa có widget nào trên bảng điều khiển."} /></p>
      {canEdit && editMode && (
        <Button type="button" size="sm" onClick={onAdd}>
          <Plus className="h-4 w-4" />
          <Translated text={"Thêm widget đầu tiên"} />
        </Button>
      )}
    </div>
  );
}

function ConflictBanner({
  conflictVersion,
  onLoadNew,
  onOverwrite,
}: {
  conflictVersion: number | null;
  onLoadNew: () => void;
  onOverwrite: () => void;
}) {
  return (
    <div
      role="alert"
      className="mx-4 mt-3 flex flex-col gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm sm:flex-row sm:items-center sm:justify-between"
    >
      <p className="text-amber-700 dark:text-amber-300">
        <Translated text={"Bảng điều khiển đã bị thay đổi bởi người khác"} after />{conflictVersion !== null ? ` (phiên bản ${conflictVersion}).` : '.'} <Translated text={"Thay đổi của bạn chưa được ghi."} /></p>
      <div className="flex shrink-0 gap-2">
        <Button type="button" variant="outline" size="sm" onClick={onLoadNew}>
          <Translated text={"Tải phiên bản mới"} />
        </Button>
        <Button type="button" size="sm" onClick={onOverwrite}>
          <Translated text={"Thử ghi đè sau khi tải/áp dụng lại"} />
        </Button>
      </div>
    </div>
  );
}

function GlobalControls({
  datePreset,
  setDatePreset,
  lastDataRefresh,
  updatedAt,
  updatedBy,
}: {
  datePreset: DashboardDatePreset | null;
  setDatePreset: (value: DashboardDatePreset | null) => void;
  lastDataRefresh: Date | null;
  updatedAt: string | null;
  updatedBy: number | null;
}) {
  const { translate } = useLanguage();
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3 text-sm">
      <label className="flex items-center gap-2">
        <span className="text-muted-foreground"><Translated text={"Khoảng thời gian"} /></span>
        <select
          aria-label={translate("Khoảng thời gian")}
          className="h-8 rounded-md border border-border bg-background px-2 text-sm"
          value={datePreset ?? ''}
          onChange={(e) => setDatePreset((e.target.value || null) as DashboardDatePreset | null)}
        >
          <option value="">{translate('Không áp dụng')}</option>
          {(Object.keys(DATE_PRESET_LABELS) as DashboardDatePreset[]).map((preset) => (
            <option key={preset} value={preset}>{translate(DATE_PRESET_LABELS[preset])}</option>
          ))}
        </select>
      </label>
      <LayoutMetadata lastDataRefresh={lastDataRefresh} updatedAt={updatedAt} updatedBy={updatedBy} />
    </div>
  );
}

function LayoutMetadata({
  lastDataRefresh,
  updatedAt,
  updatedBy,
}: {
  lastDataRefresh: Date | null;
  updatedAt: string | null;
  updatedBy: number | null;
}) {
  const { locale, t } = useLanguage();
  return (
    <div className="ml-auto flex flex-col items-end gap-0.5 text-xs text-muted-foreground">
      {lastDataRefresh && (
        <span data-testid="last-data-refresh">
          <Translated text={"Dữ liệu làm mới lúc"} after />{lastDataRefresh.toLocaleTimeString(locale)}
        </span>
      )}
      <span data-testid="layout-metadata" data-updated-at={updatedAt ?? ''} data-updated-by={String(updatedBy ?? '')}>
        {updatedAt ? `${t('Last updated:', 'Cập nhật lần cuối:')} ${updatedAt}` : t('Not saved', 'Chưa lưu')}
        {updatedBy ? ` · ${t('by', 'bởi')} #${updatedBy}` : ''}
      </span>
    </div>
  );
}
