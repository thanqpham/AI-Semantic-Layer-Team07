'use client';

import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useNodesState,
  useReactFlow,
  type EdgeMouseHandler,
  type NodeMouseHandler,
} from '@xyflow/react';
import { Network } from 'lucide-react';
import { useEffect, useMemo, useState, type ReactNode } from 'react';

import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';
import {
  applyFocus,
  buildGraph,
  layoutGraph,
  nodeStatus,
  STATUS_STYLE,
  type RelEdge,
  type TableNode as TableNodeType,
} from '@/lib/relationshipGraph';
import type { RelationshipEntity, RelationshipItem } from '@/lib/relationshipReviewApi';
import { DiagramLegend } from './DiagramLegend';
import { DiagramActionsContext, RelationshipEdge } from './RelationshipEdge';
import { TableNode } from './TableNode';

const nodeTypes = { table: TableNode };
const edgeTypes = { relationship: RelationshipEdge };

interface Props {
  entities: RelationshipEntity[];
  items: RelationshipItem[];
  selectedKey: string | null;
  loading?: boolean;
  emptyAction?: ReactNode;
  onSelectEdge: (item: RelationshipItem, trigger: HTMLElement | null) => void;
}

/** Interactive ERD of tables and their relationships; clicking an edge selects that relationship. */
export function RelationshipDiagram(props: Props) {
  const { onSelectEdge } = props;
  const actions = useMemo(() => ({ onSelect: onSelectEdge }), [onSelectEdge]);
  return (
    <ReactFlowProvider>
      <DiagramActionsContext.Provider value={actions}>
        <DiagramCanvas {...props} />
      </DiagramActionsContext.Provider>
    </ReactFlowProvider>
  );
}

function useLayout(entities: RelationshipEntity[], items: RelationshipItem[]) {
  const graph = useMemo(() => {
    const built = buildGraph(entities, items);
    return { nodes: layoutGraph(built.nodes, built.edges), edges: built.edges };
  }, [entities, items]);
  const [nodes, setNodes, onNodesChange] = useNodesState<TableNodeType>(graph.nodes);
  const { fitView } = useReactFlow();
  useEffect(() => {
    setNodes(graph.nodes);
    const frame = requestAnimationFrame(() => void fitView({ padding: 0.15, duration: 300 }));
    return () => cancelAnimationFrame(frame);
  }, [graph, setNodes, fitView]);
  return { nodes, edges: graph.edges, onNodesChange };
}

function minimapColor(edges: RelEdge[]) {
  return (node: { id: string }) => {
    const status = nodeStatus(node.id, edges);
    return status ? STATUS_STYLE[status].stroke : '#a1a1aa';
  };
}

function DiagramCanvas({ entities, items, selectedKey, loading, emptyAction, onSelectEdge }: Props) {
  const { nodes, edges, onNodesChange } = useLayout(entities, items);
  const [hover, setHover] = useState<string | null>(null);
  const view = useMemo(() => applyFocus(nodes, edges, { node: hover, edge: selectedKey }), [nodes, edges, hover, selectedKey]);
  const onEdgeClick: EdgeMouseHandler<RelEdge> = (_, edge) => { if (edge.data) onSelectEdge(edge.data.item, null); };
  const onEnter: NodeMouseHandler<TableNodeType> = (_, node) => setHover(node.id);
  return (
    <div className="relationship-diagram relative flex-1 h-[calc(100dvh-240px)] min-h-[360px] lg:h-full lg:min-h-0 w-full min-w-0 overflow-hidden rounded-xl border border-border bg-background">
      <ReactFlow
        nodes={view.nodes}
        edges={view.edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgeClick={onEdgeClick}
        onNodeMouseEnter={onEnter}
        onNodeMouseLeave={() => setHover(null)}
        nodesConnectable={false}
        minZoom={0.15}
        maxZoom={1.75}
        fitView
        attributionPosition="top-right"
      >
        <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} />
        <Panel position="top-left"><DiagramLegend /></Panel>
        <DiagramStats tables={nodes.length} links={edges.length} />
        <Controls showInteractive={false} position="bottom-left" />
        <MiniMap pannable zoomable position="bottom-right" nodeColor={minimapColor(edges)} nodeStrokeWidth={0} maskColor="color-mix(in oklch, var(--background) 70%, transparent)" />
      </ReactFlow>
      {!loading && !items.length && <EmptyOverlay action={emptyAction} />}
    </div>
  );
}

function DiagramStats({ tables, links }: { tables: number; links: number }) {
  const { translate: t } = useLanguage();
  return (
    <Panel position="bottom-center">
      <span className="rounded-full border border-border bg-card/90 px-3 py-1 font-mono text-[10px] text-muted-foreground shadow-sm backdrop-blur">
        {tables} {t('bảng')} · {links} {t('liên kết')}
      </span>
    </Panel>
  );
}

function EmptyOverlay({ action }: { action?: ReactNode }) {
  return (
    <div className="pointer-events-none absolute inset-x-0 top-1/3 flex justify-center px-4">
      <div className="pointer-events-auto flex max-w-sm flex-col items-center gap-3 rounded-2xl border border-dashed border-border bg-card/95 p-6 text-center shadow-lg backdrop-blur">
        <span className="flex h-11 w-11 items-center justify-center rounded-full bg-muted"><Network className="h-5 w-5 text-muted-foreground" /></span>
        <p className="text-sm font-medium"><Translated text="Chưa có liên kết." /></p>
        <p className="text-xs text-muted-foreground"><Translated text="Dùng AI đề xuất hoặc thêm thủ công để nối các bảng với nhau." /></p>
        {action}
      </div>
    </div>
  );
}
