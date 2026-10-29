import { describe, expect, it } from 'vitest';
import {
  applyFocus,
  buildGraph,
  columnRoles,
  focusSet,
  layoutGraph,
  nodeStatus,
  readPairs,
  relationshipKey,
  statusStyle,
  visibleColumns,
  type GraphColumn,
} from './relationshipGraph';
import type { RelationshipEntity, RelationshipItem } from './relationshipReviewApi';

const entities: RelationshipEntity[] = [
  {
    id: 1,
    schema: 'sales',
    name: 'orders',
    columns: [
      { id: 10, name: 'id', type: 'int', is_primary_key: true },
      { id: 11, name: 'customer_id', type: 'int' },
      { id: 12, name: 'status', type: 'varchar' },
    ],
  },
  {
    id: 2,
    schema: 'sales',
    name: 'customers',
    columns: [
      { id: 20, name: 'id', type: 'int', is_primary_key: true },
      { id: 21, name: 'name', type: 'varchar' },
    ],
  },
  {
    id: 3,
    schema: 'inventory',
    name: 'warehouses',
    columns: [{ id: 30, name: 'id', type: 'int', is_primary_key: true }],
  },
];

const item: RelationshipItem = {
  kind: 'candidate',
  id: 101,
  revision: 1,
  from_entity: entities[0],
  to_entity: entities[1],
  column_pairs: [{ from_column_id: 11, to_column_id: 20 }],
  relationship_type: 'many_to_one',
  source: 'ai',
  status: 'pending_review',
  evidence: {},
  on_preview: 'orders.customer_id = customers.id',
  errors: [],
  warnings: [],
  unresolved_questions: [],
};

describe('relationshipGraph', () => {
  it('identifies foreign keys and linked column roles', () => {
    const roles = columnRoles([item]);
    expect(roles.fk.has(11)).toBe(true);
    expect(roles.fk.has(20)).toBe(false);
    expect(roles.linked.has(11)).toBe(true);
    expect(roles.linked.has(20)).toBe(true);
  });

  it('safely extracts column pairs and filters malformed objects', () => {
    const valid = readPairs(item);
    expect(valid).toEqual([{ from_column_id: 11, to_column_id: 20 }]);

    const badItem = { ...item, column_pairs: ['bad', { from_column_id: 0, to_column_id: 20 }, null] };
    expect(readPairs(badItem)).toEqual([]);
  });

  it('builds nodes and edges anchored on matching columns', () => {
    const { nodes, edges } = buildGraph(entities, [item]);
    expect(nodes).toHaveLength(3);
    expect(edges).toHaveLength(1);

    const edge = edges[0];
    expect(edge.id).toBe('candidate:101');
    expect(edge.source).toBe('t-1');
    expect(edge.target).toBe('t-2');
    expect(edge.sourceHandle).toBe('col-11-src');
    expect(edge.targetHandle).toBe('col-20-tgt');
  });

  it('lays out connected nodes with dagre and positions isolated nodes below', () => {
    const { nodes, edges } = buildGraph(entities, [item]);
    const laidOut = layoutGraph(nodes, edges);
    expect(laidOut).toHaveLength(3);

    const orders = laidOut.find((n) => n.id === 't-1')!;
    const customers = laidOut.find((n) => n.id === 't-2')!;
    const warehouse = laidOut.find((n) => n.id === 't-3')!;

    expect(Number.isFinite(orders.position.x)).toBe(true);
    expect(Number.isFinite(customers.position.x)).toBe(true);
    expect(Number.isFinite(warehouse.position.y)).toBe(true);
    // connected nodes are ranked left-to-right
    expect(customers.position.x).toBeGreaterThan(orders.position.x);
  });

  it('supports hierarchical and grid layout modes', () => {
    const { nodes, edges } = buildGraph(entities, [item]);
    const hierarchical = layoutGraph(nodes, edges, 'hierarchical');
    expect(hierarchical).toHaveLength(3);
    expect(hierarchical[1].position.x).toBeGreaterThan(hierarchical[0].position.x);

    const grid = layoutGraph(nodes, edges, 'grid');
    expect(grid).toHaveLength(3);
    // Grid mode places nodes in uniform horizontal row (x coordinates increase by COL_WIDTH)
    expect(grid[1].position.x).toBeGreaterThan(grid[0].position.x);
  });

  it('computes focus set and applies dimming to unrelated elements', () => {
    const { nodes, edges } = buildGraph(entities, [item]);
    const focused = focusSet(edges, { node: 't-1' });
    expect(focused).not.toBeNull();
    expect(focused!.nodes.has('t-1')).toBe(true);
    expect(focused!.nodes.has('t-2')).toBe(true);
    expect(focused!.nodes.has('t-3')).toBe(false);

    const applied = applyFocus(nodes, edges, { node: 't-1' });
    const warehouseNode = applied.nodes.find((n) => n.id === 't-3')!;
    expect(warehouseNode.data.dimmed).toBe(true);
    const orderNode = applied.nodes.find((n) => n.id === 't-1')!;
    expect(orderNode.data.dimmed).toBe(false);
  });

  it('resolves node status from the highest priority adjacent edge', () => {
    const { edges } = buildGraph(entities, [item]);
    expect(nodeStatus('t-1', edges)).toBe('pending_review');
    expect(nodeStatus('t-3', edges)).toBeNull();
  });

  it('preserves PKs and linked columns when truncating visible columns', () => {
    const cols: GraphColumn[] = Array.from({ length: 15 }, (_, i) => ({
      id: i + 1,
      name: `c_${i + 1}`,
      type: 'text',
      pk: i === 0,
      fk: i === 12,
      linked: i === 12,
    }));
    const visible = visibleColumns(cols, false);
    expect(visible.length).toBeLessThanOrEqual(8);
    expect(visible.some((c) => c.pk)).toBe(true);
    expect(visible.some((c) => c.linked)).toBe(true);
  });

  it('generates consistent status styles and relationship keys', () => {
    expect(statusStyle('approved').stroke).toBe('#10b981');
    expect(statusStyle('pending_review').animated).toBe(true);
    expect(relationshipKey(item)).toBe('candidate:101');
  });
});
