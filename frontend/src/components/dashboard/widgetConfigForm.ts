/**
 * Pure form logic for the widget configuration modal: eligibility filtering,
 * chart-compatibility state transitions, validation, and canonical draft
 * building. No React or network access lives here.
 */

import {
  FilterColumnItem,
  MetricRecord,
  RecommendedDimensionItem,
  TimeGrain,
} from '@/lib/api';
import {
  DashboardChartType,
  DashboardWidgetConfig,
  DashboardWidgetHeight,
  DashboardWidgetWidth,
  getWidgetMetricIds,
  recommendDashboardChartType,
} from '@/lib/dashboard';

export interface WidgetFormState {
  metricId: number | null;
  chartType: DashboardChartType;
  dimensionColId: number | null;
  dateFilterColumnId: number | null;
  timeGrain: TimeGrain | null;
  width: DashboardWidgetWidth;
  height: DashboardWidgetHeight;
  title: string;
  additionalMetricIds: number[];
  orderMetricId: number | null;
}

export interface WidgetMeta {
  metricId: number;
  dimensions: RecommendedDimensionItem[];
  columns: FilterColumnItem[];
}

export const CHART_LABELS: Record<DashboardChartType, string> = {
  kpi: 'KPI',
  line: 'Biểu đồ đường',
  area: 'Biểu đồ vùng',
  bar: 'Biểu đồ cột',
  pie: 'Biểu đồ tròn',
  table: 'Bảng xếp hạng',
};

export const WIDTH_LABELS: Record<DashboardWidgetWidth, string> = {
  third: '1/3 lưới',
  half: '1/2 lưới',
  full: 'Đầy đủ chiều rộng',
};

export const HEIGHT_LABELS: Record<DashboardWidgetHeight, string> = {
  compact: 'Gọn',
  normal: 'Vừa',
  expanded: 'Cao',
};

export const GRAIN_LABELS: Record<TimeGrain, string> = {
  day: 'Ngày',
  week: 'Tuần',
  month: 'Tháng',
  quarter: 'Quý',
  year: 'Năm',
};

export const SELECT_CLASS =
  'h-9 cursor-pointer rounded-md border border-border bg-background px-2 text-sm text-foreground disabled:cursor-not-allowed disabled:opacity-50';

export const PREVIEW_PLACEHOLDER_WIDGET: DashboardWidgetConfig = {
  id: 'preview-placeholder',
  metric_id: 0,
  dimension_col_id: null,
  date_filter_column_id: null,
  time_grain: null,
  chart_type: 'kpi',
  width: 'third',
  height: 'compact',
  custom_title: null,
};

const NEW_FORM: WidgetFormState = {
  metricId: null,
  chartType: 'kpi',
  dimensionColId: null,
  dateFilterColumnId: null,
  timeGrain: null,
  width: 'third',
  height: 'normal',
  title: '',
  additionalMetricIds: [],
  orderMetricId: null,
};

/** Only approved canonical metrics without diagnostics are executable. */
export function selectExecutableMetrics(metrics: MetricRecord[]): MetricRecord[] {
  return metrics.filter(
    (metric) =>
      metric.status === 'approved' &&
      metric.definition !== null &&
      [2, 3].includes(metric.definition.schema_version ?? 0) &&
      !(metric.definition.diagnostics && metric.definition.diagnostics.length > 0),
  );
}

export function filterMetricsByName(metrics: MetricRecord[], search: string): MetricRecord[] {
  const query = search.trim().toLowerCase();
  if (!query) return metrics;
  return metrics.filter((metric) => metric.name.toLowerCase().includes(query));
}

function normalizeTitle(value: string): string | null {
  const normalized = value.trim();
  if (!normalized) return null;
  return normalized.slice(0, 200);
}

export function initFormState(
  editing: DashboardWidgetConfig | null,
  eligible: MetricRecord[],
  presetMetricId: number | null = null,
): WidgetFormState {
  if (!editing) {
    const preset = eligible.some((metric) => metric.metric_id === presetMetricId) ? presetMetricId : null;
    return preset === null ? NEW_FORM : { ...NEW_FORM, metricId: preset, orderMetricId: preset };
  }
  const known = eligible.some((metric) => metric.metric_id === editing.metric_id);
  return {
    metricId: known ? editing.metric_id : null,
    chartType: editing.chart_type,
    dimensionColId: editing.dimension_col_id,
    dateFilterColumnId: editing.date_filter_column_id,
    timeGrain: editing.time_grain,
    width: editing.width,
    height: editing.height,
    title: editing.custom_title ?? '',
    additionalMetricIds: getWidgetMetricIds(editing).slice(1),
    orderMetricId: editing.order_metric_id ?? editing.metric_id,
  };
}

/** Drop dependent selections that become incompatible with the new chart. */
export function stateForChartChange(
  prev: WidgetFormState,
  nextChart: DashboardChartType,
  dimensionIsTime: boolean,
): WidgetFormState {
  if (nextChart === 'kpi') {
    return { ...prev, chartType: nextChart, dimensionColId: null, timeGrain: null, additionalMetricIds: [], orderMetricId: null };
  }
  if (nextChart === 'line' || nextChart === 'area') {
    return {
      ...prev,
      chartType: nextChart,
      dimensionColId: dimensionIsTime ? prev.dimensionColId : null,
      timeGrain: prev.timeGrain ?? 'month',
    };
  }
  return {
    ...prev,
    chartType: nextChart,
    ...(nextChart === 'pie' ? { additionalMetricIds: [], orderMetricId: null } : {}),
    dimensionColId: dimensionIsTime ? null : prev.dimensionColId,
    timeGrain: null,
  };
}

/** Mirror of the persisted-layout compatibility rules used for validation. */
export function validateForm(form: WidgetFormState): string | null {
  if (form.metricId === null) return 'Hãy chọn một metric đã duyệt.';
  if (form.additionalMetricIds.length > 4) return 'Mỗi widget hỗ trợ tối đa 5 metric.';
  if (form.additionalMetricIds.length > 0 && (form.chartType === 'kpi' || form.chartType === 'pie')) {
    return 'KPI và biểu đồ tròn chỉ hỗ trợ một metric.';
  }
  if (
    form.additionalMetricIds.length > 0 &&
    (form.chartType === 'bar' || form.chartType === 'table') &&
    ![form.metricId, ...form.additionalMetricIds].includes(form.orderMetricId ?? -1)
  ) return 'Hãy chọn metric dùng để sắp xếp.';
  if (form.chartType === 'kpi') {
    if (form.dateFilterColumnId === null) return 'KPI cần một cột thời gian để lọc theo ngày.';
    return null;
  }
  if (form.chartType === 'line' || form.chartType === 'area') {
    if (form.dimensionColId === null) return 'Biểu đồ thời gian cần một cột thời gian.';
    if (form.timeGrain === null) return 'Hãy chọn mốc thời gian cho biểu đồ thời gian.';
    return null;
  }
  if (form.dimensionColId === null) return 'Biểu đồ cần một chiều dữ liệu phân loại.';
  return null;
}

export function buildWidgetDraft(id: string, form: WidgetFormState): DashboardWidgetConfig {
  const isTimeSeries = form.chartType === 'line' || form.chartType === 'area';
  const metricIds = form.metricId === null ? [] : [form.metricId, ...form.additionalMetricIds];
  return {
    id,
    metric_id: form.metricId ?? 0,
    ...(metricIds.length > 1 ? { metric_ids: metricIds } : {}),
    ...(metricIds.length > 1 && (form.chartType === 'bar' || form.chartType === 'table')
      ? { order_metric_id: form.orderMetricId ?? metricIds[0] }
      : {}),
    dimension_col_id: form.dimensionColId,
    date_filter_column_id: form.dateFilterColumnId,
    time_grain: isTimeSeries ? form.timeGrain : null,
    chart_type: form.chartType,
    width: form.width,
    height: form.height,
    custom_title: normalizeTitle(form.title),
  };
}

export interface WidgetSuggestion {
  key: string;
  label: string;
  form: WidgetFormState;
}

/** Reject dimension sets the compiler would refuse with INCOMPATIBLE_GRAIN. */
export function validateGrain(form: WidgetFormState, grain: number[] | null): string | null {
  if (grain === null) return null;
  const dims = form.chartType === 'kpi' || form.dimensionColId === null ? [] : [form.dimensionColId];
  const matches = dims.length === grain.length && dims.every((id) => grain.includes(id));
  if (matches) return null;
  return grain.length === 0
    ? 'Chỉ số này chỉ trả về một con số tổng, hãy chọn dạng KPI.'
    : 'Chỉ số này chỉ hỗ trợ chiều phân tích đã khai báo trong định nghĩa.';
}

/** Ready-to-save widgets derived from the metric's metadata (deterministic, no LLM). */
export function buildSuggestions(metricId: number, meta: WidgetMeta, grain: number[] | null): WidgetSuggestion[] {
  return buildAllSuggestions(metricId, meta).filter((suggestion) => validateGrain(suggestion.form, grain) === null);
}

function buildAllSuggestions(metricId: number, meta: WidgetMeta): WidgetSuggestion[] {
  const time = meta.columns.find((column) => column.is_time_dimension) ?? null;
  const base: WidgetFormState = { ...NEW_FORM, metricId, orderMetricId: metricId, dateFilterColumnId: time?.column_id ?? null };
  const out: WidgetSuggestion[] = [];
  if (time) {
    out.push({ key: 'kpi', label: `Con số tổng (lọc theo ${time.business_name})`, form: { ...base, chartType: 'kpi' } });
    out.push({
      key: 'trend',
      label: `Xu hướng theo tháng (${time.business_name})`,
      form: { ...base, chartType: 'line', dimensionColId: time.column_id, timeGrain: 'month', width: 'full' },
    });
  }
  for (const item of meta.dimensions.slice(0, 2)) {
    const chartType = recommendChartForDimensionItem(item);
    out.push({
      key: `dim-${item.column_id}`,
      label: `Theo ${item.business_name}`,
      form: { ...base, chartType, dimensionColId: item.column_id, width: 'half' },
    });
  }
  return out.filter((suggestion) => validateForm(suggestion.form) === null);
}

export function planMetricOptions(metrics: MetricRecord[], primaryId: number | null): MetricRecord[] {
  const primary = metrics.find((metric) => metric.metric_id === primaryId);
  if (!primary?.definition?.metric.query_plan) return [];
  return metrics.filter((metric) => metric.metric_id !== primaryId && metric.definition?.metric.query_plan);
}

function toCatalogColumn(item: RecommendedDimensionItem) {
  return {
    column_id: item.column_id,
    column_name: item.column_name,
    business_name: item.business_name,
    data_type: item.data_type,
    is_time_dimension: false,
    allowed_values: item.cardinality_hint ? Array.from({ length: item.cardinality_hint }) : null,
  };
}

/** Deterministic recommendation (no LLM): reuses the canonical rules. */
export function recommendChartForDimensionItem(item: RecommendedDimensionItem): DashboardChartType {
  return recommendDashboardChartType(toCatalogColumn(item));
}

export function createWidgetId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `w-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
