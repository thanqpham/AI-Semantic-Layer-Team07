'use client';

import { Handle, Position, type NodeProps } from '@xyflow/react';
import { ChevronDown, KeyRound, Link2, Table2 } from 'lucide-react';
import { memo, useState } from 'react';

import { useLanguage } from '@/context/LanguageContext';
import { visibleColumns, type GraphColumn, type TableNode as TableNodeType } from '@/lib/relationshipGraph';
import { cn } from '@/lib/utils';

const HANDLE = '!h-2 !w-2 !min-w-0 !rounded-full !border-0 !bg-transparent';

function ColumnBadge({ column }: { column: GraphColumn }) {
  if (column.pk) {
    return <span title="Primary key" className="flex h-4 w-4 shrink-0 items-center justify-center rounded bg-amber-500/15 text-amber-600 dark:text-amber-400"><KeyRound className="h-2.5 w-2.5" /></span>;
  }
  if (column.fk) {
    return <span title="Foreign key" className="flex h-4 w-4 shrink-0 items-center justify-center rounded bg-sky-500/15 text-sky-600 dark:text-sky-400"><Link2 className="h-2.5 w-2.5" /></span>;
  }
  return <span className="h-4 w-4 shrink-0" />;
}

function ColumnRow({ column, highlighted }: { column: GraphColumn; highlighted: boolean }) {
  return (
    <div
      className={cn(
        'relative flex h-7 items-center gap-2 px-3 text-[11px] transition-colors',
        column.linked && 'bg-muted/40',
        highlighted && 'bg-sky-500/15 ring-1 ring-inset ring-sky-500/40',
      )}
    >
      <Handle type="target" position={Position.Left} id={`col-${column.id}-tgt`} className={HANDLE} isConnectable={false} />
      <ColumnBadge column={column} />
      <span className={cn('min-w-0 flex-1 truncate font-mono', column.linked ? 'text-foreground' : 'text-foreground/80')}>{column.name}</span>
      <span className="max-w-[40%] shrink-0 truncate font-mono text-[10px] text-muted-foreground">{column.type}</span>
      <Handle type="source" position={Position.Right} id={`col-${column.id}-src`} className={HANDLE} isConnectable={false} />
    </div>
  );
}

function TableHeader({ label, count }: { label: string; count: number }) {
  const { translate: t } = useLanguage();
  return (
    <div className="relative flex items-center gap-2 border-b border-border bg-muted/60 px-3 py-2.5">
      <Handle type="target" position={Position.Left} id="tbl-tgt" className={HANDLE} isConnectable={false} />
      <Table2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <span className="min-w-0 flex-1 truncate font-mono text-[12px] font-semibold" title={label}>{label}</span>
      <span className="shrink-0 rounded-full bg-background px-1.5 py-0.5 font-mono text-[9px] text-muted-foreground">{count} {t('cột')}</span>
      <Handle type="source" position={Position.Right} id="tbl-src" className={HANDLE} isConnectable={false} />
    </div>
  );
}

function ExpandToggle({ expanded, hidden, onToggle }: { expanded: boolean; hidden: number; onToggle: () => void }) {
  const { translate: t } = useLanguage();
  return (
    <button
      type="button"
      onClick={(event) => { event.stopPropagation(); onToggle(); }}
      className="nodrag flex w-full items-center justify-center gap-1 border-t border-border py-1.5 text-[10px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
    >
      <ChevronDown className={cn('h-3 w-3 transition-transform', expanded && 'rotate-180')} />
      {expanded ? t('Thu gọn') : `+${hidden} ${t('cột')}`}
    </button>
  );
}

/** ERD table card: header + column rows, each row exposing left/right handles for column-level edges. */
function TableNodeComponent({ data, selected }: NodeProps<TableNodeType>) {
  const [expanded, setExpanded] = useState(false);
  const shown = visibleColumns(data.columns, expanded);
  const collapsible = visibleColumns(data.columns).length < data.columns.length;
  const highlight = new Set(data.highlight);
  return (
    <div
      data-testid={`table-node-${data.label}`}
      data-dimmed={data.dimmed}
      className={cn(
        'w-[264px] overflow-hidden rounded-xl border bg-card text-card-foreground shadow-sm transition-all duration-200',
        selected ? 'border-sky-500/60 shadow-lg shadow-sky-500/10' : 'border-border hover:border-foreground/30 hover:shadow-md',
        data.dimmed && 'opacity-25',
      )}
    >
      <TableHeader label={data.label} count={data.columns.length} />
      <div className="divide-y divide-border/50 py-1">
        {shown.map((column) => <ColumnRow key={column.id} column={column} highlighted={highlight.has(column.id)} />)}
      </div>
      {collapsible && <ExpandToggle expanded={expanded} hidden={data.columns.length - shown.length} onToggle={() => setExpanded((value) => !value)} />}
    </div>
  );
}

export const TableNode = memo(TableNodeComponent);
