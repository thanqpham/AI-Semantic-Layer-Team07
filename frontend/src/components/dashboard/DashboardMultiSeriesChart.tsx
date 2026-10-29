'use client';

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { DashboardPoint, formatCellValue, formatShortNumber, sortPointsByTimeKey } from './dashboardFormatters';

const SERIES_COLORS = [1, 2, 3, 4, 5].map((n) => `var(--color-chart-${n})`);
const CHART_MARGIN = { top: 8, right: 12, left: 0, bottom: 4 };

export function DashboardMultiSeriesChart({ chartType, series, points }: {
  chartType: 'line' | 'area' | 'bar';
  series: Array<{ id: number; name: string }>;
  points: DashboardPoint[];
}) {
  const ordered = chartType === 'bar' ? points : sortPointsByTimeKey(points);
  const displayed = chartType === 'bar' ? ordered.slice(0, 12) : ordered;
  const rows = displayed.map((point) => ({ ...point, ...seriesData(point, series) }));
  return (
    <div className="min-h-0 flex-1 rounded-lg bg-gradient-to-b from-primary/[0.04] to-transparent">
      <ResponsiveContainer width="100%" height="100%">
        {chartType === 'bar' ? (
          <BarChart data={rows} margin={CHART_MARGIN}>
            <ChartAxes /><Tooltip content={<MultiTooltipCard />} /><Legend />
            {series.map((item, index) => <Bar key={item.id} dataKey={`metric_${item.id}`} name={item.name} fill={SERIES_COLORS[index % SERIES_COLORS.length]} radius={[4, 4, 0, 0]} isAnimationActive={false} />)}
          </BarChart>
        ) : chartType === 'line' ? (
          <LineChart data={rows} margin={CHART_MARGIN}>
            <ChartAxes /><Tooltip content={<MultiTooltipCard />} /><Legend />
            {series.map((item, index) => <Line key={item.id} type="monotone" dataKey={`metric_${item.id}`} name={item.name} stroke={SERIES_COLORS[index % SERIES_COLORS.length]} strokeWidth={2.5} dot={{ r: 3 }} isAnimationActive={false} />)}
          </LineChart>
        ) : (
          <AreaChart data={rows} margin={CHART_MARGIN}>
            <ChartAxes /><Tooltip content={<MultiTooltipCard />} /><Legend />
            {series.map((item, index) => <Area key={item.id} type="monotone" dataKey={`metric_${item.id}`} name={item.name} stroke={SERIES_COLORS[index % SERIES_COLORS.length]} fill={SERIES_COLORS[index % SERIES_COLORS.length]} fillOpacity={0.16} isAnimationActive={false} />)}
          </AreaChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

function seriesData(point: DashboardPoint, series: Array<{ id: number; name: string }>): Record<string, number | null> {
  return Object.fromEntries(series.map((item, index) => [
    `metric_${item.id}`,
    point.seriesValues?.[item.id] ?? (index === 0 ? point.value : null),
  ]));
}

function MultiTooltipCard({ active, payload, label }: {
  active?: boolean;
  payload?: Array<{ value?: unknown; name?: string }>;
  label?: unknown;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-popover px-3 py-2 text-xs shadow-md">
      <p className="font-semibold text-popover-foreground">{String(label ?? '')}</p>
      {payload.map((item) => <p key={item.name} className="mt-0.5 font-mono font-medium text-primary">{item.name}: {formatCellValue(item.value)}</p>)}
    </div>
  );
}

export function ChartAxes() {
  return <><CartesianGrid strokeDasharray="3 3" vertical={false} className="stroke-border/40" /><XAxis dataKey="label" tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={16} angle={-15} textAnchor="end" height={48} tick={{ fontSize: 10 }} className="fill-muted-foreground" /><YAxis tickLine={false} axisLine={false} width={52} tickFormatter={(value: unknown) => formatShortNumber(Number(value))} tick={{ fontSize: 10 }} className="fill-muted-foreground" /></>;
}
