import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { executeSemanticQueryApi } from '@/lib/api';
import type { DashboardWidgetConfig } from '@/lib/dashboard';
import { clearDashboardPayloadCache, useDashboardWidgetData } from './useDashboardWidgetData';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/lib/api')>(),
  executeSemanticQueryApi: vi.fn(),
}));

const query = vi.mocked(executeSemanticQueryApi);
const widget: DashboardWidgetConfig = {
  id: 'one', metric_id: 5, dimension_col_id: 3, date_filter_column_id: null,
  time_grain: null, chart_type: 'pie', width: 'half', height: 'normal', custom_title: null,
};

function load(chart_type: DashboardWidgetConfig['chart_type']) {
  return renderHook(() => useDashboardWidgetData({
    dbId: 1, widget: { ...widget, chart_type, time_grain: chart_type === 'line' ? 'month' : null },
    globalGrain: null, datePreset: null, refreshGeneration: 0, enabled: true,
  }));
}

describe('dashboard bounded results', () => {
  beforeEach(() => { clearDashboardPayloadCache(); query.mockReset(); });

  it('shows only fetched top pie groups without inventing an Other slice', async () => {
    query.mockResolvedValue({
      sql: '', parameters: {}, columns: ['dimension_3', 'metric_5'], row_count: 101,
      rows: Array.from({ length: 101 }, (_, i) => [`group ${i}`, 101 - i]),
    });
    const { result } = load('pie');
    await waitFor(() => expect(result.current.status).toBe('success'));
    expect(result.current.hasMore).toBe(true);
    expect(result.current.points).toHaveLength(8);
    expect(result.current.points.every((point) => point.label !== 'Khác')).toBe(true);
  });

  it('keeps only the newest hundred periods and preserves missing values', async () => {
    query.mockResolvedValue({
      sql: '', parameters: {}, columns: ['dimension_3', 'metric_5'], row_count: 101,
      rows: Array.from({ length: 101 }, (_, i) => [String(2025 - i), i === 0 ? null : i]),
    });
    const { result } = load('line');
    await waitFor(() => expect(result.current.status).toBe('success'));
    expect(result.current.hasMore).toBe(true);
    expect(result.current.points).toHaveLength(100);
    expect(result.current.points.at(-1)?.value).toBeNull();
  });
});
