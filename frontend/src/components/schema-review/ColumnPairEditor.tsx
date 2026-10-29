'use client';

import { ArrowRight, Plus, Table2, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';
import { qualifiedEntity, type RelationshipDraft, type RelationshipEntity } from '@/lib/relationshipReviewApi';

type Side = 'from' | 'to';

interface Props {
  draft: RelationshipDraft;
  entities: RelationshipEntity[];
  from?: RelationshipEntity;
  to?: RelationshipEntity;
  canManage: boolean;
  onChange: (draft: RelationshipDraft) => void;
}

const selectClass = 'w-full min-w-0 rounded-md border border-border bg-background px-2 py-1.5 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-sky-500/40';

function TableSelect({ side, draft, entities, onChange }: Pick<Props, 'draft' | 'entities' | 'onChange'> & { side: Side }) {
  const { translate: t } = useLanguage();
  const label = t(side === 'from' ? 'Bảng nguồn' : 'Bảng đích');
  const select = (id: number) => onChange({ ...draft, [`${side}_entity_id`]: id, column_pairs: draft.column_pairs.map((p) => ({ ...p, [`${side}_column_id`]: 0 })) });
  return (
    <label className="min-w-0 flex-1 rounded-lg border border-border bg-background/60 p-2.5 text-[10px] uppercase tracking-wide text-muted-foreground">
      <span className="flex items-center gap-1"><Table2 className="h-3 w-3" aria-hidden="true" />{label}</span>
      <select aria-label={label} className={`${selectClass} mt-1.5 normal-case tracking-normal text-foreground`} value={draft[`${side}_entity_id`]} onChange={(e) => select(Number(e.target.value))}>
        <option value={0}>{t('Chọn bảng')}</option>
        {entities.map((entity) => <option key={entity.id} value={entity.id}>{qualifiedEntity(entity)}</option>)}
      </select>
    </label>
  );
}

function ColumnSelect({ side, index, value, entity, onSelect }: { side: Side; index: number; value: number; entity?: RelationshipEntity; onSelect: (id: number) => void }) {
  const { translate: t } = useLanguage();
  const label = `${t(side === 'from' ? 'Cột nguồn' : 'Cột đích')} ${index + 1}`;
  return (
    <label className="min-w-0">
      <span className="sr-only">{label}</span>
      <select aria-label={label} className={selectClass} value={value} onChange={(e) => onSelect(Number(e.target.value))}>
        <option value={0}>{t('Chọn cột')}</option>
        {entity?.columns.map((column) => <option key={column.id} value={column.id}>{column.name} ({column.type})</option>)}
      </select>
    </label>
  );
}

/** Visual column-pair mapping editor: [source table] → [target table] and per-pair column selectors. */
export function ColumnPairEditor({ draft, entities, from, to, canManage, onChange }: Props) {
  const { translate: t } = useLanguage();
  const setPair = (index: number, side: Side, id: number) => onChange({ ...draft, column_pairs: draft.column_pairs.map((p, i) => (i === index ? { ...p, [`${side}_column_id`]: id } : p)) });
  return (
    <div className="space-y-3">
      <div className="flex min-w-0 flex-col items-stretch gap-2 sm:flex-row sm:items-center">
        <TableSelect side="from" draft={draft} entities={entities} onChange={onChange} />
        <ArrowRight className="mx-auto h-4 w-4 shrink-0 rotate-90 text-muted-foreground sm:rotate-0" aria-hidden="true" />
        <TableSelect side="to" draft={draft} entities={entities} onChange={onChange} />
      </div>
      <div className="space-y-2 rounded-lg border border-dashed border-border p-2.5">
        <p className="text-[10px] uppercase tracking-wide text-muted-foreground"><Translated text="Ánh xạ cột" /></p>
        {draft.column_pairs.map((pair, index) => (
          <div key={index} className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto] items-center gap-2">
            <ColumnSelect side="from" index={index} value={pair.from_column_id} entity={from} onSelect={(id) => setPair(index, 'from', id)} />
            <span aria-hidden="true" className="flex h-5 w-5 items-center justify-center rounded-full bg-sky-500/15 text-sky-600 dark:text-sky-400"><ArrowRight className="h-3 w-3" /></span>
            <ColumnSelect side="to" index={index} value={pair.to_column_id} entity={to} onSelect={(id) => setPair(index, 'to', id)} />
            {canManage ? <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive" aria-label={`${t('Xóa cặp')} ${index + 1}`} onClick={() => onChange({ ...draft, column_pairs: draft.column_pairs.filter((_, i) => i !== index) })}><Trash2 className="size-3.5" /></Button> : <span />}
          </div>
        ))}
        {canManage && <Button variant="ghost" size="sm" className="h-7 gap-1.5 text-xs" onClick={() => onChange({ ...draft, column_pairs: [...draft.column_pairs, { from_column_id: 0, to_column_id: 0 }] })}><Plus className="size-3.5" aria-hidden="true" /><Translated text="Thêm cặp cột" /></Button>}
      </div>
    </div>
  );
}
