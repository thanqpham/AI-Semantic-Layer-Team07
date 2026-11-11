import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  createEavConfigApi,
  createEavMetricApi,
  createMetricApi,
  executeSemanticQueryApi,
  listEavConfigsApi,
  MetricDefinition,
  reviewEavConfigApi,
  rollbackMetricApi,
  SemanticApiError,
} from '@/lib/api';

const definition: MetricDefinition = {
  metric: {
    name: 'Doanh thu',
    formula: { function: 'SUM', expression: 'quantity * unit_price' },
    base_entity: 'OrderItem',
    filters: [],
    status: 'pending_approval',
    confidence: 'high',
    excluded_notes: '',
  },
};

describe('semantic adapter', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('persists canonical JSON and never sends SQL template', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ metric_id: 7, definition, source: 'ai' }), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    vi.stubGlobal('fetch', fetchMock);
    const record = await createMetricApi('5', { definition, source: 'ai' });
    const request = fetchMock.mock.calls[0][1] as RequestInit;
    const payload = JSON.parse(String(request.body));
    expect(record.metric_id).toBe(7);
    expect(payload.definition).toEqual(definition);
    expect(payload).not.toHaveProperty('sql_template');
  });

  it('preserves the backend-controlled status for Member submissions', async () => {
    const response = {
      metric_id: 7,
      definition,
      source: 'manual',
      status: 'unverified',
    };
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(response), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );

    const record = await createMetricApi('5', { definition, source: 'manual' });

    expect(record.status).toBe('unverified');
  });

  it('keeps the backend permission error visible', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ detail: 'Member chỉ được gửi metric mới.' }), {
            status: 403,
            headers: { 'Content-Type': 'application/json' },
          }),
        ),
    );

    await expect(createMetricApi('5', { definition, source: 'manual' })).rejects.toEqual(
      new SemanticApiError(403, 'Member chỉ được gửi metric mới.', 'Member chỉ được gửi metric mới.'),
    );
  });

  it('executes only semantic selections and returns compiled results', async () => {
    const response = {
      sql: 'SELECT COUNT(*) FROM orders LIMIT 100',
      parameters: {},
      columns: ['count'],
      rows: [[2]],
      row_count: 1,
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    await executeSemanticQueryApi('5', {
      metric_ids: [7],
      dimensions: [{ column_id: 11 }],
      filters: [],
      limit: 100,
    });
    const payload = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body));
    expect(payload).toEqual({
      metric_ids: [7],
      dimensions: [{ column_id: 11 }],
      filters: [],
      limit: 100,
    });
    expect(payload).not.toHaveProperty('sql');
  });

  it('rolls back by posting to the exact versioned path and maps the mutation response', async () => {
    const response = {
      metric_id: 7,
      definition,
      source: 'manual',
      status: 'approved',
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const record = await rollbackMetricApi('5', 7, 2);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/v1\/semantic\/5\/metric\/7\/rollback\/2$/);
    expect((init as RequestInit).method).toBe('POST');
    expect(record.metric_id).toBe(7);
    expect(record.status).toBe('approved');
    expect(record.definition).toEqual(definition);
  });

  it('propagates backend rollback failures as SemanticApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'Chỉ được phép khôi phục về phiên bản cũ hơn.' }), {
          status: 422,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );

    await expect(rollbackMetricApi('5', 7, 3)).rejects.toEqual(
      new SemanticApiError(
        422,
        'Chỉ được phép khôi phục về phiên bản cũ hơn.',
        'Chỉ được phép khôi phục về phiên bản cũ hơn.',
      ),
    );
  });
});

describe('eav source configs', () => {
  afterEach(() => vi.unstubAllGlobals());

  const config = {
    id: 3,
    name: 'EAV chính',
    entity_table: 'entity_eav',
    entity_id_column: 'entity_id',
    attribute_mode: 'direct',
    attribute_column: 'attr_code',
    attribute_fk_column: null,
    dict_table: null,
    dict_key_column: null,
    dict_label_column: null,
    value_columns: { number: 'value_num', string: 'value_str' },
    history: null,
    review_status: 'pending_review',
    reviewed_by: null,
    reviewed_at: null,
    created_at: '2026-11-11T00:00:00',
    attributes: [
      {
        id: 11,
        attribute_key: 'revenue',
        label: 'Doanh thu',
        description: '',
        data_type: 'number',
        value_column: null,
        multi_value_rule: 'reject',
        history_enabled: false,
      },
    ],
  };

  it('creates an EAV config and surfaces backend validation errors', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(config), { status: 201, headers: { 'Content-Type': 'application/json' } }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(['Cột "ghost" không tồn tại']), {
          status: 422,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    vi.stubGlobal('fetch', fetchMock);
    const payload = {
      name: 'EAV chính',
      entity_table: 'entity_eav',
      entity_id_column: 'entity_id',
      attribute_mode: 'direct' as const,
      attribute_column: 'attr_code',
      value_columns: { number: 'value_num', string: 'value_str' },
      attributes: [
        { attribute_key: 'revenue', label: 'Doanh thu', data_type: 'number' as const },
      ],
    };
    await expect(createEavConfigApi(5, payload)).resolves.toMatchObject({ id: 3, review_status: 'pending_review' });
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/api\/v1\/semantic\/5\/eav-configs$/);
    await expect(createEavConfigApi(5, payload)).rejects.toMatchObject({ status: 422 });
  });

  it('lists, reviews, and creates metrics from approved configs', async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: RequestInfo | URL, init?: RequestInit) => {
      const path = String(url);
      const method = init?.method || 'GET';
      if (path.endsWith('/eav-configs') && method === 'GET') {
        return new Response(JSON.stringify({ items: [config] }), { headers: { 'Content-Type': 'application/json' } });
      }
      if (path.endsWith('/review')) {
        return new Response(JSON.stringify({ ...config, review_status: 'approved' }), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (/\/attributes\/11\/metric$/.test(path)) {
        return new Response(
          JSON.stringify({ metric_id: 42, name: 'Tổng doanh thu', status: 'draft' }),
          { status: 201, headers: { 'Content-Type': 'application/json' } },
        );
      }
      return new Response(JSON.stringify({}), { status: 404 });
    });
    vi.stubGlobal('fetch', fetchMock);
    await expect(listEavConfigsApi(5)).resolves.toHaveLength(1);
    await expect(reviewEavConfigApi(5, 3, 'approve')).resolves.toMatchObject({ review_status: 'approved' });
    await expect(createEavMetricApi(5, 3, 11, { aggregation: 'SUM', name: 'Tổng doanh thu' })).resolves.toMatchObject(
      { metric_id: 42 },
    );
  });

  it('sends eav_dimensions and as_of with the query request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ sql: 'SELECT 1', columns: [], rows: [], row_count: 0 }), {
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    await executeSemanticQueryApi('5', {
      metric_ids: [42],
      eav_dimensions: [{ attribute_id: 12 }],
      as_of: '2026-05-01T00:00:00',
      filters: [],
      limit: 100,
    });
    const body = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body));
    expect(body.eav_dimensions).toEqual([{ attribute_id: 12 }]);
    expect(body.as_of).toBe('2026-05-01T00:00:00');
  });
});
