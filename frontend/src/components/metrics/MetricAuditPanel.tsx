'use client';

import { AlertTriangle, GitCompare, Pencil, RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import {
  compareMetricsApi,
  MetricComparisonGroup,
  MetricComparisonResponse,
  MetricRecord,
} from '@/lib/api';
import { Translated } from '@/components/ui/translated';

interface MetricAuditPanelProps {
  dbId?: number | null;
  metrics: MetricRecord[];
  canEdit?: boolean;
  onEdit?: (metric: MetricRecord) => void;
}

export function MetricAuditPanel({ dbId, metrics, canEdit, onEdit }: MetricAuditPanelProps) {
  const [audit, setAudit] = useState<MetricComparisonResponse | null>(null);
  const [kind, setKind] = useState<'all' | 'exact_duplicate' | 'near_duplicate'>('all');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadAudit = async () => {
    if (!dbId) return;
    setLoading(true);
    setError(null);
    try {
      setAudit(await compareMetricsApi(dbId));
    } catch {
      setError('Không thể tải kết quả so sánh metric. Vui lòng thử lại.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadAudit();
  }, [dbId, metrics]);

  const groups = audit?.groups.filter((group) => kind === 'all' || group.group_type === kind) ?? [];
  const findMetric = (id: number) => metrics.find((metric) => metric.metric_id === id);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <AuditStat label="Đã phân tích" value={audit?.analyzed_metric_count ?? 0} />
        <AuditStat label="Trùng hoàn toàn" value={audit?.exact_duplicate_count ?? 0} tone="red" />
        <AuditStat label="Near-duplicate" value={audit?.near_duplicate_count ?? 0} tone="amber" />
      </div>

      <div className="flex items-center justify-between gap-2">
        <div className="flex gap-1 rounded-lg border border-border bg-card p-1">
          {([
            ['all', 'Tất cả'],
            ['exact_duplicate', 'Trùng hoàn toàn'],
            ['near_duplicate', 'Khác filter'],
          ] as const).map(([value, label]) => (
            <button key={value} type="button" onClick={() => setKind(value)}
              className={`rounded-md px-3 py-1.5 text-xs ${kind === value ? 'bg-primary text-primary-foreground font-semibold' : 'text-muted-foreground hover:text-foreground'}`}>
              {label}
            </button>
          ))}
        </div>
        <Button size="sm" variant="outline" onClick={() => void loadAudit()} disabled={loading}>
          <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} /> <Translated text={"Làm mới"} /></Button>
      </div>

      {error && <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-600"><AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />{error}</div>}
      {loading && !audit && <div role="status" className="p-8 text-center text-xs text-muted-foreground"><Translated text={"Đang phân tích Catalog..."} /></div>}
      {!loading && audit && groups.length === 0 && <EmptyAudit />}
      <div className="space-y-3">
        {groups.map((group, index) => (
          <AuditGroup key={`${group.group_type}-${group.core_formula}-${index}`} group={group} canEdit={canEdit} onEdit={findMetric} onEditMetric={onEdit} />
        ))}
      </div>
    </div>
  );
}

function AuditStat({ label, value, tone = 'default' }: { label: string; value: number; tone?: string }) {
  return <div className="rounded-lg border border-border bg-card p-4"><p className="text-[11px] text-muted-foreground">{label}</p><p className={`mt-1 text-2xl font-semibold ${tone === 'red' ? 'text-red-500' : tone === 'amber' ? 'text-amber-500' : 'text-foreground'}`}>{value}</p></div>;
}

function AuditGroup({ group, canEdit, onEdit, onEditMetric }: { group: MetricComparisonGroup; canEdit?: boolean; onEdit: (id: number) => MetricRecord | undefined; onEditMetric?: (metric: MetricRecord) => void }) {
  const memberFilters = (member: MetricComparisonGroup['members'][number]) => {
    const filters = member.filters.map((filter) => `${filter.field} ${filter.operator} ${String(filter.value)}`);
    filters.push(...(member.ratio?.numerator.filters ?? []).map(
      (filter) => `Tử: ${filter.field} ${filter.operator} ${String(filter.value)}`,
    ));
    filters.push(...(member.ratio?.denominator.filters ?? []).map(
      (filter) => `Mẫu: ${filter.field} ${filter.operator} ${String(filter.value)}`,
    ));
    return filters.length ? filters.join('; ') : 'Không có filter';
  };

  return <article className="rounded-lg border border-border bg-card p-4">
    <div className="flex items-start justify-between gap-3">
      <div><div className="flex items-center gap-2"><GitCompare className="h-4 w-4 text-primary" /><h3 className="text-sm font-semibold"><Translated text={group.group_type === 'exact_duplicate' ? 'Metric trùng hoàn toàn' : 'Metric cùng lõi, khác filter'} /></h3></div><p className="mt-1 font-mono text-xs text-muted-foreground">{group.core_formula} · {group.base_entity}</p></div>
      <span className="rounded-full bg-secondary px-2 py-1 text-[10px] text-muted-foreground">{group.members.length} <Translated text={"metric"} /></span>
    </div>
    {group.group_type === 'near_duplicate' && <p className="mt-3 rounded-md bg-amber-500/10 p-2 text-xs text-amber-700 dark:text-amber-300"><Translated text={"Cùng công thức lõi, khác bộ lọc nghiệp vụ. Hãy xác nhận các filter này có thực sự là định nghĩa riêng."} /></p>}
    <div className="mt-3 divide-y divide-border rounded-md border border-border">
      {group.members.map((member) => <div key={member.metric_id} className="flex items-center justify-between gap-3 p-3"><div className="min-w-0"><p className="truncate text-xs font-medium">{member.name}</p><p className="mt-1 text-[11px] text-muted-foreground">{memberFilters(member)}</p></div>{canEdit && onEditMetric && <Button size="sm" variant="ghost" onClick={() => { const metric = onEdit(member.metric_id); if (metric) onEditMetric(metric); }}><Pencil className="mr-1 h-3 w-3" /><Translated text={"Sửa"} /></Button>}</div>)}
    </div>
  </article>;
}

function EmptyAudit() { return <div className="rounded-lg border border-dashed border-border p-10 text-center text-xs text-muted-foreground"><Translated text={"Không phát hiện nhóm metric trùng hoặc gần trùng."} /></div>; }
