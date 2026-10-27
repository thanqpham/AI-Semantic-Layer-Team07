import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Translated } from '@/components/ui/translated';
import { type RelationshipDraft, type RelationshipEntity, type RelationshipItem, type RelationshipPreview, qualifiedEntity, type RelationshipType } from '@/lib/relationshipReviewApi';
import { useLanguage } from '@/context/LanguageContext';

interface Props {
  item: RelationshipItem | null; draft: RelationshipDraft; entities: RelationshipEntity[];
  preview: RelationshipPreview | null; dirty: boolean; busy: boolean; canManage: boolean; canApprove: boolean;
  onChange: (draft: RelationshipDraft) => void; onSave: () => void; onBack: () => void;
  onDecision: (action: 'approve' | 'reject' | 'disable') => void;
}
const cardinality = { many_to_one: 'N → 1', one_to_one: '1 → 1', one_to_many: '1 → N', many_to_many: 'N → M' };

/** ID-based editor; selectors contain only columns owned by their selected table. */
export function RelationshipDetail(props: Props) {
  const { item, draft, entities, preview, dirty, busy, canManage, canApprove, onChange, onSave, onBack, onDecision } = props;
  const { translate: t } = useLanguage();
  const from = entities.find(e => e.id === draft.from_entity_id);
  const to = entities.find(e => e.id === draft.to_entity_id);
  const errors = preview?.errors ?? item?.errors ?? [];
  const warnings = preview?.warnings ?? item?.warnings ?? [];
  const valid = !!from && !!to && draft.column_pairs.length > 0 && draft.column_pairs.every(p => p.from_column_id > 0 && p.to_column_id > 0) && !errors.length;
  const selectTable = (side: 'from' | 'to', id: number) => onChange({ ...draft, [`${side}_entity_id`]: id, column_pairs: draft.column_pairs.map(p => ({...p, [`${side}_column_id`]: 0})) });
  return <section aria-label={t('Chi tiết liên kết')} className="min-w-0 space-y-4 rounded-xl border border-border bg-card p-4">
    <Button variant="ghost" onClick={onBack}><Translated text="Quay lại danh sách" /></Button>
    <h2 tabIndex={-1} className="break-words text-lg font-semibold">{from ? qualifiedEntity(from) : t('Liên kết mới')} → {to && qualifiedEntity(to)}</h2>
    {item && <div className="space-y-2 text-sm">
      <p>{cardinality[item.relationship_type]} · {item.source} · {item.status}</p>
      {item.active_relationship_id && item.kind === 'candidate' && <p><Translated text="Bản sửa đang chờ; liên kết gốc vẫn hoạt động:" /> #{item.active_relationship_id}</p>}
      <p><Translated text="Người duyệt:" /> <span>{item.reviewer_name ?? item.reviewed_by ?? '—'}</span> · <time>{item.reviewed_at ?? '—'}</time></p>
      <p className="whitespace-pre-wrap break-words"><Translated text="Bằng chứng:" /> {JSON.stringify(item.evidence)}</p>
      {item.confidence != null && <p><Translated text="Độ tin cậy:" /> {item.confidence}</p>}
      {item.unresolved_questions.map((q,i)=><p key={i}>{q}</p>)}
    </div>}
    <fieldset disabled={!canManage || busy} className="min-w-0 space-y-4">
      <legend className="sr-only">{t('Chỉnh sửa liên kết')}</legend>
      <div className="grid min-w-0 gap-3 sm:grid-cols-2">{(['from','to'] as const).map((side)=><label key={side} className="min-w-0 rounded-lg border border-border p-3 text-sm">
        {t(side === 'from' ? 'Bảng nguồn' : 'Bảng đích')}
        <select aria-label={t(side === 'from' ? 'Bảng nguồn' : 'Bảng đích')} className="mt-2 w-full min-w-0 rounded border bg-background p-2" value={draft[`${side}_entity_id`]} onChange={e=>selectTable(side,Number(e.target.value))}>
          <option value={0}>{t('Chọn bảng')}</option>{entities.map(e=><option key={e.id} value={e.id}>{qualifiedEntity(e)}</option>)}
        </select>
      </label>)}</div>
      {draft.column_pairs.map((pair,index)=><div key={index} className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2">
        {(['from','to'] as const).map((side)=><label key={side} className={side === 'to' ? 'col-start-3 row-start-1 min-w-0' : 'min-w-0'}>
          <span className="sr-only">{t(side === 'from' ? 'Cột nguồn' : 'Cột đích')} {index+1}</span>
          <select aria-label={`${t(side === 'from' ? 'Cột nguồn' : 'Cột đích')} ${index+1}`} className="w-full min-w-0 rounded border bg-background p-2 text-sm" value={pair[`${side}_column_id`]} onChange={e=>onChange({...draft,column_pairs:draft.column_pairs.map((p,i)=>i===index?{...p,[`${side}_column_id`]:Number(e.target.value)}:p)})}>
            <option value={0}>{t('Chọn cột')}</option>{(side==='from'?from:to)?.columns.map(c=><option key={c.id} value={c.id}>{c.name} ({c.type})</option>)}
          </select>
        </label>)}
        <span aria-hidden="true" className="col-start-2 row-start-1">→</span>
        {canManage && <Button variant="ghost" className="col-span-3 justify-self-end" aria-label={`${t('Xóa cặp')} ${index+1}`} onClick={()=>onChange({...draft,column_pairs:draft.column_pairs.filter((_,i)=>i!==index)})}><Translated text="Xóa cặp" /></Button>}
      </div>)}
      {canManage && <Button variant="outline" onClick={()=>onChange({...draft,column_pairs:[...draft.column_pairs,{from_column_id:0,to_column_id:0}]})}><Translated text="Thêm cặp cột" /></Button>}
      <label className="block text-sm">{t('Kiểu liên kết')}
        <select aria-label={t('Kiểu liên kết')} className="ml-2 max-w-full rounded border bg-background p-2" value={draft.relationship_type} onChange={e=>onChange({...draft,relationship_type:e.target.value as RelationshipType})}>
          {Object.entries(cardinality).map(([value,label])=><option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      <label className="block text-sm">{t('Xác nhận cardinality khi thiếu bằng chứng khóa')}
        <Input value={draft.cardinality_confirmation ?? ''} onChange={e=>onChange({...draft,cardinality_confirmation:e.target.value || null})} />
      </label>
    </fieldset>
    <div className="rounded border border-border p-3"><span className="text-sm">ON</span><pre className="whitespace-pre-wrap break-all text-xs">{preview?.on_preview ?? item?.on_preview ?? '—'}</pre></div>
    {errors.map((e,i)=><p role="alert" key={i} className="break-words text-sm text-destructive">{e.pair_index != null ? `${t('Cặp')} ${e.pair_index+1}: ` : ''}{e.field && `${e.field}: `}{e.code} {e.message}</p>)}
    {warnings.map((w,i)=><p key={i} className="break-words rounded border border-amber-500/30 p-2 text-sm text-amber-700 dark:text-amber-300">{w.code}: {w.message}</p>)}
    {dirty && <p className="text-sm"><Translated text="Có chỉnh sửa chưa lưu." /></p>}
    <div className="flex flex-wrap gap-2">
      {canManage && <Button disabled={busy || !dirty || !valid || !preview} onClick={onSave}><Translated text="Lưu đề xuất" /></Button>}
      {canManage && item?.kind==='candidate' && item.status==='pending_review' && <Button variant="outline" disabled={busy || dirty} onClick={()=>onDecision('reject')}><Translated text="Từ chối" /></Button>}
      {canApprove && item?.kind==='candidate' && item.status==='pending_review' && <Button disabled={busy || dirty || !valid} onClick={()=>onDecision('approve')}><Translated text="Xác nhận" /></Button>}
      {canApprove && item?.kind==='active' && item.status==='approved' && <Button variant="outline" disabled={busy || dirty} onClick={()=>onDecision('disable')}><Translated text="Vô hiệu hóa" /></Button>}
    </div>
  </section>;
}
