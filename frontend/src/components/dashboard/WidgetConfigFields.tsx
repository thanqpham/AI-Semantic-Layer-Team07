'use client';

import { useState } from 'react';
import { FilterColumnItem, MetricRecord, RecommendedDimensionItem } from '@/lib/api';
import { DashboardChartType } from '@/lib/dashboard';
import { cn } from '@/lib/utils';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';
import {
  CHART_LABELS,
  filterMetricsByName,
  HEIGHT_LABELS,
  SELECT_CLASS,
  WIDTH_LABELS,
  WidgetFormState,
} from './widgetConfigForm';

export function FormField({ label, id, children }: { label: string; id: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <Label htmlFor={id} className="text-xs font-medium text-muted-foreground"><Translated text={label} /></Label>
      {children}
    </div>
  );
}

export function MetricPicker({ metrics, value, onChange }: {
  metrics: MetricRecord[];
  value: number | null;
  onChange: (value: string) => void;
}) {
  const { translate } = useLanguage();
  const [search, setSearch] = useState('');
  const filtered = filterMetricsByName(metrics, search);
  return (
    <div className="flex flex-col gap-3">
      <FormField label="Tìm metric" id="widget-metric-search">
        <Input id="widget-metric-search" type="text" placeholder={translate('Tìm metric đã duyệt…')} value={search} onChange={(event) => setSearch(event.target.value)} />
      </FormField>
      <FormField label="Metric" id="widget-metric">
        <select id="widget-metric" className={SELECT_CLASS} value={value === null ? '' : String(value)} onChange={(event) => onChange(event.target.value)}>
          {filtered.map((metric) => <option key={metric.metric_id} value={String(metric.metric_id)}>{metric.name}</option>)}
        </select>
      </FormField>
      {filtered.length === 0 && <p className="text-xs text-muted-foreground"><Translated text="Không có metric đã duyệt nào." /></p>}
    </div>
  );
}

export function MetricComparePicker({ metrics, value, disabled, onChange }: {
  metrics: MetricRecord[];
  value: number[];
  disabled: boolean;
  onChange: (values: number[]) => void;
}) {
  const { translate } = useLanguage();
  return (
    <FormField label="Thêm metric để so sánh" id="widget-metric-compare">
      <select
        id="widget-metric-compare"
        multiple
        size={Math.min(4, Math.max(2, metrics.length))}
        className={SELECT_CLASS}
        disabled={disabled || metrics.length === 0}
        value={value.map(String)}
        aria-describedby="widget-metric-compare-help"
        onChange={(event) => onChange(Array.from(event.currentTarget.selectedOptions, (option) => Number(option.value)))}
      >
        {metrics.map((metric) => <option key={metric.metric_id} value={metric.metric_id}>{metric.name}</option>)}
      </select>
      <p id="widget-metric-compare-help" className="text-xs text-muted-foreground">
        {translate('Chỉ metric có query plan được phép ghép; chọn tối đa 4 metric bổ sung.')}
      </p>
    </FormField>
  );
}

export function DimensionField({ form, dimensions, timeColumns, recommendation, onSelect }: {
  form: WidgetFormState;
  dimensions: RecommendedDimensionItem[];
  timeColumns: FilterColumnItem[];
  recommendation: DashboardChartType | null;
  onSelect: (columnId: number | null) => void;
}) {
  const { translate } = useLanguage();
  const isTimeSeries = form.chartType === 'line' || form.chartType === 'area';
  const options = isTimeSeries
    ? timeColumns.map((column) => ({ id: column.column_id, name: column.business_name }))
    : dimensions.map((item) => ({ id: item.column_id, name: item.business_name }));
  return (
    <FormField label={isTimeSeries ? 'Cột thời gian' : 'Chiều dữ liệu'} id="widget-dimension">
      <div className="flex items-center gap-2">
        <select id="widget-dimension" className={cn(SELECT_CLASS, 'flex-1')} value={form.dimensionColId ?? ''} onChange={(event) => onSelect(event.target.value === '' ? null : Number(event.target.value))}>
          <option value="">{translate('— Chọn —')}</option>
          {options.map((option) => <option key={option.id} value={option.id}>{option.name}</option>)}
        </select>
        {recommendation && <span className="whitespace-nowrap rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary"><Translated text="Đề xuất:" after />{translate(CHART_LABELS[recommendation])}</span>}
      </div>
    </FormField>
  );
}

export function DateFilterField({ timeColumns, value, required, onChange }: {
  timeColumns: FilterColumnItem[];
  value: number | null;
  required: boolean;
  onChange: (columnId: number | null) => void;
}) {
  const { translate } = useLanguage();
  return (
    <FormField label="Cột lọc ngày" id="widget-date-filter">
      <select id="widget-date-filter" className={SELECT_CLASS} aria-required={required} value={value ?? ''} onChange={(event) => onChange(event.target.value === '' ? null : Number(event.target.value))}>
        {!required && <option value="">{translate('Không áp dụng')}</option>}
        {timeColumns.map((column) => <option key={column.column_id} value={column.column_id}>{column.business_name}</option>)}
      </select>
    </FormField>
  );
}

export function LayoutFields({ form, onPatch }: {
  form: WidgetFormState;
  onPatch: (patch: Partial<WidgetFormState>) => void;
}) {
  const { translate } = useLanguage();
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <FormField label="Độ rộng" id="widget-width">
        <select id="widget-width" className={SELECT_CLASS} value={form.width} onChange={(event) => onPatch({ width: event.target.value as typeof form.width })}>
          {(Object.keys(WIDTH_LABELS) as (keyof typeof WIDTH_LABELS)[]).map((width) => <option key={width} value={width}>{translate(WIDTH_LABELS[width])}</option>)}
        </select>
      </FormField>
      <FormField label="Chiều cao" id="widget-height">
        <select id="widget-height" className={SELECT_CLASS} value={form.height} onChange={(event) => onPatch({ height: event.target.value as typeof form.height })}>
          {(Object.keys(HEIGHT_LABELS) as (keyof typeof HEIGHT_LABELS)[]).map((height) => <option key={height} value={height}>{translate(HEIGHT_LABELS[height])}</option>)}
        </select>
      </FormField>
      <div className="sm:col-span-2">
        <FormField label="Tiêu đề widget" id="widget-title">
          <Input id="widget-title" type="text" maxLength={200} placeholder={translate('Bỏ trống để dùng tên metric')} value={form.title} onChange={(event) => onPatch({ title: event.target.value })} />
        </FormField>
      </div>
    </div>
  );
}
