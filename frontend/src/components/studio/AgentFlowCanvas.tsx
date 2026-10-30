'use client';

import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from '@xyflow/react';
import { useEffect, useMemo, useRef, useState } from 'react';

import { useLanguage } from '@/context/LanguageContext';
import {
  buildAgentFlowGraph,
  collectVisibleAgentIds,
  getAgentDetails,
  getAgentStatus,
  NODE_HEIGHT,
  NODE_WIDTH,
  type AgentFlowEdge,
  type AgentFlowNode as AgentFlowNodeType,
  type AgentNodeData,
  type AgentStatus,
} from '@/lib/agentFlowGraph';
import type { ExecutionTrace } from '@/lib/chatTrace';
import { AgentFlowNode } from './AgentFlowNode';
import { StepStatus, TraceDuration } from './AgentThinking';

const nodeTypes = {
  agentNode: AgentFlowNode,
};

function mapStatusToStepStatus(status: AgentStatus): 'started' | 'finished' | 'failed' {
  if (status === 'running') return 'started';
  if (status === 'error') return 'failed';
  return 'finished';
}

function getStatusLabel(status: AgentStatus, t: (en: string, vi: string) => string): string {
  switch (status) {
    case 'running':
      return t('Running', 'Đang chạy');
    case 'completed':
      return t('Completed', 'Hoàn tất');
    case 'error':
      return t('Error', 'Có lỗi');
    case 'idle':
    default:
      return t('Idle', 'Chờ xử lý');
  }
}

interface AgentDetailsHeaderProps {
  displayName: string;
  statusText: string;
  status: AgentStatus;
  durationMs: number;
  running: boolean;
}

function AgentDetailsHeader({
  displayName,
  statusText,
  status,
  durationMs,
  running,
}: AgentDetailsHeaderProps) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="flex items-center gap-2 font-medium">
        <StepStatus status={mapStatusToStepStatus(status)} />
        <span>{displayName}</span>
        <span className="text-[11px] text-muted-foreground">({statusText})</span>
      </div>
      <div className="text-muted-foreground">
        <TraceDuration milliseconds={durationMs} running={running} />
      </div>
    </div>
  );
}

interface AgentDetailsPaneProps {
  trace: ExecutionTrace;
  details: AgentNodeData;
  reconnecting?: boolean;
}

function AgentDetailsPane({ trace, details, reconnecting }: AgentDetailsPaneProps) {
  const { language, t } = useLanguage();
  const displayName = language === 'en'
    ? (details.enName || details.name)
    : (details.name || details.enName);
  const statusText = getStatusLabel(details.status, t);
  const isRunning = details.status === 'running' && trace.status === 'running' && !reconnecting;
  const explanation =
    details.outcome_summary?.trim() ||
    details.summary?.trim() ||
    t('No explanation available', 'Chưa có giải thích');

  return (
    <div
      className="rounded-b-md border-x border-b border-border bg-card/40 p-3 text-xs"
      data-testid="agent-flow-details"
    >
      <AgentDetailsHeader
        displayName={displayName}
        statusText={statusText}
        status={details.status}
        durationMs={details.duration_ms ?? 0}
        running={isRunning}
      />
      <div className="mt-1.5 break-words text-muted-foreground [overflow-wrap:anywhere]" data-testid="agent-flow-explanation">
        {explanation}
      </div>
    </div>
  );
}

function useSelectedAgent(trace: ExecutionTrace, visibleIds: string[]) {
  const [prevRunId, setPrevRunId] = useState(trace.run_id);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  if (trace.run_id !== prevRunId) {
    setPrevRunId(trace.run_id);
    setSelectedId(null);
  }

  const effectiveId = useMemo(() => {
    if (visibleIds.length === 0) return null;
    if (selectedId && visibleIds.includes(selectedId)) {
      return selectedId;
    }
    const runningId = visibleIds.find((id) => getAgentStatus(trace, id) === 'running');
    return runningId ?? visibleIds[0];
  }, [trace, visibleIds, selectedId]);

  return { selectedId: effectiveId, setSelectedId };
}

function useFitViewOnRunChange(runId: string, visibleCount: number) {
  const { fitView } = useReactFlow();
  const prevRunIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (visibleCount > 0 && runId !== prevRunIdRef.current) {
      prevRunIdRef.current = runId;
      fitView({ padding: 0.15, duration: 300 });
    }
  }, [runId, visibleCount, fitView]);
}

function useAgentGraphNodes(
  trace: ExecutionTrace,
  selectedId: string | null,
  onSelect: (id: string) => void,
) {
  const built = useMemo(() => {
    const g = buildAgentFlowGraph(trace, selectedId ?? undefined);
    const nodes = g.nodes.map((node) => ({
      ...node,
      measured: { width: NODE_WIDTH, height: NODE_HEIGHT },
      data: { ...node.data, onSelect },
    }));
    return { nodes, edges: g.edges };
  }, [trace, selectedId, onSelect]);

  const [nodes, setNodes, onNodesChange] = useNodesState<AgentFlowNodeType>(built.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<AgentFlowEdge>(built.edges);

  useEffect(() => {
    setNodes(built.nodes);
    setEdges(built.edges);
  }, [built, setNodes, setEdges]);

  return { nodes, edges, onNodesChange, onEdgesChange };
}

function AgentFlowEmptyState() {
  const { t } = useLanguage();
  return (
    <div
      className="flex h-56 w-full items-center justify-center rounded-md border border-border bg-card/40 text-xs text-muted-foreground"
      data-testid="agent-flow-empty"
    >
      {t('No agent flow yet', 'Chưa có luồng agent')}
    </div>
  );
}

interface AgentFlowGraphViewportProps {
  nodes: AgentFlowNodeType[];
  edges: AgentFlowEdge[];
  onNodesChange: ReturnType<typeof useNodesState<AgentFlowNodeType>>[2];
  onEdgesChange: ReturnType<typeof useEdgesState<AgentFlowEdge>>[2];
  onNodeClick: (id: string) => void;
}

function AgentFlowGraphViewport({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onNodeClick,
}: AgentFlowGraphViewportProps) {
  return (
    <div className="relative h-56 w-full overflow-hidden rounded-t-md border border-border bg-card/40">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={(_, node) => onNodeClick(node.id)}
        nodeTypes={nodeTypes}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
        panOnDrag={true}
        zoomOnScroll={true}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
    </div>
  );
}

function AgentFlowInnerCanvas({ trace, reconnecting }: { trace: ExecutionTrace; reconnecting?: boolean }) {
  const visibleIds = useMemo(() => collectVisibleAgentIds(trace), [trace]);
  const { selectedId, setSelectedId } = useSelectedAgent(trace, visibleIds);
  useFitViewOnRunChange(trace.run_id, visibleIds.length);
  const { nodes, edges, onNodesChange, onEdgesChange } = useAgentGraphNodes(trace, selectedId, setSelectedId);

  const selectedDetails = useMemo(
    () => (selectedId ? getAgentDetails(trace, selectedId) : null),
    [trace, selectedId],
  );

  if (visibleIds.length === 0) return <AgentFlowEmptyState />;

  return (
    <div className="flex w-full flex-col" data-testid="agent-flow-canvas-container">
      <AgentFlowGraphViewport
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={setSelectedId}
      />
      {selectedDetails && (
        <AgentDetailsPane trace={trace} details={selectedDetails} reconnecting={reconnecting} />
      )}
    </div>
  );
}

/**
 * Embedded read-only Agent Flow canvas with compact inspection details.
 */
export function AgentFlowCanvas({ trace, reconnecting }: { trace: ExecutionTrace; reconnecting?: boolean }) {
  return (
    <ReactFlowProvider>
      <AgentFlowInnerCanvas trace={trace} reconnecting={reconnecting} />
    </ReactFlowProvider>
  );
}
