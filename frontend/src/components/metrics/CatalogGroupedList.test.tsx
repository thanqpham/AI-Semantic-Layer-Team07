import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { MetricRecord, SemanticCatalog } from '@/lib/api';
import { CatalogGroupedList } from './CatalogGroupedList';

function metric(id: number, name: string, baseEntity: string, fn: 'SUM' | 'COUNT'): MetricRecord {
  return {
    metric_id: id,
    name,
    source: 'ai',
    status: 'approved',
    created_at: '2026-01-01T00:00:00Z',
    definition: {
      schema_version: 2,
      metric: { name, formula: { function: fn, expression: 'x' }, base_entity: baseEntity, filters: [], status: 'approved', excluded_notes: '' },
      diagnostics: [],
    },
  };
}

const catalog = {
  db_id: 1, source_type: 'live', query_supported: true, relationships: [],
  tables: [
    { table_id: 1, table_name: 'orders', business_name: 'Đơn hàng', columns: [] },
    { table_id: 2, table_name: 'customers', business_name: 'Khách hàng', columns: [] },
  ],
} as SemanticCatalog;

const metrics = [
  metric(1, 'Doanh thu', 'orders', 'SUM'),
  metric(2, 'Số đơn', 'orders', 'COUNT'),
  metric(3, 'Số khách', 'customers', 'COUNT'),
];

afterEach(cleanup);

describe('CatalogGroupedList', () => {
  it('groups by business entity and narrows by kind', () => {
    render(<CatalogGroupedList metrics={metrics} catalog={catalog} renderCard={(m) => <p key={m.metric_id}>{m.name}</p>} />);
    expect(screen.getByRole('region', { name: 'Đơn hàng' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Khách hàng' })).toBeInTheDocument();

    expect(screen.queryByRole('navigation', { name: 'Nhóm nghiệp vụ' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Đếm' }));
    expect(screen.getByText('Số đơn')).toBeInTheDocument();
    expect(screen.getByText('Số khách')).toBeInTheDocument();
    expect(screen.queryByText('Doanh thu')).not.toBeInTheDocument();
  });
});
