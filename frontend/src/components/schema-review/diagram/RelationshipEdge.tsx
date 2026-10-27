'use client';

import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from '@xyflow/react';
import { createContext, memo, useContext } from 'react';

import { useLanguage } from '@/context/LanguageContext';
import { CARDINALITY, statusStyle, type RelEdge } from '@/lib/relationshipGraph';
import { qualifiedEntity, type RelationshipItem } from '@/lib/relationshipReviewApi';
import { cn } from '@/lib/utils';

interface DiagramActions {
  onSelect: (item: RelationshipItem, trigger: HTMLButtonElement) => void;
}

/** Lets edge labels open the detail panel without threading callbacks through edge data. */
export const DiagramActionsContext = createContext<DiagramActions>({ onSelect: () => undefined });

/** Path that loops over the top of a node for self-referencing relationships. */
export function selfLoopPath(sx: number, sy: number, tx: number, ty: number): [string, number, number] {
  const top = Math.min(sy, ty) - 90;
  const mid = (sx + tx) / 2;
  const path = `M ${sx} ${sy} C ${sx + 90} ${sy}, ${sx + 90} ${top}, ${mid} ${top} C ${tx - 90} ${top}, ${tx - 90} ${ty}, ${tx} ${ty}`;
  return [path, mid, top];
}

function edgePath(props: EdgeProps<RelEdge>): [string, number, number] {
  const { source, target, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition } = props;
  if (source === target) return selfLoopPath(sourceX, sourceY, targetX, targetY);
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, curvature: 0.35 });
  return [path, labelX, labelY];
}

/** Status-colored relationship edge with an accessible cardinality pill acting as the select button. */
function RelationshipEdgeComponent(props: EdgeProps<RelEdge>) {
  const { id, data, markerEnd } = props;
  const { onSelect } = useContext(DiagramActionsContext);
  const { translate: t } = useLanguage();
  if (!data) return null;
  const style = statusStyle(data.item.status);
  const [path, labelX, labelY] = edgePath(props);
  const opacity = data.dimmed ? 0.12 : style.faded ? 0.55 : 1;
  const name = `${qualifiedEntity(data.item.from_entity)} → ${qualifiedEntity(data.item.to_entity)}`;
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        interactionWidth={22}
        className={cn(style.animated && !data.dimmed && 'rel-edge-flow')}
        style={{ stroke: style.stroke, strokeWidth: data.selected ? 2.75 : 1.75, strokeDasharray: style.dash, opacity, transition: 'opacity .2s, stroke-width .2s' }}
      />
      <EdgeLabelRenderer>
        <button
          type="button"
          aria-label={name}
          aria-pressed={data.selected}
          title={`${name} · ${t(style.label)}`}
          onClick={(event) => onSelect(data.item, event.currentTarget)}
          className={cn(
            'nodrag nopan absolute rounded-full border bg-card px-2 py-0.5 font-mono text-[10px] font-semibold shadow-sm transition-all hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500',
            data.selected && 'scale-110 shadow-md',
          )}
          style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`, borderColor: style.stroke, color: style.stroke, opacity: data.dimmed ? 0.25 : 1, pointerEvents: 'all' }}
        >
          {CARDINALITY[data.item.relationship_type] ?? '—'}
          {data.pairCount > 1 && <span className="ml-1 font-normal opacity-80">· {data.pairCount} {t('cột')}</span>}
        </button>
      </EdgeLabelRenderer>
    </>
  );
}

export const RelationshipEdge = memo(RelationshipEdgeComponent);
