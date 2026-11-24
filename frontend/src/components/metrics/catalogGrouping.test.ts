import { describe, expect, it } from 'vitest';

import type { MetricRecord, SemanticCatalog } from '@/lib/api';
import { groupMetrics, metricKind, UNGROUPED_LABEL } from './catalogGrouping';

function metric(id: number, overrides: Partial<NonNullable<MetricRecord['definition']>['metric']> = {}): MetricRecord {
  return {
    metric_id: id,
    name: `Metric ${id}`,
    source: 'ai',
    status: 'approved',
    created_at: '2026-01-01T00:00:00Z',
    definition: {
      schema_version: 2,
      metric: {
        name: `metric_${id}`,
        formula: { function: 'SUM', expression: 'amount' },
        base_entity: 'orders',
        base_entity_id: 1,
        filters: [],
        status: 'approved',
        excluded_notes: '',
        ...overrides,
      },
      diagnostics: [],
    },
  };
}

const catalog = {
  db_id: 8,
  source_type: 'live',
  query_supported: true,
  relationships: [],
  tables: [
    { table_id: 1, table_name: 'orders', business_name: 'Đơn hàng', columns: [] },
    { table_id: 2, table_name: 'customers', business_name: 'Khách hàng', columns: [] },
  ],
} as SemanticCatalog;

describe('metricKind', () => {
  it('classifies count, sum, ratio and other aggregates', () => {
    expect(metricKind(metric(1, { formula: { function: 'COUNT_DISTINCT', expression: 'id' } }))).toBe('count');
    expect(metricKind(metric(2))).toBe('sum');
    expect(metricKind(metric(3, { formula: { function: 'AVG', expression: 'x' } }))).toBe('other');
    expect(
      metricKind(metric(4, {
        formula: {
          function: 'COUNT',
          expression: 'id',
          ratio: {
            numerator: { function: 'COUNT', expression: 'id', filters: [] },
            denominator: { function: 'COUNT', expression: 'id', filters: [] },
          },
        },
      })),
    ).toBe('ratio');
  });

  it('trusts the query plan over a placeholder formula', () => {
    const planned = metric(5, {
      formula: { function: 'COUNT', expression: '*' },
      query_plan: {
        stages: [{ name: 'revenue', joins: [], group_by: [], filters: [], aggregates: [{ name: 'net', function: 'SUM', expression: 'net_revenue', filters: [] }] }],
        output_expression: 'revenue.net',
      },
    });
    expect(metricKind(planned)).toBe('sum');
  });
});

describe('groupMetrics', () => {
  it('uses business names, sorts larger groups first and keeps ungrouped last', () => {
    const legacy: MetricRecord = { ...metric(9), definition: null };
    const groups = groupMetrics(
      [metric(1, { base_entity: 'customers', base_entity_id: 2 }), legacy, metric(2), metric(3)],
      catalog,
    );
    expect(groups.map((group) => [group.label, group.metrics.length])).toEqual([
      ['Đơn hàng', 2],
      ['Khách hàng', 1],
      [UNGROUPED_LABEL, 1],
    ]);
  });

  it('falls back to the raw table name before the catalog loads', () => {
    expect(groupMetrics([metric(1)], null)[0].label).toBe('orders');
  });
});
