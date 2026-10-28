'use client';

/**
 * Accessible modal for creating or editing one dashboard widget. Metrics are
 * restricted to approved canonical-v2 definitions, dependent selections reset
 * whenever the metric or chart type changes, and previews run through the
 * shared bounded query engine only on an explicit "Xem trước" action.
 */

import { useCallback, useMemo, useState } from 'react';

import {
  FilterColumnItem,
  MetricRecord,
  RecommendedDimensionItem,
  TimeGrain,
} from '@/lib/api';
import { DashboardChartType, DashboardWidgetConfig } from '@/lib/dashboard';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { DashboardChart } from './DashboardChart';
import {
  DateFilterField,
  DimensionField,
  FormField,
  LayoutFields,
  MetricComparePicker,
  MetricPicker,
} from './WidgetConfigFields';
import { useDashboardWidgetData, DashboardWidgetData } from './useDashboardWidgetData';
import { useWidgetConfigMeta } from './useWidgetConfigMeta';
import {
  buildWidgetDraft,
  CHART_LABELS,
  createWidgetId,
  GRAIN_LABELS,
  initFormState,
  planMetricOptions,
  PREVIEW_PLACEHOLDER_WIDGET,
  recommendChartForDimensionItem,
  selectExecutableMetrics,
  SELECT_CLASS,
  stateForChartChange,
  validateForm,
  WidgetFormState,
  WidgetMeta,
} from './widgetConfigForm';
import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';

export interface WidgetConfigModalProps {
  open: boolean;
  dbId: number | string;
  querySupported: boolean;
  metrics: MetricRecord[];
  editingWidget: DashboardWidgetConfig | null;
  onSave: (widget: DashboardWidgetConfig) => void;
  onCancel: () => void;
}

/** Gate rendering so every open starts from a fresh, correctly seeded form. */
export function WidgetConfigModal(props: WidgetConfigModalProps) {
  if (!props.open) return null;
  return (
    <WidgetConfigModalInner
      key={props.editingWidget?.id ?? 'new-widget'}
      {...props}
    />
  );
}

function WidgetConfigModalInner(props: WidgetConfigModalProps) {
  const { translate } = useLanguage();
  const eligibleMetrics = useMemo(() => selectExecutableMetrics(props.metrics), [props.metrics]);
  const [form, setForm] = useState<WidgetFormState>(() =>
    initFormState(props.editingWidget, eligibleMetrics),
  );
  const [widgetId] = useState(() => props.editingWidget?.id ?? createWidgetId());
  const [previewWidget, setPreviewWidget] = useState<DashboardWidgetConfig | null>(null);
  const sanitizeOnLoad = useCallback((meta: WidgetMeta) => {
    const dimensionIds = new Set(meta.dimensions.map((item) => item.column_id));
    const timeIds = new Set(
      meta.columns.filter((column) => column.is_time_dimension).map((column) => column.column_id),
    );
    setForm((prev) => ({
      ...prev,
      dimensionColId:
        prev.dimensionColId !== null && dimensionIds.has(prev.dimensionColId) ? prev.dimensionColId : null,
      dateFilterColumnId:
        prev.dateFilterColumnId !== null && timeIds.has(prev.dateFilterColumnId)
          ? prev.dateFilterColumnId
          : null,
    }));
  }, []);
  const { currentMeta, errorMessage: metaError, loading: loadingMeta } = useWidgetConfigMeta(
    form.metricId,
    props.dbId,
    sanitizeOnLoad,
  );

  const timeColumns = useMemo(
    () => (currentMeta ? currentMeta.columns.filter((column) => column.is_time_dimension) : []),
    [currentMeta],
  );
  const dimensionIsTime =
    form.dimensionColId !== null && timeColumns.some((column) => column.column_id === form.dimensionColId);
  const validationMessage = validateForm(form);
  const canSave = validationMessage === null && !loadingMeta && metaError === null;

  const previewData = useDashboardWidgetData({
    dbId: props.dbId,
    widget: previewWidget ?? PREVIEW_PLACEHOLDER_WIDGET,
    globalGrain: null,
    datePreset: null,
    refreshGeneration: 0,
    enabled: previewWidget !== null && props.querySupported,
  });

  const handleMetricChange = useCallback((value: string) => {
    const metricId = value === '' ? null : Number(value);
    setForm((prev) => ({
      ...prev,
      metricId,
      additionalMetricIds: [],
      orderMetricId: metricId,
      dimensionColId: null,
      dateFilterColumnId: null,
      timeGrain: null,
    }));
    setPreviewWidget(null);
  }, []);

  const handleChartChange = useCallback(
    (value: string) => {
      const nextChart = value as DashboardChartType;
      setForm((prev) => stateForChartChange(prev, nextChart, dimensionIsTime));
    },
    [dimensionIsTime],
  );

  const patchForm = useCallback((patch: Partial<WidgetFormState>) => {
    setForm((prev) => ({ ...prev, ...patch }));
    setPreviewWidget(null);
  }, []);

  const runPreview = useCallback(() => {
    if (!canSave || form.metricId === null) return;
    setPreviewWidget(buildWidgetDraft(widgetId, form));
  }, [canSave, form, widgetId]);

  const handleSave = useCallback(() => {
    if (!canSave || form.metricId === null) return;
    props.onSave(buildWidgetDraft(widgetId, form));
  }, [canSave, form, widgetId, props]);

  const selectedMetric =
    eligibleMetrics.find((metric) => metric.metric_id === form.metricId) ?? null;
  const selectedMetricIds = form.metricId === null ? [] : [form.metricId, ...form.additionalMetricIds];
  const selectedMetricNames = selectedMetricIds.map(
    (id) => eligibleMetrics.find((metric) => metric.metric_id === id)?.name ?? `Metric ${id}`,
  );
  const compareOptions = planMetricOptions(eligibleMetrics, form.metricId);

  return (
    <Dialog open onOpenChange={(next) => { if (!next) props.onCancel(); }}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-base font-semibold">
            <Translated text={props.editingWidget ? 'Chỉnh sửa widget' : 'Thêm widget mới'} />
          </DialogTitle>
          <DialogDescription>
            <Translated text={"Cấu hình widget từ metric đã duyệt. Dữ liệu chỉ được truy vấn khi bấm “Xem trước”."} />
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <MetricPicker metrics={eligibleMetrics} value={form.metricId} onChange={handleMetricChange} />
          {form.chartType !== 'kpi' && form.chartType !== 'pie' && form.metricId !== null && (
            <MetricComparePicker
              metrics={compareOptions}
              value={form.additionalMetricIds}
              disabled={!selectedMetric?.definition?.metric.query_plan}
              onChange={(ids) => {
                const selected = ids.filter((id) => compareOptions.some((metric) => metric.metric_id === id)).slice(0, 4);
                setForm((prev) => ({
                  ...prev,
                  additionalMetricIds: selected,
                  orderMetricId: selected.includes(prev.orderMetricId ?? -1) ? prev.orderMetricId : prev.metricId,
                }));
                setPreviewWidget(null);
              }}
            />
          )}
          <FormField label="Loại biểu đồ" id="widget-chart">
            <select
              id="widget-chart"
              className={SELECT_CLASS}
              value={form.chartType}
              onChange={(event) => handleChartChange(event.target.value)}
            >
              {(Object.keys(CHART_LABELS) as DashboardChartType[]).map((chart) => (
                <option key={chart} value={chart}>{translate(CHART_LABELS[chart])}</option>
              ))}
            </select>
          </FormField>
          {form.chartType !== 'kpi' && (
            <DimensionField
              form={form}
              dimensions={currentMeta?.dimensions ?? []}
              timeColumns={timeColumns}
              recommendation={resolveRecommendation(form, currentMeta)}
              onSelect={(dimensionColId) => patchForm({ dimensionColId })}
            />
          )}
          {(form.chartType === 'line' || form.chartType === 'area') && (
            <FormField label="Mốc thời gian" id="widget-grain">
              <select
                id="widget-grain"
                className={SELECT_CLASS}
                value={form.timeGrain ?? ''}
                onChange={(event) => patchForm({ timeGrain: (event.target.value || null) as TimeGrain | null })}
              >
                {(Object.keys(GRAIN_LABELS) as TimeGrain[]).map((grain) => (
                  <option key={grain} value={grain}>{translate(GRAIN_LABELS[grain])}</option>
                ))}
              </select>
            </FormField>
          )}
          {selectedMetricIds.length > 1 && (form.chartType === 'bar' || form.chartType === 'table') && (
            <FormField label="Sắp xếp theo metric" id="widget-order-metric">
              <select
                id="widget-order-metric"
                className={SELECT_CLASS}
                value={form.orderMetricId ?? ''}
                onChange={(event) => patchForm({ orderMetricId: event.target.value ? Number(event.target.value) : null })}
              >
                {selectedMetricIds.map((id, index) => (
                  <option key={id} value={id}>{selectedMetricNames[index]}</option>
                ))}
              </select>
            </FormField>
          )}
          <DateFilterField
            timeColumns={timeColumns}
            value={form.dateFilterColumnId}
            required={form.chartType === 'kpi'}
            onChange={(dateFilterColumnId) => patchForm({ dateFilterColumnId })}
          />
          <LayoutFields form={form} onPatch={patchForm} />
          <PreviewPanel
            querySupported={props.querySupported}
            canPreview={canSave && props.querySupported}
            previewWidget={previewWidget}
            metricName={selectedMetric?.name ?? null}
            metricNames={selectedMetricNames}
            dimensionLabel={resolveDimensionLabel(form, currentMeta, timeColumns)}
            data={previewData}
            onPreview={runPreview}
          />
        </div>

        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-end">
          {metaError ? (
            <p role="alert" className="flex-1 text-xs font-medium text-destructive">{metaError}</p>
          ) : validationMessage ? (
            <p role="alert" className="flex-1 text-xs font-medium text-destructive">{validationMessage}</p>
          ) : (
            <p className="flex-1" />
          )}
          <Button type="button" variant="outline" onClick={props.onCancel}><Translated text={"Hủy"} /></Button>
          <Button type="button" disabled={!canSave} onClick={handleSave}><Translated text={"Lưu"} /></Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function resolveRecommendation(
  form: WidgetFormState,
  meta: WidgetMeta | null,
): DashboardChartType | null {
  if (form.chartType !== 'bar' && form.chartType !== 'pie' && form.chartType !== 'table') return null;
  const item = meta?.dimensions.find((candidate) => candidate.column_id === form.dimensionColId);
  return item ? recommendChartForDimensionItem(item) : null;
}

function resolveDimensionLabel(
  form: WidgetFormState,
  meta: WidgetMeta | null,
  timeColumns: FilterColumnItem[],
): string | null {
  if (form.chartType === 'kpi') return null;
  const categorical = meta?.dimensions.find((item) => item.column_id === form.dimensionColId);
  if (categorical) return categorical.business_name;
  const time = timeColumns.find((column) => column.column_id === form.dimensionColId);
  return time?.business_name ?? null;
}

function PreviewPanel({
  querySupported,
  canPreview,
  previewWidget,
  metricName,
  metricNames,
  dimensionLabel,
  data,
  onPreview,
}: {
  querySupported: boolean;
  canPreview: boolean;
  previewWidget: DashboardWidgetConfig | null;
  metricName: string | null;
  metricNames: string[];
  dimensionLabel: string | null;
  data: DashboardWidgetData;
  onPreview: () => void;
}) {
  return (
    <section className="rounded-lg border border-border bg-secondary/30 p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground"><Translated text={"Xem trước"} /></h3>
        <Button type="button" size="sm" variant="outline" disabled={!canPreview} onClick={onPreview}>
          <Translated text={"Xem trước"} />
        </Button>
      </div>
      {!querySupported ? (
        <p
          role="note"
          className="mt-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-2.5 text-xs text-amber-600 dark:text-amber-400"
        >
          <Translated text={"Nguồn SQL Dump chỉ chứa metadata cấu trúc và không hỗ trợ truy vấn trực tiếp. Không thể xem trước dữ liệu Live DB cho nguồn này."} />
        </p>
      ) : previewWidget ? (
        <>
          <p className="mt-1 text-xs text-muted-foreground">
            <Translated text={"Dữ liệu mẫu truy vấn trực tiếp từ Live DB (tối đa 100 dòng)."} />
          </p>
          <div className="mt-2 h-64 rounded-xl border border-border bg-card p-3 flex flex-col">
            <DashboardChart
              widget={previewWidget}
              title={previewWidget.custom_title ?? metricName ?? 'Widget'}
              metricName={metricName ?? ''}
              metricNames={metricNames}
              dimensionLabel={dimensionLabel}
              data={data}
            />
          </div>
        </>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">
          <Translated text={"Hoàn tất cấu hình hợp lệ rồi nhấn “Xem trước” để chạy truy vấn mẫu."} />
        </p>
      )}
    </section>
  );
}
