import YAML from 'yaml';
import {
  FilterOperator,
  MetricDefinition,
  MetricFilter,
  MetricQueryPlan,
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

/**
 * Render the metric formula. `conditions: false` drops WHERE/HAVING for views that show
 * filters next to it; views without a filter list must keep them (diff, dedupe, catalog).
 */
export function formatMetricFormula(definition: MetricDefinition, { conditions = true } = {}): string {
  if (definition.metric.query_plan) return formatPlanOutput(definition.metric.query_plan, conditions);
  const formula = definition.metric.formula;
  if (!formula.ratio) {
    const prefix = formula.expression.includes('/') ? 'Cần xem xét · ' : '';
    return `${prefix}${formatAggregateCall(formula.function, formula.expression)}`;
  }

  const numerator = formatAggregate(formula.ratio.numerator, conditions);
  const denominator = formatAggregate(formula.ratio.denominator, conditions);
  const scale = formula.ratio.scale ?? 1;
  const offset = formula.ratio.offset ?? 0;
  // Parentheses only when a WHERE clause would otherwise run into the operator.
  const wrap = (text: string) => (text.includes(' WHERE ') ? `(${text})` : text);
  const ratio = `${wrap(numerator)} / ${wrap(denominator)}`;
  const scaled = scale === 1 ? ratio : `${scale} × ${ratio}`;
  return offset ? `${offset} + ${scaled}` : scaled;
}

/** Render an aggregate call as SQL, e.g. COUNT_DISTINCT(x) -> COUNT(DISTINCT x). */
export function formatAggregateCall(fn: string, expression: string): string {
  return fn === 'COUNT_DISTINCT' ? `COUNT(DISTINCT ${expression})` : `${fn}(${expression})`;
}

type PlanStage = MetricQueryPlan['stages'][number];
type PlanAggregate = PlanStage['aggregates'][number];

type PlanStages = Map<string, PlanStage>;

/** Collapse the plan into one expression by inlining every `stage.aggregate` ref. */
function formatPlanOutput(plan: MetricQueryPlan, conditions: boolean): string {
  const stages: PlanStages = new Map(plan.stages.map((stage) => [stage.name, stage]));
  return plan.output_expression.replace(/(?<![\w$.])[A-Za-z_][\w$]*\.[A-Za-z_][\w$]*(?![\w$.])/g, (ref) => {
    const [stageName, aggregateName] = ref.split('.');
    const stage = stages.get(stageName);
    const aggregate = stage?.aggregates.find((item) => item.name === aggregateName);
    return stage && aggregate ? formatPlanAggregate(stages, stage, aggregate, 0, conditions) : ref;
  });
}

/**
 * Render one plan aggregate inline. Over a source stage, `*` becomes that stage's
 * group keys and fields naming its aggregates are inlined, so filters read as HAVING.
 */
function formatPlanAggregate(
  stages: PlanStages, stage: PlanStage, aggregate: PlanAggregate, depth: number, conditions = true,
): string {
  const source = stage.source_stage ? stages.get(stage.source_stage) : undefined;
  const resolve = (field: string) => resolveSourceField(stages, source, field, depth, conditions);
  const keys = source?.group_by.map((field) => field.name).join(', ');
  const expression = source && aggregate.expression === '*' ? keys || '*' : resolve(aggregate.expression);
  const filters = (conditions ? [...(stage.filters || []), ...(aggregate.filters || [])] : [])
    .map((filter) => formatMetricFilter({ ...filter, field: resolve(filter.field) }));
  const clause = filters.length ? ` ${source ? 'HAVING' : 'WHERE'} ${filters.join(' VÀ ')}` : '';
  return formatAggregateCall(aggregate.function, `${expression}${clause}`);
}

function resolveSourceField(
  stages: PlanStages, source: PlanStage | undefined, field: string, depth: number, conditions = true,
): string {
  const aggregate = source?.aggregates.find((item) => item.name === field);
  // Depth guard: the backend rejects cyclic plans, but never recurse unboundedly on bad data.
  if (!source || !aggregate || depth > 5) return field;
  return formatPlanAggregate(stages, source, aggregate, depth + 1, conditions);
}

const filterOperators: Record<FilterOperator, string> = {
  eq: '=', neq: '≠', gt: '>', gte: '≥', lt: '<', lte: '≤',
  in: 'thuộc', not_in: 'không thuộc', is_null: 'là NULL', is_not_null: 'khác NULL',
};

function formatMetricFilter(filter: MetricFilter): string {
  const operator = filterOperators[filter.operator] ?? filter.operator;
  if (filter.operator === 'is_null' || filter.operator === 'is_not_null') return `${filter.field} ${operator}`;
  const value = Array.isArray(filter.value)
    ? `[${filter.value.map((item) => JSON.stringify(item)).join(', ')}]`
    : JSON.stringify(filter.value) ?? 'null';
  return `${filter.field} ${operator} ${value}`;
}

/** Filters grouped by business role (shared / numerator / denominator), never by internal stage names. */
export function formatMetricFilters(definition: MetricDefinition): string[] {
  const { filters, formula, query_plan: plan } = definition.metric;
  const isRatio = Boolean(formula.ratio) || (plan ? topLevelSlash(plan.output_expression) >= 0 : false);
  const shared = isRatio ? 'Chung (cả tử và mẫu)' : 'Chung';
  const groups = new Map<string, string[]>([[shared, (filters || []).map(formatMetricFilter)]]);
  const add = (scope: string, items: string[]) => groups.set(scope, [...(groups.get(scope) || []), ...items]);
  add('Tử số', (formula.ratio?.numerator.filters || []).map(formatMetricFilter));
  add('Mẫu số', (formula.ratio?.denominator.filters || []).map(formatMetricFilter));
  if (plan) for (const [roles, text] of planFilterEntries(plan)) add(roleLabel(roles, shared), [text]);
  return [...groups].filter(([, items]) => items.length).map(([scope, items]) => `${scope}: ${items.join(' VÀ ')}`);
}

type Role = 'num' | 'den';

function roleLabel(roles: Set<Role>, shared: string): string {
  if (roles.size !== 1) return shared;
  return roles.has('num') ? 'Tử số' : 'Mẫu số';
}

/** Index of the first `/` outside parentheses, or -1. */
function topLevelSlash(expression: string): number {
  let depth = 0;
  for (let index = 0; index < expression.length; index++) {
    const char = expression[index];
    if (char === '(') depth++;
    else if (char === ')') depth--;
    else if (char === '/' && depth === 0) return index;
  }
  return -1;
}

/** Each plan filter with its roles and a readable text (prior-stage outputs inlined). */
function planFilterEntries(plan: MetricQueryPlan): [Set<Role>, string][] {
  const stages: PlanStages = new Map(plan.stages.map((stage) => [stage.name, stage]));
  const refRoles = planRefRoles(plan.output_expression);
  const stageRoles = planStageRoles(plan, refRoles);
  return plan.stages.flatMap((stage) => {
    const source = stage.source_stage ? stages.get(stage.source_stage) : undefined;
    const text = (filter: MetricFilter) =>
      formatMetricFilter({ ...filter, field: resolveSourceField(stages, source, filter.field, 0) });
    const own = stageRoles.get(stage.name) || new Set<Role>();
    return [
      ...(stage.filters || []).map((filter): [Set<Role>, string] => [own, text(filter)]),
      ...stage.aggregates.flatMap((aggregate) => (aggregate.filters || [])
        .map((filter): [Set<Role>, string] => [refRoles.get(`${stage.name}.${aggregate.name}`) || own, text(filter)])),
    ];
  });
}

/** Role of each `stage.aggregate` ref: left of the top-level `/` is numerator, right is denominator. */
function planRefRoles(output: string): Map<string, Set<Role>> {
  const slash = topLevelSlash(output);
  const roles = new Map<string, Set<Role>>();
  if (slash < 0) return roles;
  for (const match of output.matchAll(/(?<![\w$.])[A-Za-z_][\w$]*\.[A-Za-z_][\w$]*(?![\w$.])/g)) {
    const set = roles.get(match[0]) || new Set<Role>();
    set.add((match.index ?? 0) < slash ? 'num' : 'den');
    roles.set(match[0], set);
  }
  return roles;
}

/** Stage roles from its refs, then pushed down to the source stages that feed it. */
function planStageRoles(plan: MetricQueryPlan, refRoles: Map<string, Set<Role>>): Map<string, Set<Role>> {
  const roles = new Map(plan.stages.map((stage) => [stage.name, new Set<Role>()]));
  for (const [ref, refSet] of refRoles) refSet.forEach((role) => roles.get(ref.split('.')[0])?.add(role));
  for (let pass = 0; pass < plan.stages.length; pass++) {
    for (const stage of plan.stages) {
      if (stage.source_stage) roles.get(stage.name)?.forEach((role) => roles.get(stage.source_stage!)?.add(role));
    }
  }
  return roles;
}

export function getMetricUsedColumns(definition: MetricDefinition): string[] {
  const { formula, filters } = definition.metric;
  const plan = definition.metric.query_plan;
  const expressions = plan
    ? plan.stages.flatMap((stage) => [
        ...stage.group_by.map((field) => field.expression),
        ...stage.aggregates.map((aggregate) => aggregate.expression),
      ])
    : formula.ratio
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
      if (!isQuotedIdentifier && expression[tokens.lastIndex] === '.') continue;
      if (!isQuotedIdentifier && /^(true|false|null)$/i.test(name)) continue;
      if (/^\s*\(/.test(expression.slice(tokens.lastIndex))) continue;
      names.set(name.toLowerCase(), names.get(name.toLowerCase()) || name);
    }
  }

  const ratio = formula.ratio;
  // Filters over a source stage name its outputs (e.g. order_count), not table columns.
  const planFilters = plan?.stages.filter((stage) => !stage.source_stage).flatMap((stage) => [
    ...stage.filters,
    ...stage.aggregates.flatMap((aggregate) => aggregate.filters),
  ]) || [];
  const allFilters = [
    ...filters,
    ...planFilters,
    ...(ratio?.numerator.filters || []),
    ...(ratio?.denominator.filters || []),
  ];
  for (const filter of allFilters) {
    const key = filter.field.toLowerCase();
    names.set(key, names.get(key) || filter.field);
  }

  return [...names.values()];
}

function formatAggregate(
  aggregate: NonNullable<MetricDefinition['metric']['formula']['ratio']>['numerator'], conditions: boolean,
): string {
  const filters = conditions ? aggregate.filters?.map(formatMetricFilter).sort() : [];
  const filterText = filters?.length ? ` WHERE ${filters.join(' AND ')}` : '';
  return `${formatAggregateCall(aggregate.function, aggregate.expression)}${filterText}`;
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
