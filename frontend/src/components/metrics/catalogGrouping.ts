/**
 * Pure helpers that group catalog metrics by business entity and classify them
 * by kind (count / sum / ratio / other). No React or network access.
 */

import type { MetricRecord, SemanticCatalog } from '@/lib/api';

export type MetricKind = 'count' | 'sum' | 'ratio' | 'other';

export const METRIC_KIND_LABELS: Record<MetricKind, string> = {
  count: 'Đếm',
  sum: 'Tổng',
  ratio: 'Tỷ lệ',
  other: 'Khác',
};

export const UNGROUPED_LABEL = 'Chưa phân nhóm';

export interface MetricGroup {
  key: string;
  label: string;
  metrics: MetricRecord[];
}

/** Classify by the aggregate that produces the final value (query plans win over the legacy formula). */
export function metricKind(metric: MetricRecord): MetricKind {
  const definition = metric.definition?.metric;
  if (!definition) return 'other';
  if (definition.formula.ratio) return 'ratio';
  const stages = definition.query_plan?.stages ?? [];
  const fn = stages.length > 0 ? stages[stages.length - 1].aggregates[0]?.function : definition.formula.function;
  if (fn === 'COUNT' || fn === 'COUNT_DISTINCT') return 'count';
  if (fn === 'SUM') return 'sum';
  return 'other';
}

/** Business name of the metric's base entity, falling back to the raw table name. */
export function metricGroup(metric: MetricRecord, catalog: SemanticCatalog | null): { key: string; label: string } {
  const definition = metric.definition?.metric;
  if (!definition?.base_entity) return { key: UNGROUPED_LABEL, label: UNGROUPED_LABEL };
  const table = catalog?.tables.find((item) =>
    definition.base_entity_id != null ? item.table_id === definition.base_entity_id : item.table_name === definition.base_entity,
  );
  return { key: definition.base_entity, label: table?.business_name || definition.base_entity };
}

/** Group metrics, largest group first, ungrouped last; keeps metric order inside each group. */
export function groupMetrics(metrics: MetricRecord[], catalog: SemanticCatalog | null): MetricGroup[] {
  const groups = new Map<string, MetricGroup>();
  for (const metric of metrics) {
    const { key, label } = metricGroup(metric, catalog);
    const group = groups.get(key) ?? { key, label, metrics: [] };
    group.metrics.push(metric);
    groups.set(key, group);
  }
  return Array.from(groups.values()).sort((a, b) => {
    if (a.key === UNGROUPED_LABEL) return 1;
    if (b.key === UNGROUPED_LABEL) return -1;
    return b.metrics.length - a.metrics.length || a.label.localeCompare(b.label, 'vi');
  });
}
