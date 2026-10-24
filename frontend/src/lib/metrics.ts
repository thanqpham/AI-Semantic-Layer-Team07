import YAML from 'yaml';
import {
  FilterOperator,
  MetricDefinition,
  MetricRecord,
  MetricSuggestion,
  MetricStatus,
} from '@/lib/api';

export function createMetricDefinition(baseEntity: string = ''): MetricDefinition {
  return {
    metric: {
      name: '',
      formula: {
        function: 'SUM',
        expression: '',
      },
      base_entity: baseEntity,
      filters: [],
      status: 'pending_approval',
      confidence: 'high',
      excluded_notes: '',
    },
  };
}

export function formatMetricFormula(definition: MetricDefinition): string {
  const formula = definition.metric.formula;
  if (!formula.ratio) {
    const prefix = formula.expression.includes('/') ? 'Cần xem xét · ' : '';
    return `${prefix}${formula.function}(${formula.expression})`;
  }

  const numerator = formatAggregate(formula.ratio.numerator);
  const denominator = formatAggregate(formula.ratio.denominator);
  const scale = formula.ratio.scale ?? 1;
  const offset = formula.ratio.offset ?? 0;
  const ratio = `${scale} × (${numerator}) / (${denominator})`;
  return offset ? `${offset} + ${ratio}` : ratio;
}

export function getMetricUsedColumns(definition: MetricDefinition): string[] {
  const { formula, filters } = definition.metric;
  const expressions = formula.ratio
    ? [formula.ratio.numerator.expression, formula.ratio.denominator.expression]
    : [formula.expression];
  const names = new Map<string, string>();

  for (const expression of expressions) {
    const tokens = /'(?:''|[^'])*'|"(?:\"\"|[^"])*"|`(?:``|[^`])*`|[A-Za-z_][A-Za-z0-9_$]*/g;
    let match: RegExpExecArray | null;
    while ((match = tokens.exec(expression)) !== null) {
      const token = match[0];
      if (token.startsWith("'")) continue;

      const isQuotedIdentifier = token.startsWith('"') || token.startsWith('`');
      const name = isQuotedIdentifier ? token.slice(1, -1).replace(/(["`])\1/g, '$1') : token;
      const precedingCharacter = expression[match.index - 1];
      if (!isQuotedIdentifier && precedingCharacter && /[A-Za-z0-9_$]/.test(precedingCharacter)) continue;
      if (!isQuotedIdentifier && /^(true|false|null)$/i.test(name)) continue;
      if (/^\s*\(/.test(expression.slice(tokens.lastIndex))) continue;
      names.set(name.toLowerCase(), names.get(name.toLowerCase()) || name);
    }
  }

  const ratio = formula.ratio;
  const allFilters = [
    ...filters,
    ...(ratio?.numerator.filters || []),
    ...(ratio?.denominator.filters || []),
  ];
  for (const filter of allFilters) {
    const key = filter.field.toLowerCase();
    names.set(key, names.get(key) || filter.field);
  }

  return [...names.values()];
}

function formatAggregate(aggregate: NonNullable<MetricDefinition['metric']['formula']['ratio']>['numerator']): string {
  const filters = aggregate.filters
    ?.map((item) => `${item.field} ${item.operator} ${JSON.stringify(item.value)}`)
    .sort();
  const filterText = filters?.length ? ` WHERE ${filters.join(' AND ')}` : '';
  return `${aggregate.function}(${aggregate.expression})${filterText}`;
}

export function withPendingStatus(definition: MetricDefinition): MetricDefinition {
  return {
    metric: {
      ...definition.metric,
      status: 'pending_approval',
    },
  };
}

export function metricName(item: MetricRecord | MetricDefinition | null | undefined): string {
  if (!item) return 'Chưa đặt tên';
  if ('name' in item && typeof item.name === 'string' && item.name) {
    return item.name;
  }
  if ('metric' in item && item.metric?.name) {
    return item.metric.name;
  }
  if ('definition' in item && item.definition?.metric?.name) {
    return item.definition.metric.name;
  }
  return 'Chưa đặt tên';
}

export function statusLabel(status?: MetricStatus | string): string {
  switch (status) {
    case 'approved':
      return 'Đã duyệt';
    case 'pending_approval':
      return 'Chờ duyệt';
    case 'draft':
      return 'Bản nháp';
    case 'needs_review':
      return 'Cần xem xét';
    default:
      return status || 'Chờ duyệt';
  }
}

export function coerceFilterValue(operator: FilterOperator | string, rawValue: string): unknown {
  if (operator === 'is_null' || operator === 'is_not_null') {
    return null;
  }
  if (operator === 'in' || operator === 'not_in') {
    return rawValue
      .split(',')
      .map((item) => {
        const t = item.trim();
        if (t !== '' && !isNaN(Number(t))) return Number(t);
        if (t.toLowerCase() === 'true') return true;
        if (t.toLowerCase() === 'false') return false;
        return t;
      })
      .filter(Boolean);
  }
  const trimmed = rawValue.trim();
  if (trimmed === '') return null;
  if (!isNaN(Number(trimmed))) {
    return Number(trimmed);
  }
  if (trimmed.toLowerCase() === 'true') return true;
  if (trimmed.toLowerCase() === 'false') return false;
  return trimmed;
}

export function renderMetricYaml(definition?: MetricDefinition | null): string {
  if (!definition) return '';
  const clone = JSON.parse(JSON.stringify(definition));
  if (clone.metric && Array.isArray(clone.metric.filters) && clone.metric.filters.length === 0) {
    delete clone.metric.filters;
  }
  try {
    return YAML.stringify(clone);
  } catch {
    return JSON.stringify(clone, null, 2);
  }
}

export function applySuggestedName(suggestion: MetricSuggestion): MetricSuggestion {
  const newName = suggestion.conflict?.suggested_name?.trim();
  if (!newName) return suggestion;
  const definition: MetricDefinition = {
    ...suggestion.definition,
    metric: { ...suggestion.definition.metric, name: newName },
  };
  // The returned copy intentionally drops `conflict` — the clarify flow is resolved.
  return { definition, yaml_preview: renderMetricYaml(definition) };
}
