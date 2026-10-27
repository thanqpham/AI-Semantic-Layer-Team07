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

interface BadgeProps {
  name: string;
  selected: boolean;
  item: RelationshipItem;
  pairCount: number;
  stroke: string;
  label: string;
  onSelect: (item: RelationshipItem, trigger: HTMLButtonElement) => void;
}

function EdgeBadge({ name, selected, item, pairCount, stroke, label, onSelect }: BadgeProps) {
  const { translate: t } = useLanguage();
  return (
    <button
      type="button"
      aria-label={name}
      aria-pressed={selected}
      title={`${name} · ${t(label)}`}
      onClick={(event) => onSelect(item, event.currentTarget)}
      className={cn(
        'origin-center cursor-pointer select-none rounded-full border bg-card px-2 py-0.5 font-mono text-[10px] font-semibold shadow-sm transition-transform duration-150 hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500',
        selected && 'scale-110 shadow-md ring-2 ring-primary/40',
      )}
      style={{ borderColor: stroke, color: stroke }}
    >
      {CARDINALITY[item.relationship_type] ?? '—'}
      {pairCount > 1 && <span className="ml-1 font-normal opacity-80">· {pairCount} {t('cột')}</span>}
    </button>
  );
}

/** Status-colored relationship edge with an accessible cardinality pill acting as the select button. */
function RelationshipEdgeComponent(props: EdgeProps<RelEdge>) {
  const { id, data, markerEnd } = props;
  const { onSelect } = useContext(DiagramActionsContext);
  if (!data) return null;
  const style = statusStyle(data.item.status);
  const [path, labelX, labelY] = edgePath(props);
  const opacity = data.dimmed ? 0.12 : style.faded ? 0.55 : 1;
  const name = `${qualifiedEntity(data.item.from_entity)} → ${qualifiedEntity(data.item.to_entity)}`;
  const x = Math.round(labelX);
  const y = Math.round(labelY);

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
        <div
          className="nodrag nopan absolute origin-center pointer-events-auto"
          style={{ transform: `translate(-50%, -50%) translate(${x}px, ${y}px)`, opacity: data.dimmed ? 0.25 : 1, zIndex: data.selected ? 20 : 5 }}
        >
          <EdgeBadge
            name={name}
            selected={data.selected}
            item={data.item}
            pairCount={data.pairCount}
            stroke={style.stroke}
            label={style.label}
            onSelect={onSelect}
          />
        </div>
      </EdgeLabelRenderer>
    </>
  );
}

export const RelationshipEdge = memo(RelationshipEdgeComponent);
