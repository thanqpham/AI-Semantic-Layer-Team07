import { describe, expect, it } from 'vitest';
import { MarkerType } from '@xyflow/react';
import type { ExecutionTrace } from '@/lib/chatTrace';
import {
  buildAgentFlowGraph,
  getAgentDetails,
  getAgentStatus,
  KNOWN_AGENTS,
  NODE_HEIGHT,
  NODE_WIDTH,
} from './agentFlowGraph';

function makeTrace(events: ExecutionTrace['events'] = []): ExecutionTrace {
  return {
    run_id: 'test-run-1',
    status: 'completed',
    started_at: '2026-10-30T00:00:00Z',
    finished_at: '2026-10-30T00:00:10Z',
    elapsed_ms: 10000,
    events,
  };
}

describe('agentFlowGraph', () => {
  it('deduplicates multiple runs of the same agent into a single node', () => {
    const trace = makeTrace([
      {
        seq: 1,
        kind: 'transition',
        step_id: 't-1',
        node: 'orchestrator',
        source: 'orchestrator',
        target: 'metric_review',
        at: '',
        elapsed_ms: 500,
        status: 'finished',
        summary: '',
      },
      {
        seq: 2,
        kind: 'step',
        step_id: 's-rev-1',
        node: 'metric_review',
        action: 'metric_review',
        at: '',
        elapsed_ms: 600,
        duration_ms: 1200,
        status: 'finished',
        summary: 'Review round 1: needs revision',
        outcome_summary: 'Needs revision',
      },
      {
        seq: 3,
        kind: 'step',
        step_id: 's-rev-2',
        node: 'metric_review',
        action: 'metric_review',
        at: '',
        elapsed_ms: 2500,
        duration_ms: 900,
        status: 'finished',
        summary: 'Review round 2: approved',
        outcome_summary: 'Approved',
      },
    ]);

    const { nodes } = buildAgentFlowGraph(trace);
    const reviewNodes = nodes.filter((n) => n.id === 'metric_review');

    expect(reviewNodes).toHaveLength(1);
    expect(reviewNodes[0].data.name).toBe('Metric Reviewer Agent');
    expect(reviewNodes[0].data.enName).toBe('Metric Reviewer Agent');
  });

  it('maps metric_repair to metric_suggest node', () => {
    const trace = makeTrace([
      {
        seq: 1,
        kind: 'transition',
        step_id: 't-1',
        node: 'orchestrator',
        source: 'orchestrator',
        target: 'metric_repair',
        at: '',
        elapsed_ms: 100,
        status: 'finished',
        summary: '',
      },
      {
        seq: 2,
        kind: 'step',
        step_id: 's-rep-1',
        node: 'metric_repair',
        action: 'metric_repair',
        at: '',
        elapsed_ms: 200,
        duration_ms: 800,
        status: 'finished',
        summary: 'Sửa metric theo feedback',
      },
    ]);

    const { nodes } = buildAgentFlowGraph(trace);
    expect(nodes.some((n) => n.id === 'metric_repair')).toBe(false);

    const suggestNode = nodes.find((n) => n.id === 'metric_suggest');
    expect(suggestNode).toBeDefined();
    expect(suggestNode?.data.name).toBe('Metric Designer Agent');

    const details = getAgentDetails(trace, 'metric_repair');
    expect(details.id).toBe('metric_suggest');
  });

  it('derives correct status: running, completed, error, idle', () => {
    const runningTrace = makeTrace([
      {
        seq: 1,
        kind: 'step',
        step_id: 's-1',
        node: 'orchestrator',
        action: 'orchestrator',
        at: '',
        elapsed_ms: 0,
        status: 'started',
        summary: 'Đang điều phối',
      },
    ]);
    expect(getAgentStatus(runningTrace, 'orchestrator')).toBe('running');

    const errorTrace = makeTrace([
      {
        seq: 1,
        kind: 'step',
        step_id: 's-2',
        node: 'orchestrator',
        action: 'orchestrator',
        at: '',
        elapsed_ms: 0,
        status: 'failed',
        summary: 'Lỗi thực thi',
      },
    ]);
    expect(getAgentStatus(errorTrace, 'orchestrator')).toBe('error');

    const completedTrace = makeTrace([
      {
        seq: 1,
        kind: 'step',
        step_id: 's-3',
        node: 'orchestrator',
        action: 'orchestrator',
        at: '',
        elapsed_ms: 0,
        status: 'finished',
        summary: 'Hoàn tất phân tích',
      },
    ]);
    expect(getAgentStatus(completedTrace, 'orchestrator')).toBe('completed');

    const idleTrace = makeTrace([]);
    expect(getAgentStatus(idleTrace, 'chitchat')).toBe('idle');
  });

  it('bridges transitions across hidden system steps when continuous', () => {
    const trace = makeTrace([
      {
        seq: 1,
        kind: 'transition',
        step_id: 't-1',
        node: 'orchestrator',
        source: 'orchestrator',
        target: 'context',
        at: '',
        elapsed_ms: 10,
        status: 'finished',
        summary: '',
      },
      {
        seq: 2,
        kind: 'transition',
        step_id: 't-2',
        node: 'context',
        source: 'context',
        target: 'metric_coordinator',
        at: '',
        elapsed_ms: 20,
        status: 'finished',
        summary: '',
      },
      {
        seq: 3,
        kind: 'transition',
        step_id: 't-3',
        node: 'metric_coordinator',
        source: 'metric_coordinator',
        target: 'metric_suggest',
        at: '',
        elapsed_ms: 30,
        status: 'finished',
        summary: '',
      },
      {
        seq: 4,
        kind: 'step',
        step_id: 's-sug',
        node: 'metric_suggest',
        action: 'metric_suggest',
        at: '',
        elapsed_ms: 35,
        status: 'started',
        summary: 'Generating draft metric',
      },
    ]);

    const { nodes, edges } = buildAgentFlowGraph(trace);
    expect(nodes.map((n) => n.id)).toEqual(['orchestrator', 'metric_suggest']);
    expect(edges).toHaveLength(1);

    const edge = edges[0];
    expect(edge.id).toBe('e-orchestrator-metric_suggest');
    expect(edge.source).toBe('orchestrator');
    expect(edge.target).toBe('metric_suggest');
    // target is running -> animated and blue
    expect(edge.animated).toBe(true);
    expect(edge.style?.stroke).toBe('#3b82f6');
    expect(edge.markerEnd).toEqual(expect.objectContaining({ type: MarkerType.ArrowClosed }));
  });

  it('does not create an edge when there is a break in the transition chain', () => {
    const trace = makeTrace([
      {
        seq: 1,
        kind: 'transition',
        step_id: 't-1',
        node: 'orchestrator',
        source: 'orchestrator',
        target: 'context',
        at: '',
        elapsed_ms: 10,
        status: 'finished',
        summary: '',
      },
      // Broken chain: source is metric_validate, not context
      {
        seq: 2,
        kind: 'transition',
        step_id: 't-2',
        node: 'metric_validate',
        source: 'metric_validate',
        target: 'metric_suggest',
        at: '',
        elapsed_ms: 50,
        status: 'finished',
        summary: '',
      },
    ]);

    const { edges } = buildAgentFlowGraph(trace);
    expect(edges).toHaveLength(0);
  });

  it('computes positive Dagre LR coordinates where source.x < target.x', () => {
    const trace = makeTrace([
      {
        seq: 1,
        kind: 'transition',
        step_id: 't-1',
        node: 'orchestrator',
        source: 'orchestrator',
        target: 'metric_suggest',
        at: '',
        elapsed_ms: 10,
        status: 'finished',
        summary: '',
      },
      {
        seq: 2,
        kind: 'transition',
        step_id: 't-2',
        node: 'metric_suggest',
        source: 'metric_suggest',
        target: 'metric_review',
        at: '',
        elapsed_ms: 20,
        status: 'finished',
        summary: '',
      },
    ]);

    const { nodes } = buildAgentFlowGraph(trace);
    expect(nodes).toHaveLength(3);

    const orchestrator = nodes.find((n) => n.id === 'orchestrator')!;
    const suggest = nodes.find((n) => n.id === 'metric_suggest')!;
    const review = nodes.find((n) => n.id === 'metric_review')!;

    // Coordinates are positive
    expect(orchestrator.position.x).toBeGreaterThan(0);
    expect(orchestrator.position.y).toBeGreaterThan(0);
    expect(suggest.position.x).toBeGreaterThan(0);
    expect(review.position.x).toBeGreaterThan(0);

    // Left-to-right ordering along the flow
    expect(suggest.position.x).toBeGreaterThan(orchestrator.position.x);
    expect(review.position.x).toBeGreaterThan(suggest.position.x);

    // Card dimensions
    expect(NODE_WIDTH).toBe(180);
    expect(NODE_HEIGHT).toBe(56);
  });

  it('returns correct agent details and aggregates duration', () => {
    const trace = makeTrace([
      {
        seq: 1,
        kind: 'step',
        step_id: 's-1',
        node: 'metric_review',
        action: 'metric_review',
        at: '',
        elapsed_ms: 100,
        duration_ms: 1100,
        status: 'finished',
        summary: 'Review round 1',
        outcome_summary: 'Cần sửa đổi công thức',
      },
      {
        seq: 2,
        kind: 'step',
        step_id: 's-2',
        node: 'metric_review',
        action: 'metric_review',
        at: '',
        elapsed_ms: 2000,
        duration_ms: 1400,
        status: 'finished',
        summary: 'Review round 2',
        outcome_summary: 'Chỉ số đạt tiêu chuẩn',
      },
    ]);

    const details = getAgentDetails(trace, 'metric_review');
    expect(details.id).toBe('metric_review');
    expect(details.name).toBe(KNOWN_AGENTS.metric_review.name);
    expect(details.enName).toBe(KNOWN_AGENTS.metric_review.enName);
    expect(details.status).toBe('completed');
    expect(details.duration_ms).toBe(2500);
    expect(details.summary).toBe('Review round 2');
    expect(details.outcome_summary).toBe('Chỉ số đạt tiêu chuẩn');
  });

  it('marks selected node according to selectedId parameter', () => {
    const trace = makeTrace([
      {
        seq: 1,
        kind: 'step',
        step_id: 's-1',
        node: 'orchestrator',
        action: 'orchestrator',
        at: '',
        elapsed_ms: 0,
        status: 'finished',
        summary: 'Phân loại',
      },
      {
        seq: 2,
        kind: 'step',
        step_id: 's-2',
        node: 'data_assistant',
        action: 'data_assistant',
        at: '',
        elapsed_ms: 100,
        status: 'finished',
        summary: 'Hỗ trợ dữ liệu',
      },
    ]);

    const { nodes } = buildAgentFlowGraph(trace, 'data_assistant');
    const orchestrator = nodes.find((n) => n.id === 'orchestrator')!;
    const assistant = nodes.find((n) => n.id === 'data_assistant')!;

    expect(orchestrator.data.selected).toBe(false);
    expect(assistant.data.selected).toBe(true);
  });
});
