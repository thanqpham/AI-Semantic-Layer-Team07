import { AlertCircle, AlertTriangle, CheckCircle2, Save, X, XCircle, Ban } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Translated } from '@/components/ui/translated';
import { type RelationshipDraft, type RelationshipEntity, type RelationshipItem, type RelationshipPreview, qualifiedEntity, type RelationshipType } from '@/lib/relationshipReviewApi';
import { useLanguage } from '@/context/LanguageContext';
import { ColumnPairEditor } from './ColumnPairEditor';
import { RelationshipMeta } from './RelationshipMeta';
import { RelationshipStatusBadge } from './RelationshipStatusBadge';

interface Props {
  item: RelationshipItem | null; draft: RelationshipDraft; entities: RelationshipEntity[];
  preview: RelationshipPreview | null; dirty: boolean; busy: boolean; canManage: boolean; canApprove: boolean;
  onChange: (draft: RelationshipDraft) => void; onSave: () => void; onBack: () => void;
  onDecision: (action: 'approve' | 'reject' | 'disable') => void;
}
const cardinality = { many_to_one: 'N → 1', one_to_one: '1 → 1', one_to_many: '1 → N', many_to_many: 'N → M' };

function DetailHeader({ item, from, to, onBack }: { item: RelationshipItem | null; from?: RelationshipEntity; to?: RelationshipEntity; onBack: () => void }) {
  const { translate: t } = useLanguage();
  return (
    <header className="flex items-start gap-2 border-b border-border p-4">
      <div className="min-w-0 flex-1 space-y-1.5">
        {item ? <RelationshipStatusBadge status={item.status} /> : <span className="text-[10px] uppercase tracking-wide text-muted-foreground"><Translated text="Liên kết mới" /></span>}
        <h2 tabIndex={-1} className="break-words font-mono text-sm font-semibold outline-none">{from ? qualifiedEntity(from) : t('Liên kết mới')} → {to && qualifiedEntity(to)}</h2>
      </div>
      <Button variant="ghost" size="icon-sm" aria-label={t('Quay lại danh sách')} title={t('Quay lại danh sách')} onClick={onBack}><X className="size-4" /></Button>
    </header>
  );
}

function TypeFields({ draft, onChange }: Pick<Props, 'draft' | 'onChange'>) {
  const { translate: t } = useLanguage();
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="block text-xs text-muted-foreground">{t('Kiểu liên kết')}
        <select aria-label={t('Kiểu liên kết')} className="mt-1 block w-full rounded-md border border-border bg-background px-2 py-1.5 font-mono text-xs text-foreground" value={draft.relationship_type} onChange={e => onChange({ ...draft, relationship_type: e.target.value as RelationshipType })}>
          {Object.entries(cardinality).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      <label className="block text-xs text-muted-foreground">{t('Xác nhận cardinality khi thiếu bằng chứng khóa')}
        <Input className="mt-1 h-8 text-xs" value={draft.cardinality_confirmation ?? ''} onChange={e => onChange({ ...draft, cardinality_confirmation: e.target.value || null })} />
      </label>
    </div>
  );
}

function Diagnostics({ preview, item, errors, warnings, dirty }: { preview: RelationshipPreview | null; item: RelationshipItem | null; errors: RelationshipPreview['errors']; warnings: RelationshipPreview['warnings']; dirty: boolean }) {
  const { translate: t } = useLanguage();
  return (
    <div className="space-y-2">
      <div className="overflow-hidden rounded-lg border border-border">
        <span className="block border-b border-border bg-muted/60 px-3 py-1 font-mono text-[10px] text-muted-foreground">ON</span>
        <pre className="whitespace-pre-wrap break-all bg-muted/30 p-3 font-mono text-xs">{preview?.on_preview ?? item?.on_preview ?? '—'}</pre>
      </div>
      {errors.map((e, i) => <p role="alert" key={i} className="flex items-start gap-2 break-words rounded-lg border border-destructive/30 bg-destructive/10 p-2 text-xs text-destructive"><AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" /><span>{e.pair_index != null ? `${t('Cặp')} ${e.pair_index + 1}: ` : ''}{e.field && `${e.field}: `}{e.code} {e.message}</span></p>)}
      {warnings.map((w, i) => <p key={i} className="flex items-start gap-2 break-words rounded-lg border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-700 dark:text-amber-300"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />{w.code}: {w.message}</p>)}
      {dirty && <p className="text-xs text-amber-700 dark:text-amber-300"><Translated text="Có chỉnh sửa chưa lưu." /></p>}
    </div>
  );
}

function Actions({ item, dirty, busy, valid, preview, canManage, canApprove, onSave, onDecision }: Pick<Props, 'item' | 'dirty' | 'busy' | 'preview' | 'canManage' | 'canApprove' | 'onSave' | 'onDecision'> & { valid: boolean }) {
  const pending = item?.kind === 'candidate' && item.status === 'pending_review';
  return (
    <footer className="sticky bottom-0 flex flex-wrap justify-end gap-2 border-t border-border bg-card/95 p-3 backdrop-blur">
      {canManage && <Button size="sm" variant="outline" disabled={busy || !dirty || !valid || !preview} onClick={onSave}><Save className="size-3.5" /><Translated text="Lưu đề xuất" /></Button>}
      {canManage && pending && <Button size="sm" variant="outline" className="hover:text-destructive" disabled={busy || dirty} onClick={() => onDecision('reject')}><XCircle className="size-3.5" /><Translated text="Từ chối" /></Button>}
      {canApprove && pending && <Button size="sm" className="bg-emerald-600 text-white hover:bg-emerald-600/90" disabled={busy || dirty || !valid} onClick={() => onDecision('approve')}><CheckCircle2 className="size-3.5" /><Translated text="Xác nhận" /></Button>}
      {canApprove && item?.kind === 'active' && item.status === 'approved' && <Button size="sm" variant="outline" disabled={busy || dirty} onClick={() => onDecision('disable')}><Ban className="size-3.5" /><Translated text="Vô hiệu hóa" /></Button>}
    </footer>
  );
}

/** ID-based editor; selectors contain only columns owned by their selected table. */
export function RelationshipDetail(props: Props) {
  const { item, draft, entities, preview, dirty, busy, canManage, onChange, onBack } = props;
  const { translate: t } = useLanguage();
  const from = entities.find(e => e.id === draft.from_entity_id);
  const to = entities.find(e => e.id === draft.to_entity_id);
  const errors = preview?.errors ?? item?.errors ?? [];
  const warnings = preview?.warnings ?? item?.warnings ?? [];
  const valid = !!from && !!to && draft.column_pairs.length > 0 && draft.column_pairs.every(p => p.from_column_id > 0 && p.to_column_id > 0) && !errors.length;
  return <section aria-label={t('Chi tiết liên kết')} className="flex max-h-full min-w-0 flex-col overflow-hidden rounded-xl border border-border bg-card shadow-xl">
    <DetailHeader item={item} from={from} to={to} onBack={onBack} />
    <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
      {item && <RelationshipMeta item={item} />}
      <fieldset disabled={!canManage || busy} className="min-w-0 space-y-4">
        <legend className="sr-only">{t('Chỉnh sửa liên kết')}</legend>
        <ColumnPairEditor draft={draft} entities={entities} from={from} to={to} canManage={canManage} onChange={onChange} />
        <TypeFields draft={draft} onChange={onChange} />
      </fieldset>
      <Diagnostics preview={preview} item={item} errors={errors} warnings={warnings} dirty={dirty} />
    </div>
    <Actions {...props} valid={valid} />
  </section>;
}
