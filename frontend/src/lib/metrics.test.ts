import { describe, expect, it } from 'vitest';

import { MetricSuggestion } from '@/lib/api';
import {
  applySuggestedName,
  coerceFilterValue,
  createMetricDefinition,
  getMetricUsedColumns,
  formatMetricFormula,
  formatMetricFilters,
  renderMetricYaml,
} from '@/lib/metrics';

describe('metric definition utilities', () => {
  it('joins conditions within a scope and keeps false, zero and null operators clear', () => {
    const definition = createMetricDefinition('orders');
    definition.metric.filters = [
      { field: 'active', operator: 'eq', value: false },
      { field: 'amount', operator: 'gte', value: 0 },
      { field: 'deleted_at', operator: 'is_not_null', value: null },
    ];
    expect(formatMetricFilters(definition)).toEqual([
      'Chung: active = false VÀ amount ≥ 0 VÀ deleted_at khác NULL',
    ]);
  });
  it('renders stable Unicode YAML without empty filters', () => {
    const definition = createMetricDefinition('OrderItem');
    definition.metric.name = 'Doanh thu';
    definition.metric.formula.expression = 'quantity * unit_price';
    definition.metric.excluded_notes = 'Chưa trừ hoàn tiền';
    const yaml = renderMetricYaml(definition);
    expect(yaml).toContain('name: Doanh thu');
    expect(yaml).toContain('Chưa trừ hoàn tiền');
    expect(yaml).not.toContain('filters:');
  });

  it('converts operator-specific filter values', () => {
    expect(coerceFilterValue('in', '1, 2, active')).toEqual([1, 2, 'active']);
    expect(coerceFilterValue('is_null', 'ignored')).toBeNull();
    expect(coerceFilterValue('eq', 'true')).toBe(true);
  });

  it('lists formula, ratio, and filter columns once without including function names', () => {
    const definition = createMetricDefinition('orders');
    definition.metric.formula = {
      function: 'SUM',
      expression: 'amount',
      ratio: {
        numerator: {
          function: 'SUM',
          expression: 'price_after_discount',
          filters: [{ field: 'region', operator: 'eq', value: 'north' }],
        },
        denominator: {
          function: 'COUNT_DISTINCT',
          expression: 'order_id',
          filters: [{ field: 'channel', operator: 'eq', value: 'online' }],
        },
      },
    };
    definition.metric.filters = [{ field: 'status', operator: 'eq', value: 'paid' }];

    expect(getMetricUsedColumns(definition)).toEqual([
      'price_after_discount',
      'order_id',
      'status',
      'region',
      'channel',
    ]);
  });

  it('extracts timestamp-difference columns and ignores literals and functions', () => {
    const definition = createMetricDefinition('orders');
    definition.metric.formula = {
      function: 'AVG',
      expression: 'TIMESTAMP_DIFF_HOURS(delivered_at, created_at) + 2',
    };

    expect(getMetricUsedColumns(definition)).toEqual(['delivered_at', 'created_at']);
  });

  it('shows the plan expression and lists qualified source columns for a multi-table metric', () => {
    const definition = createMetricDefinition('orders');
    definition.metric.query_plan = {
      stages: [
        {
          name: 'per_customer',
          base_entity: 'orders',
          joins: ['customers'],
          group_by: [{ name: 'customer_id', expression: 'customers.id' }],
          aggregates: [{ name: 'order_count', function: 'COUNT_DISTINCT', expression: 'orders.id', filters: [] }],
          filters: [],
        },
      ],
      output_expression: 'per_customer.order_count',
    };

    expect(formatMetricFormula(definition)).toBe('COUNT(DISTINCT orders.id)');
    expect(getMetricUsedColumns(definition)).toEqual(['id']);
  });

  it('renders COUNT_DISTINCT as SQL COUNT(DISTINCT ...)', () => {
    const definition = createMetricDefinition('orders');
    definition.metric.formula = { function: 'COUNT_DISTINCT', expression: 'customer_id' };
    expect(formatMetricFormula(definition)).toBe('COUNT(DISTINCT customer_id)');
  });

  it('formats ratio filters with readable operators', () => {
    const definition = createMetricDefinition('leads');
    definition.metric.formula.ratio = {
      numerator: { function: 'COUNT_DISTINCT', expression: 'id', filters: [{ field: 'converted_order_id', operator: 'is_not_null', value: null }] },
      denominator: { function: 'COUNT_DISTINCT', expression: 'id' },
      scale: 100,
    };
    expect(formatMetricFormula(definition)).toBe(
      '100 × (COUNT(DISTINCT id) WHERE converted_order_id khác NULL) / COUNT(DISTINCT id)',
    );
    expect(formatMetricFormula(definition, { conditions: false })).toBe('100 × COUNT(DISTINCT id) / COUNT(DISTINCT id)');
    definition.metric.formula.ratio.scale = 1;
    expect(formatMetricFormula(definition, { conditions: false })).toBe('COUNT(DISTINCT id) / COUNT(DISTINCT id)');
  });

  it('inlines stage refs in a plan ratio, leaving lookalike tokens alone', () => {
    const definition = createMetricDefinition('orders');
    const stage = (name: string, entity: string, expression: string) => ({
      name, base_entity: entity, joins: [], group_by: [], filters: [],
      aggregates: [{ name: 'n', function: 'COUNT_DISTINCT' as const, expression, filters: [] }],
    });
    definition.metric.query_plan = {
      stages: [stage('returned_orders', 'product_returns', 'product_returns.order_id'), stage('all_orders', 'orders', 'orders.id')],
      output_expression: 'returned_orders.n / all_orders.n + x.all_orders.n',
    };
    expect(formatMetricFormula(definition))
      .toBe('COUNT(DISTINCT product_returns.order_id) / COUNT(DISTINCT orders.id) + x.all_orders.n');
  });

  it('collapses a multi-stage plan into one expression with HAVING on the source aggregate', () => {
    const definition = createMetricDefinition('orders');
    definition.metric.query_plan = {
      stages: [
        { name: 'per_customer', base_entity: 'orders', joins: [], filters: [],
          group_by: [{ name: 'customer_id', expression: 'orders.customer_id' }],
          aggregates: [{ name: 'order_count', function: 'COUNT_DISTINCT', expression: 'orders.id', filters: [] }] },
        { name: 'repeat_customers', source_stage: 'per_customer', joins: [], group_by: [],
          filters: [{ field: 'order_count', operator: 'gte', value: 2 }],
          aggregates: [{ name: 'customers', function: 'COUNT', expression: '*', filters: [] }] },
        { name: 'total_customers', source_stage: 'per_customer', joins: [], group_by: [], filters: [],
          aggregates: [{ name: 'customers', function: 'COUNT', expression: '*', filters: [] }] },
      ],
      output_expression: 'repeat_customers.customers / total_customers.customers',
    };
    expect(formatMetricFormula(definition))
      .toBe('COUNT(customer_id HAVING COUNT(DISTINCT orders.id) ≥ 2) / COUNT(customer_id)');
    expect(formatMetricFormula(definition, { conditions: false })).toBe('COUNT(customer_id) / COUNT(customer_id)');
  });

  it('labels plan filters by numerator/denominator role and inlines prior-stage outputs', () => {
    const definition = createMetricDefinition('orders');
    definition.metric.filters = [{ field: 'orders.channel', operator: 'eq', value: 'Web' }];
    definition.metric.query_plan = {
      stages: [
        { name: 'per_customer', base_entity: 'orders', joins: [], group_by: [{ name: 'customer_id', expression: 'orders.customer_id' }],
          filters: [{ field: 'orders.status', operator: 'eq', value: 'completed' }],
          aggregates: [{ name: 'order_count', function: 'COUNT_DISTINCT', expression: 'orders.id', filters: [] }] },
        { name: 'repeat_customers', source_stage: 'per_customer', joins: [], group_by: [],
          filters: [{ field: 'order_count', operator: 'gte', value: 2 }],
          aggregates: [{ name: 'customers', function: 'COUNT', expression: '*', filters: [] }] },
        { name: 'all_customers', base_entity: 'customers', joins: [], group_by: [], filters: [],
          aggregates: [{ name: 'customers', function: 'COUNT', expression: '*',
            filters: [{ field: 'customers.region', operator: 'eq', value: 'North' }] }] },
      ],
      output_expression: 'repeat_customers.customers / all_customers.customers',
    };
    expect(formatMetricFilters(definition)).toEqual([
      'Chung (cả tử và mẫu): orders.channel = "Web"',
      'Tử số: orders.status = "completed" VÀ COUNT(DISTINCT orders.id WHERE orders.status = "completed") ≥ 2',
      'Mẫu số: customers.region = "North"',
    ]);
    expect(getMetricUsedColumns(definition)).not.toContain('order_count');
  });

  it('keeps base-stage filters inline as WHERE', () => {
    const definition = createMetricDefinition('orders');
    definition.metric.query_plan = {
      stages: [{ name: 'paid', base_entity: 'orders', joins: [], group_by: [],
        filters: [{ field: 'orders.status', operator: 'eq', value: 'paid' }],
        aggregates: [{ name: 'revenue', function: 'SUM', expression: 'orders.amount', filters: [] }] }],
      output_expression: 'paid.revenue',
    };
    expect(formatMetricFormula(definition)).toBe('SUM(orders.amount WHERE orders.status = "paid")');
  });
});

describe('applySuggestedName', () => {
  it('renames the metric, re-renders YAML, and drops the conflict flag', () => {
    const definition = createMetricDefinition('OrderItem');
    definition.metric.name = 'Doanh thu';
    definition.metric.formula.expression = 'quantity * unit_price';
    const suggestion: MetricSuggestion = {
      definition,
      yaml_preview: renderMetricYaml(definition),
      conflict: {
        proposed_metric_name: 'Doanh thu',
        existing_metric_id: 12,
        existing_metric_name: 'Doanh thu',
        existing_metric_status: 'approved',
        suggested_name: 'Doanh thu (mới)',
        clarify_question: 'Tên "Doanh thu" đã được dùng cho metric khác công thức. Bạn muốn đổi tên?',
      },
    };
    const inputSnapshot = JSON.parse(JSON.stringify(suggestion));

    const result = applySuggestedName(suggestion);

    expect(result.definition.metric.name).toBe('Doanh thu (mới)');
    expect(result.yaml_preview).toContain('Doanh thu (mới)');
    expect(result.yaml_preview).not.toContain('name: Doanh thu\n');
    expect(result.conflict).toBeUndefined();
    // Input is not mutated
    expect(suggestion).toEqual(inputSnapshot);
    expect(suggestion.definition.metric.name).toBe('Doanh thu');
  });

  it('returns the suggestion unchanged when there is no usable suggested name', () => {
    const definition = createMetricDefinition('OrderItem');
    definition.metric.name = 'Doanh thu';
    const plain: MetricSuggestion = { definition, yaml_preview: renderMetricYaml(definition) };
    const emptySuggestion: MetricSuggestion = {
      definition: createMetricDefinition('OrderItem'),
      yaml_preview: '',
      conflict: {
        proposed_metric_name: 'Doanh thu',
        existing_metric_id: null,
        existing_metric_name: 'Doanh thu',
        existing_metric_status: null,
        suggested_name: '   ',
        clarify_question: '',
      },
    };
    const plainSnapshot = JSON.parse(JSON.stringify(plain));
    const emptySnapshot = JSON.parse(JSON.stringify(emptySuggestion));

    expect(applySuggestedName(plain)).toEqual(plain);
    expect(applySuggestedName(emptySuggestion)).toEqual(emptySuggestion);

    // Inputs are not mutated
    expect(plain).toEqual(plainSnapshot);
    expect(emptySuggestion).toEqual(emptySnapshot);
  });
});
