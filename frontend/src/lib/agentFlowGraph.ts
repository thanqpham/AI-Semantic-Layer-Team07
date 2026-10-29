import dagre from '@dagrejs/dagre';
import { MarkerType, type Edge, type Node } from '@xyflow/react';
import { agentId, traceSteps, type ExecutionTrace, type TraceEvent } from '@/lib/chatTrace';

export type AgentStatus = 'running' | 'completed' | 'error' | 'idle';

export type AgentNodeData = {
  id: string;
  name: string;
  enName: string;
  status: AgentStatus;
  duration_ms?: number;
  outcome_summary?: string;
  summary?: string;
  selected?: boolean;
  onSelect?: (id: string) => void;
};

export type AgentFlowNode = Node<AgentNodeData, 'agentNode'>;
export type AgentFlowEdge = Edge;

export const NODE_WIDTH = 180;
export const NODE_HEIGHT = 56;

export interface KnownAgentDef {
  id: string;
  name: string;
  enName: string;
}

export const KNOWN_AGENTS: Record<string, KnownAgentDef> = {
  orchestrator: { id: 'orchestrator', name: 'Orchestrator Agent', enName: 'Orchestrator Agent' },
  chitchat: { id: 'chitchat', name: 'Conversation Agent', enName: 'Conversation Agent' },
  data_assistant: { id: 'data_assistant', name: 'Data Assistant Agent', enName: 'Data Assistant Agent' },
  metric_suggest: { id: 'metric_suggest', name: 'Metric Designer Agent', enName: 'Metric Designer Agent' },
  metric_review: { id: 'metric_review', name: 'Metric Reviewer Agent', enName: 'Metric Reviewer Agent' },
  semantic_parse: { id: 'semantic_parse', name: 'Semantic Query Parser Agent', enName: 'Semantic Query Parser Agent' },
};

/** Collect all visible agent IDs that appear in steps or transitions, preserving order of appearance. */
export function collectVisibleAgentIds(trace: ExecutionTrace): string[] {
  const visible = new Set<string>();
  for (const event of trace.events) {
    if (event.kind === 'step') {
      const id = agentId(event.node);
      if (id) visible.add(id);
    } else if (event.kind === 'transition') {
      const src = agentId(event.source);
      if (src) visible.add(src);
      const tgt = agentId(event.target);
      if (tgt) visible.add(tgt);
    }
  }
  return [...visible];
}

/** Collect bridged edges between visible agents across continuous transition paths. */
export function collectBridgedEdges(
  trace: ExecutionTrace,
  visibleIds: Set<string>,
): Array<[string, string]> {
  const edgesById = new Map<string, [string, string]>();
  let lastTarget: string | undefined;
  let lastAgent: string | undefined;
  for (const event of trace.events) {
    if (event.kind !== 'transition' || !event.source || !event.target) continue;
    if (event.source !== lastTarget) lastAgent = agentId(event.source);
    const target = agentId(event.target);
    if (lastAgent && target && lastAgent !== target) {
      if (visibleIds.has(lastAgent) && visibleIds.has(target)) {
        edgesById.set(`${lastAgent}:${target}`, [lastAgent, target]);
      }
    }
    if (target) lastAgent = target;
    lastTarget = event.target;
  }
  return [...edgesById.values()];
}

/** Resolve status for an agent based on trace steps and transition touch state. */
export function getAgentStatus(trace: ExecutionTrace, rawNodeOrAgentId: string): AgentStatus {
  const targetId = agentId(rawNodeOrAgentId) || rawNodeOrAgentId;
  const steps = traceSteps(trace).filter((s) => (agentId(s.node) || s.node) === targetId);
  if (steps.some((s) => s.status === 'started')) return 'running';
  if (steps.some((s) => s.status === 'failed')) return 'error';
  const isTouched =
    steps.length > 0 ||
    trace.events.some(
      (e) =>
        (e.source && (agentId(e.source) || e.source) === targetId) ||
        (e.target && (agentId(e.target) || e.target) === targetId),
    );
  if (isTouched) return 'completed';
  return 'idle';
}

function computeAgentStepMetrics(trace: ExecutionTrace, steps: TraceEvent[]) {
  const duration = steps.reduce(
    (acc, step) =>
      acc +
      (step.duration_ms ??
        (step.status === 'started' ? Math.max(0, trace.elapsed_ms - step.elapsed_ms) : 0)),
    0,
  );
  const summary = [...steps].reverse().find((s) => s.summary?.trim())?.summary;
  const outcome_summary = [...steps].reverse().find((s) => s.outcome_summary?.trim())?.outcome_summary;
  return { duration, summary, outcome_summary };
}

/** Extract details and aggregated metrics for a single agent from the trace. */
export function getAgentDetails(trace: ExecutionTrace, rawAgentId: string): AgentNodeData {
  const id = agentId(rawAgentId) || rawAgentId;
  const steps = traceSteps(trace).filter((s) => (agentId(s.node) || s.node) === id);
  const { duration, summary, outcome_summary } = computeAgentStepMetrics(trace, steps);
  const known = KNOWN_AGENTS[id];
  return {
    id,
    name: known?.name ?? id,
    enName: known?.enName ?? id,
    status: getAgentStatus(trace, id),
    duration_ms: duration > 0 ? duration : undefined,
    summary,
    outcome_summary,
  };
}

function createFlowEdge(source: string, target: string, targetStatus: AgentStatus): AgentFlowEdge {
  const stroke = targetStatus === 'running' ? '#3b82f6' : targetStatus === 'error' ? '#ef4444' : '#10b981';
  return {
    id: `e-${source}-${target}`,
    source,
    target,
    animated: targetStatus === 'running',
    style: { stroke },
    markerEnd: { type: MarkerType.ArrowClosed },
  };
}

function layoutWithDagre(nodes: AgentFlowNode[], edges: AgentFlowEdge[]): AgentFlowNode[] {
  if (!nodes.length) return [];
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 24, ranksep: 48, marginx: 16, marginy: 16 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT }));
  edges.forEach((e) => {
    if (e.source !== e.target) g.setEdge(e.source, e.target);
  });
  dagre.layout(g);
  return nodes.map((node) => {
    const point = g.node(node.id);
    return {
      ...node,
      position: {
        x: point ? Math.round(point.x - NODE_WIDTH / 2) : 0,
        y: point ? Math.round(point.y - NODE_HEIGHT / 2) : 0,
      },
    };
  });
}

/** Build Dagre LR positioned agent nodes and bridged flow edges from an execution trace. */
export function buildAgentFlowGraph(
  trace: ExecutionTrace,
  selectedId?: string,
): { nodes: AgentFlowNode[]; edges: AgentFlowEdge[] } {
  const activeSelectedId = selectedId ? agentId(selectedId) || selectedId : undefined;
  const visibleIds = collectVisibleAgentIds(trace);
  const visibleSet = new Set(visibleIds);

  const rawNodes: AgentFlowNode[] = visibleIds.map((id) => ({
    id,
    type: 'agentNode',
    position: { x: 0, y: 0 },
    data: {
      ...getAgentDetails(trace, id),
      selected: Boolean(activeSelectedId && id === activeSelectedId),
    },
  }));

  const rawEdges: AgentFlowEdge[] = collectBridgedEdges(trace, visibleSet).map(([src, tgt]) =>
    createFlowEdge(src, tgt, getAgentStatus(trace, tgt)),
  );

  return {
    nodes: layoutWithDagre(rawNodes, rawEdges),
    edges: rawEdges,
  };
}
