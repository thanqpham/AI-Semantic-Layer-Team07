import dagre from '@dagrejs/dagre';
import { MarkerType, type Edge, type Node } from '@xyflow/react';
import {
  qualifiedEntity,
  type ColumnPair,
  type RelationshipEntity,
  type RelationshipItem,
  type RelationshipType,
} from './relationshipReviewApi';

export type GraphStatus = 'pending_review' | 'approved' | 'needs_review' | 'rejected' | 'disabled';

export interface StatusStyle {
  stroke: string;
  dash?: string;
  animated: boolean;
  faded: boolean;
  label: string;
  tone: string;
}

/** Visual language per relationship status (stroke color, dash pattern, animation). */
export const STATUS_STYLE: Record<GraphStatus, StatusStyle> = {
  pending_review: { stroke: '#f59e0b', dash: '6 4', animated: true, faded: false, label: 'Chờ review', tone: 'amber' },
  approved: { stroke: '#10b981', animated: false, faded: false, label: 'Đã duyệt', tone: 'emerald' },
  needs_review: { stroke: '#f97316', dash: '6 4', animated: false, faded: false, label: 'Cần review lại', tone: 'orange' },
  rejected: { stroke: '#ef4444', dash: '2 4', animated: false, faded: true, label: 'Từ chối', tone: 'red' },
  disabled: { stroke: '#a1a1aa', dash: '6 4', animated: false, faded: true, label: 'Vô hiệu', tone: 'zinc' },
};

export const STATUS_ORDER: GraphStatus[] = ['pending_review', 'needs_review', 'approved', 'rejected', 'disabled'];

export const CARDINALITY: Record<RelationshipType, string> = {
  many_to_one: 'N : 1',
  one_to_one: '1 : 1',
  one_to_many: '1 : N',
  many_to_many: 'N : M',
};

export const NODE_WIDTH = 264;
export const MAX_VISIBLE_COLUMNS = 8;
const HEADER_HEIGHT = 48;
const ROW_HEIGHT = 28;
const FOOTER_HEIGHT = 30;

export interface GraphColumn {
  id: number;
  name: string;
  type: string;
  pk: boolean;
  fk: boolean;
  linked: boolean;
}

export type TableNodeData = {
  label: string;
  columns: GraphColumn[];
  dimmed: boolean;
  highlight: number[];
};

export type RelEdgeData = {
  item: RelationshipItem;
  pairCount: number;
  dimmed: boolean;
  selected: boolean;
};

export type TableNode = Node<TableNodeData, 'table'>;
export type RelEdge = Edge<RelEdgeData, 'relationship'>;

export interface Focus {
  node?: string | null;
  edge?: string | null;
}

/** Resolve a status string into its style, defaulting unknown statuses to pending. */
export function statusStyle(status: string): StatusStyle {
  return STATUS_STYLE[status as GraphStatus] ?? STATUS_STYLE.pending_review;
}

/** Stable key shared by list rows, diagram edges and selection state. */
export const relationshipKey = (item: { kind: string; id: number }) => `${item.kind}:${item.id}`;

export const nodeId = (entityId: number) => `t-${entityId}`;

function isPair(value: unknown): value is ColumnPair {
  if (!value || typeof value !== 'object') return false;
  const pair = value as ColumnPair;
  return Number.isInteger(pair.from_column_id) && Number.isInteger(pair.to_column_id)
    && pair.from_column_id > 0 && pair.to_column_id > 0;
}

/** Safely read the untyped column_pairs payload; malformed entries are dropped. */
export function readPairs(item: RelationshipItem): ColumnPair[] {
  return Array.isArray(item.column_pairs) ? item.column_pairs.filter(isPair) : [];
}

/** Column ids acting as foreign keys (source side) and all columns joined by any relationship. */
export function columnRoles(items: RelationshipItem[]): { fk: Set<number>; linked: Set<number> } {
  const fk = new Set<number>();
  const linked = new Set<number>();
  for (const pair of items.flatMap(readPairs)) {
    fk.add(pair.from_column_id);
    linked.add(pair.from_column_id);
    linked.add(pair.to_column_id);
  }
  return { fk, linked };
}

/** Merge schema entities with entities embedded in relationships so no edge is orphaned. */
export function collectEntities(entities: RelationshipEntity[], items: RelationshipItem[]): RelationshipEntity[] {
  const map = new Map(entities.map((entity) => [entity.id, entity]));
  for (const item of items) {
    for (const entity of [item.from_entity, item.to_entity]) {
      if (!map.has(entity.id)) map.set(entity.id, entity);
    }
  }
  return [...map.values()];
}

/** Columns rendered when a table is collapsed: keys and joined columns first, capped otherwise. */
export function visibleColumns(columns: GraphColumn[], expanded = false): GraphColumn[] {
  if (expanded || columns.length <= MAX_VISIBLE_COLUMNS) return columns;
  const keep = columns.filter((column) => column.pk || column.linked);
  const room = Math.max(0, MAX_VISIBLE_COLUMNS - keep.length);
  const rest = columns.filter((column) => !column.pk && !column.linked).slice(0, room);
  const ids = new Set([...keep, ...rest].map((column) => column.id));
  return columns.filter((column) => ids.has(column.id));
}

/** Estimated collapsed node height used by the layout engine. */
export function nodeHeight(data: TableNodeData): number {
  const visible = visibleColumns(data.columns).length;
  const footer = data.columns.length > visible ? FOOTER_HEIGHT : 0;
  return HEADER_HEIGHT + Math.max(visible, 1) * ROW_HEIGHT + footer + 8;
}

function toNode(entity: RelationshipEntity, roles: ReturnType<typeof columnRoles>): TableNode {
  const columns = entity.columns.map((column) => ({
    id: column.id,
    name: column.name,
    type: column.type,
    pk: !!column.is_primary_key,
    fk: roles.fk.has(column.id),
    linked: roles.linked.has(column.id),
  }));
  const data: TableNodeData = { label: qualifiedEntity(entity), columns, dimmed: false, highlight: [] };
  return { id: nodeId(entity.id), type: 'table', position: { x: 0, y: 0 }, data };
}

function toEdge(item: RelationshipItem, known: Set<number>): RelEdge {
  const pairs = readPairs(item);
  const pair = pairs.find((p) => known.has(p.from_column_id) && known.has(p.to_column_id));
  return {
    id: relationshipKey(item),
    type: 'relationship',
    source: nodeId(item.from_entity.id),
    target: nodeId(item.to_entity.id),
    sourceHandle: pair ? `col-${pair.from_column_id}-src` : 'tbl-src',
    targetHandle: pair ? `col-${pair.to_column_id}-tgt` : 'tbl-tgt',
    markerEnd: { type: MarkerType.ArrowClosed, color: statusStyle(item.status).stroke, width: 18, height: 18 },
    data: { item, pairCount: pairs.length, dimmed: false, selected: false },
  };
}

/** Build table nodes and relationship edges anchored on the first valid column pair. */
export function buildGraph(entities: RelationshipEntity[], items: RelationshipItem[]): { nodes: TableNode[]; edges: RelEdge[] } {
  const roles = columnRoles(items);
  const nodes = collectEntities(entities, items).map((entity) => toNode(entity, roles));
  const known = new Set(nodes.flatMap((node) => node.data.columns.map((column) => column.id)));
  return { nodes, edges: items.map((item) => toEdge(item, known)) };
}

export type LayoutMode = 'balanced' | 'hierarchical' | 'grid';
const MAX_PER_COL = 4;
const COL_WIDTH = NODE_WIDTH + 64;
const GAP_Y = 28;

function initDagreGraph(nodes: TableNode[], edges: RelEdge[]) {
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({ rankdir: 'LR', nodesep: 48, ranksep: 140, marginx: 24, marginy: 24 });
  graph.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((node) => graph.setNode(node.id, { width: NODE_WIDTH, height: nodeHeight(node.data) }));
  edges.forEach((edge) => { if (edge.source !== edge.target) graph.setEdge(edge.source, edge.target); });
  dagre.layout(graph);
  return graph;
}

function dagreLayout(nodes: TableNode[], edges: RelEdge[]): Map<string, { x: number; y: number }> {
  const graph = initDagreGraph(nodes, edges);
  const positions = new Map<string, { x: number; y: number }>();
  for (const node of nodes) {
    const point = graph.node(node.id);
    positions.set(node.id, { x: point.x - NODE_WIDTH / 2, y: point.y - nodeHeight(node.data) / 2 });
  }
  return positions;
}

function groupDagreRanks(nodes: TableNode[], graph: dagre.graphlib.Graph): TableNode[][] {
  const buckets = new Map<number, TableNode[]>();
  for (const node of nodes) {
    const rx = Math.round(graph.node(node.id).x / 50) * 50;
    if (!buckets.has(rx)) buckets.set(rx, []);
    buckets.get(rx)!.push(node);
  }
  return [...buckets.keys()].sort((a, b) => a - b).map((rx) => {
    const list = buckets.get(rx)!;
    return list.sort((a, b) => graph.node(a.id).y - graph.node(b.id).y);
  });
}

function layoutRankColumns(nodes: TableNode[], startX: number, positions: Map<string, { x: number; y: number }>): number {
  const cols = Math.ceil(nodes.length / MAX_PER_COL);
  for (let c = 0; c < cols; c++) {
    const colNodes = nodes.slice(c * MAX_PER_COL, (c + 1) * MAX_PER_COL);
    let y = 32;
    for (const node of colNodes) {
      positions.set(node.id, { x: startX + c * COL_WIDTH, y });
      y += nodeHeight(node.data) + GAP_Y;
    }
  }
  return startX + cols * COL_WIDTH + 80;
}

function balancedLayout(nodes: TableNode[], edges: RelEdge[]): Map<string, { x: number; y: number }> {
  const graph = initDagreGraph(nodes, edges);
  const ranks = groupDagreRanks(nodes, graph);
  const positions = new Map<string, { x: number; y: number }>();
  let x = 32;
  for (const rankNodes of ranks) {
    x = layoutRankColumns(rankNodes, x, positions);
  }
  return positions;
}

function gridLayout(nodes: TableNode[], top = 24, perRow = 5): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  let y = top;
  for (let start = 0; start < nodes.length; start += perRow) {
    const row = nodes.slice(start, start + perRow);
    row.forEach((node, index) => positions.set(node.id, { x: 24 + index * COL_WIDTH, y }));
    y += Math.max(...row.map((node) => nodeHeight(node.data))) + GAP_Y;
  }
  return positions;
}

/** Lay out tables according to mode (balanced multi-column, hierarchical LR, or uniform grid). */
export function layoutGraph(nodes: TableNode[], edges: RelEdge[], mode: LayoutMode = 'balanced'): TableNode[] {
  if (mode === 'grid') {
    const positions = gridLayout(nodes);
    return nodes.map((n) => ({ ...n, position: positions.get(n.id) ?? n.position }));
  }
  const connectedIds = new Set(edges.flatMap((edge) => [edge.source, edge.target]));
  const connected = nodes.filter((node) => connectedIds.has(node.id));
  const isolated = nodes.filter((node) => !connectedIds.has(node.id));
  const positions = connected.length
    ? (mode === 'hierarchical' ? dagreLayout(connected, edges) : balancedLayout(connected, edges))
    : new Map<string, { x: number; y: number }>();
  const bottom = connected.reduce((max, node) => {
    const point = positions.get(node.id);
    return point ? Math.max(max, point.y + nodeHeight(node.data)) : max;
  }, 0);
  gridLayout(isolated, connected.length ? bottom + 80 : 24, 5).forEach((point, id) => positions.set(id, point));
  return nodes.map((node) => ({ ...node, position: positions.get(node.id) ?? node.position }));
}

/** Nodes and edges that stay bright for a hovered node or a selected edge; null means no focus. */
export function focusSet(edges: RelEdge[], focus: Focus): { nodes: Set<string>; edges: Set<string> } | null {
  if (focus.node) {
    const hit = edges.filter((edge) => edge.source === focus.node || edge.target === focus.node);
    return {
      nodes: new Set([focus.node, ...hit.flatMap((edge) => [edge.source, edge.target])]),
      edges: new Set(hit.map((edge) => edge.id)),
    };
  }
  const edge = focus.edge ? edges.find((candidate) => candidate.id === focus.edge) : undefined;
  return edge ? { nodes: new Set([edge.source, edge.target]), edges: new Set([edge.id]) } : null;
}

/** Decorate nodes/edges with dim + highlight flags for the current focus. */
export function applyFocus(nodes: TableNode[], edges: RelEdge[], focus: Focus): { nodes: TableNode[]; edges: RelEdge[] } {
  const active = focusSet(edges, focus);
  const selectedEdge = edges.find((edge) => edge.id === focus.edge);
  const highlight = selectedEdge?.data ? readPairs(selectedEdge.data.item).flatMap((p) => [p.from_column_id, p.to_column_id]) : [];
  return {
    nodes: nodes.map((node) => ({
      ...node,
      data: { ...node.data, dimmed: !!active && !active.nodes.has(node.id), highlight },
    })),
    edges: edges.map((edge) => ({
      ...edge,
      zIndex: active?.edges.has(edge.id) ? 10 : 0,
      data: edge.data && { ...edge.data, dimmed: !!active && !active.edges.has(edge.id), selected: edge.id === focus.edge },
    })),
  };
}

/** Most urgent status among a table's relationships (used to tint the minimap). */
export function nodeStatus(nodeKey: string, edges: RelEdge[]): GraphStatus | null {
  const statuses = edges
    .filter((edge) => edge.source === nodeKey || edge.target === nodeKey)
    .map((edge) => edge.data?.item.status as GraphStatus);
  return STATUS_ORDER.find((status) => statuses.includes(status)) ?? null;
}
