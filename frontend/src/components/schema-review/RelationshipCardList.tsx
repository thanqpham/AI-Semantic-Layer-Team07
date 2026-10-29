'use client';

import { AlertTriangle, ArrowRight, Network } from 'lucide-react';

import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';
import { CARDINALITY, readPairs, relationshipKey, statusStyle } from '@/lib/relationshipGraph';
import { qualifiedEntity, type RelationshipItem } from '@/lib/relationshipReviewApi';
import { cn } from '@/lib/utils';
import { RelationshipStatusBadge } from './RelationshipStatusBadge';

interface Props {
  items: RelationshipItem[];
  selectedKey: string | null;
  loading: boolean;
  onOpen: (item: RelationshipItem, trigger: HTMLButtonElement) => void;
}

function RelationshipCard({ item, selected, onOpen }: { item: RelationshipItem; selected: boolean; onOpen: Props['onOpen'] }) {
  const { translate: t } = useLanguage();
  const pairs = readPairs(item).length;
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={(event) => onOpen(item, event.currentTarget)}
      style={{ borderLeftColor: statusStyle(item.status).stroke }}
      className={cn(
        'group w-full break-words rounded-xl border border-l-4 border-border bg-card p-3 text-left text-sm shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500',
        selected && 'ring-2 ring-sky-500/50',
      )}
    >
      <span className="flex flex-wrap items-center gap-1.5 font-mono text-[12px]">
        <span className="font-semibold">{qualifiedEntity(item.from_entity)}</span>
        <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
        <span className="font-semibold">{qualifiedEntity(item.to_entity)}</span>
      </span>
      <span className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
        <RelationshipStatusBadge status={item.status} />
        <span className="rounded bg-muted px-1.5 py-0.5 font-mono">{CARDINALITY[item.relationship_type]}</span>
        <span className="font-mono uppercase">{item.source}</span>
        {pairs > 1 && <span>{pairs} {t('cặp cột')}</span>}
        {item.errors.length > 0 && <span className="inline-flex items-center gap-1 text-destructive"><AlertTriangle className="h-3 w-3" aria-hidden="true" />{item.errors.length}</span>}
        <span className="ml-auto font-mono">#{item.id}</span>
      </span>
    </button>
  );
}

/** Card-style relationship list (alternative to the diagram view). */
export function RelationshipCardList({ items, selectedKey, loading, onOpen }: Props) {
  const { translate: t } = useLanguage();
  if (!loading && !items.length) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
        <Network className="h-5 w-5" aria-hidden="true" />
        <p><Translated text="Chưa có liên kết." /></p>
      </div>
    );
  }
  return (
    <div className="grid min-w-0 gap-2 xl:grid-cols-2" aria-label={t('Danh sách liên kết')}>
      {items.map((item) => <RelationshipCard key={relationshipKey(item)} item={item} selected={selectedKey === relationshipKey(item)} onOpen={onOpen} />)}
    </div>
  );
}
