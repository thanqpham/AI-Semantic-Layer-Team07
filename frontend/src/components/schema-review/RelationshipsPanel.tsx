import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';
import { getSchemaReviewApi, SemanticApiError } from '@/lib/api';
import {
  decideRelationship,
  getRelationshipImpact,
  listRelationships,
  previewRelationship,
  saveRelationship,
  suggestRelationships,
  type RelationshipDraft,
  type RelationshipEntity,
  type RelationshipImpact,
  type RelationshipItem,
  type RelationshipList,
  type RelationshipPreview,
} from '@/lib/relationshipReviewApi';
import { RelationshipCardList } from './RelationshipCardList';
import { RelationshipDetail } from './RelationshipDetail';
import { RelationshipToolbar, type RelationshipView } from './RelationshipToolbar';
import { RelationshipDiagram } from './diagram/RelationshipDiagram';

interface Props {
  dbId: string;
  canManageSchema: boolean;
  canApproveSchema: boolean;
  onReviewChanged: () => void;
  onNotify?: (message: string) => void;
  onDirtyChange?: (dirty: boolean) => void;
  initialView?: RelationshipView;
}

const emptyDraft: RelationshipDraft = {
  from_entity_id: 0,
  to_entity_id: 0,
  column_pairs: [{ from_column_id: 0, to_column_id: 0 }],
  relationship_type: 'many_to_one',
};

const toDraft = (item: RelationshipItem): RelationshipDraft => ({
  from_entity_id: item.from_entity.id,
  to_entity_id: item.to_entity.id,
  column_pairs:
    Array.isArray(item.column_pairs) &&
    item.column_pairs.length &&
    item.column_pairs.every(
      (p) =>
        p &&
        typeof p === 'object' &&
        Number.isInteger(p.from_column_id) &&
        Number.isInteger(p.to_column_id) &&
        Object.keys(p).length === 2,
    )
      ? item.column_pairs
      : [{ from_column_id: 0, to_column_id: 0 }],
  relationship_type: item.relationship_type,
  expected_revision: item.revision,
  cardinality_confirmation:
    typeof item.evidence.cardinality_confirmation === 'string'
      ? item.evidence.cardinality_confirmation
      : null,
});

const message = (error: unknown) => (error instanceof Error ? error.message : 'Không thể tải liên kết');
const key = (item: RelationshipItem) => `${item.kind}:${item.id}`;

/** Scoped relationship queue with ERD diagram, card list toggle, and slide-over detail. */
export function RelationshipsPanel({
  dbId,
  canManageSchema,
  canApproveSchema,
  onReviewChanged,
  onNotify,
  onDirtyChange,
  initialView = 'diagram',
}: Props) {
  const { translate: t } = useLanguage();
  const [data, setData] = useState<RelationshipList>({ items: [], counts: { pending_relationships: 0 } });
  const [entities, setEntities] = useState<RelationshipEntity[]>([]);
  const [selected, setSelected] = useState<RelationshipItem | null>(null);
  const [detail, setDetail] = useState(false);
  const [draft, setDraft] = useState<RelationshipDraft>(emptyDraft);
  const [baseline, setBaseline] = useState('');
  const [preview, setPreview] = useState<RelationshipPreview | null>(null);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [view, setView] = useState<RelationshipView>(initialView);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [impact, setImpact] = useState<RelationshipImpact | null>(null);
  const [action, setAction] = useState<'approve' | 'disable'>('approve');
  const [ack, setAck] = useState(false);
  const [leave, setLeave] = useState<(() => void) | null>(null);

  const currentDb = useRef(dbId);
  useLayoutEffect(() => {
    currentDb.current = dbId;
  }, [dbId]);

  const requestId = useRef(0);
  const rowFocus = useRef<HTMLButtonElement | null>(null);
  const panel = useRef<HTMLDivElement>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const dialogInvoker = useRef<HTMLElement | null>(null);

  const dirty = detail && JSON.stringify(draft) !== baseline;
  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);

  const load = useCallback(async () => {
    const request = ++requestId.current;
    setLoading(true);
    setError('');
    try {
      const result = await listRelationships(dbId, status, search);
      if (request === requestId.current && dbId === currentDb.current) setData(result);
    } catch (e) {
      if (request === requestId.current && dbId === currentDb.current) setError(message(e));
    } finally {
      if (request === requestId.current && dbId === currentDb.current) setLoading(false);
    }
  }, [dbId, status, search]);

  useEffect(() => {
    void load();
    return () => {
      requestId.current++;
    };
  }, [load]);

  useEffect(() => {
    setData({ items: [], counts: { pending_relationships: 0 } });
    setEntities([]);
    setDetail(false);
    setSelected(null);
    setImpact(null);
    setBusy(false);
    setLeave(null);
    let cancelled = false;
    getSchemaReviewApi(dbId)
      .then((r) => {
        if (!cancelled) {
          setEntities(
            r.tables.map((table) => ({
              id: table.table_id,
              name: table.table_name,
              schema: table.physical_schema,
              columns: table.columns.map((c) => ({
                id: c.column_id,
                name: c.column_name,
                type: c.data_type,
                is_primary_key: c.is_primary_key,
              })),
            })),
          );
        }
      })
      .catch((e) => {
        if (!cancelled) setError(message(e));
      });
    return () => {
      cancelled = true;
    };
  }, [dbId]);

  useEffect(() => {
    if (detail) panel.current?.querySelector<HTMLElement>('h2')?.focus();
  }, [detail, selected]);

  useEffect(() => {
    if (impact || leave) dialog.current?.querySelector<HTMLElement>('button')?.focus();
  }, [impact, leave]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  useEffect(() => {
    if (!detail) return;
    if (!dirty) {
      setPreview(selected ? { on_preview: selected.on_preview, errors: selected.errors, warnings: selected.warnings } : null);
      return;
    }
    let cancelled = false;
    setPreview(null);
    const timer = setTimeout(() => {
      previewRelationship(dbId, draft)
        .then((p) => {
          if (!cancelled) setPreview(p);
        })
        .catch((e) => {
          if (cancelled) return;
          const errors =
            e instanceof SemanticApiError && e.detail && typeof e.detail === 'object' && 'errors' in e.detail
              ? (e.detail as { errors: RelationshipPreview['errors'] }).errors
              : [{ message: message(e) }];
          setPreview({ on_preview: '', errors, warnings: [] });
        });
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [dbId, draft, detail, dirty, selected]);

  const guard = (next: () => void) => {
    if (dirty) {
      dialogInvoker.current = document.activeElement as HTMLElement;
      setLeave(() => next);
    } else next();
  };

  const closeDialog = () => {
    setImpact(null);
    setLeave(null);
    dialogInvoker.current?.focus();
  };

  const open = (item: RelationshipItem | null) => {
    setSelected(item);
    const next = item ? toDraft(item) : emptyDraft;
    setDraft(next);
    setBaseline(item ? JSON.stringify(next) : '');
    setPreview(item ? { on_preview: item.on_preview, errors: item.errors, warnings: item.warnings } : null);
    setDetail(true);
    setError('');
  };

  const back = () =>
    guard(() => {
      setDetail(false);
      setSelected(null);
      setTimeout(() => rowFocus.current?.focus(), 0);
    });

  const changed = async () => {
    await load();
    if (dbId === currentDb.current) onReviewChanged();
  };

  const save = async () => {
    setBusy(true);
    setError('');
    try {
      await previewRelationship(dbId, draft);
      const result = await saveRelationship(dbId, draft, selected);
      if (dbId !== currentDb.current) return;
      open(result.item);
      await changed();
      onNotify?.(t('Đã lưu đề xuất, chờ xác nhận'));
    } catch (e) {
      if (dbId === currentDb.current) setError(message(e));
    } finally {
      if (dbId === currentDb.current) setBusy(false);
    }
  };

  const suggest = async () => {
    setBusy(true);
    setError('');
    try {
      await suggestRelationships(dbId);
      if (dbId !== currentDb.current) return;
      await changed();
      onNotify?.(t('Đề xuất AI đang chờ review'));
    } catch (e) {
      if (dbId === currentDb.current) setError(message(e));
    } finally {
      if (dbId === currentDb.current) setBusy(false);
    }
  };

  const decide = async (next: 'approve' | 'reject' | 'disable') => {
    dialogInvoker.current = document.activeElement as HTMLElement;
    if (!selected || dirty) return;
    setBusy(true);
    setError('');
    try {
      if (next === 'reject') {
        await decideRelationship(dbId, selected, next, { expected_revision: selected.revision });
        if (dbId !== currentDb.current) return;
        setDetail(false);
        await changed();
      } else {
        const result = await getRelationshipImpact(dbId, selected, next);
        if (dbId !== currentDb.current) return;
        setAction(next);
        setImpact(result);
        setAck(false);
      }
    } catch (e) {
      if (dbId === currentDb.current) setError(message(e));
    } finally {
      if (dbId === currentDb.current) setBusy(false);
    }
  };

  const confirm = async () => {
    if (!selected || !impact || !ack) return;
    setBusy(true);
    setError('');
    try {
      await decideRelationship(dbId, selected, action, {
        expected_revision: selected.revision,
        impact_token: impact.token,
        acknowledge_impact: true,
      });
      if (dbId !== currentDb.current) return;
      setImpact(null);
      setDetail(false);
      await changed();
      onNotify?.(t('Đã cập nhật liên kết. Chọn metric và dimensions để xem SQL mới.'));
    } catch (e) {
      if (dbId !== currentDb.current) return;
      setError(message(e));
      if (e instanceof SemanticApiError && e.status === 409) {
        setAck(false);
        try {
          const fresh = await listRelationships(dbId);
          const row = fresh.items.find((i) => key(i) === key(selected));
          if (dbId !== currentDb.current) return;
          setData(fresh);
          if (row) {
            open(row);
            const nextImpact = await getRelationshipImpact(dbId, row, action);
            if (dbId === currentDb.current) setImpact(nextImpact);
          } else setImpact(null);
        } catch (reload) {
          setImpact(null);
          setError(message(reload));
        }
      }
    } finally {
      if (dbId === currentDb.current) setBusy(false);
    }
  };

  const trap = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape' && !busy) {
      closeDialog();
      return;
    }
    if (event.key !== 'Tab') return;
    const controls = dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled)');
    if (!controls?.length) return;
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div ref={panel} className="min-w-0 space-y-4">
      <RelationshipToolbar
        search={search}
        onSearch={setSearch}
        status={status}
        onStatus={setStatus}
        view={view}
        onView={setView}
        pending={data.counts.pending_relationships}
        canManage={canManageSchema}
        busy={busy}
        onSuggest={suggest}
        onAdd={() => guard(() => open(null))}
      />

      {error && (
        <div role="alert" className="break-words rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {error} <Button variant="outline" size="sm" onClick={() => void load()}><Translated text="Thử lại" /></Button>
        </div>
      )}

      {loading && <p role="status" className="text-sm text-muted-foreground"><Translated text="Đang tải liên kết…" /></p>}

      <div className="relative flex min-h-0 flex-1 gap-4">
        <div className="min-w-0 flex-1">
          {view === 'diagram' ? (
            <RelationshipDiagram
              entities={entities}
              items={data.items}
              selectedKey={selected ? key(selected) : null}
              loading={loading}
              onSelectEdge={(item, trigger) =>
                guard(() => {
                  if (trigger instanceof HTMLButtonElement) rowFocus.current = trigger;
                  open(item);
                })
              }
            />
          ) : (
            <RelationshipCardList
              items={data.items}
              selectedKey={selected ? key(selected) : null}
              loading={loading}
              onOpen={(item, trigger) =>
                guard(() => {
                  rowFocus.current = trigger;
                  open(item);
                })
              }
            />
          )}
        </div>

        {detail && (
          <aside className="animate-slide-in-right z-30 flex w-full flex-col lg:w-[420px] lg:shrink-0 max-lg:fixed max-lg:inset-0 max-lg:bg-background/80 max-lg:p-4 max-lg:backdrop-blur">
            <RelationshipDetail
              item={selected}
              draft={draft}
              entities={entities}
              preview={preview}
              dirty={dirty}
              busy={busy}
              canManage={canManageSchema}
              canApprove={canApproveSchema}
              onChange={setDraft}
              onSave={save}
              onBack={back}
              onDecision={decide}
            />
          </aside>
        )}
      </div>

      {(impact || leave) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs">
          <div
            ref={dialog}
            role="dialog"
            aria-modal="true"
            aria-labelledby="relationship-dialog-title"
            onKeyDown={trap}
            className="max-h-[90dvh] w-full max-w-xl space-y-4 overflow-y-auto rounded-2xl border border-border bg-background p-6 shadow-2xl"
          >
            <h2 id="relationship-dialog-title" className="text-lg font-semibold">
              <Translated text={leave ? 'Bỏ chỉnh sửa chưa lưu?' : 'Xem trước tác động'} />
            </h2>
            {leave ? (
              <div className="flex flex-wrap gap-2 pt-2">
                <Button onClick={closeDialog}><Translated text="Tiếp tục chỉnh sửa" /></Button>
                <Button variant="outline" onClick={() => { leave(); setLeave(null); }}><Translated text="Bỏ chỉnh sửa" /></Button>
              </div>
            ) : (
              impact && (
                <>
                  <p className="text-sm text-muted-foreground">
                    <Translated text="Các metric bên dưới sẽ chuyển sang needs_review; định nghĩa và SQL đã duyệt không bị viết lại. SQL đã lưu bên ngoài ứng dụng không thể thu hồi." />
                  </p>
                  <ul className="space-y-1 rounded-lg border border-border bg-muted/40 p-3 font-mono text-xs">
                    {impact.published_metrics.map((m, i) => (
                      <li key={i}>{m.name} #{m.metric_id ?? m.id}</li>
                    ))}
                    {impact.metric_ids.map((id) => (
                      <li key={`id-${id}`}>Metric #{id}</li>
                    ))}
                  </ul>
                  <p className="break-words text-sm">
                    <Translated text="Đường JOIN thay đổi:" />{' '}
                    <span className="font-mono text-xs">{impact.join_paths.map((p) => p.join(' → ')).join('; ') || '—'}</span>
                  </p>
                  <pre className="whitespace-pre-wrap break-all rounded-lg bg-muted p-3 font-mono text-xs">
                    {impact.before_on} → {impact.after_on}
                  </pre>
                  {impact.warnings.map((w, i) => (
                    <p key={i} className="break-words rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 text-xs text-amber-700 dark:text-amber-300">
                      {w.code}: {w.message}
                    </p>
                  ))}
                  <label className="flex items-start gap-2.5 text-sm font-medium">
                    <input type="checkbox" className="mt-0.5 rounded" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                    <Translated text="Tôi hiểu và xác nhận tác động này" />
                  </label>
                  <div className="flex flex-wrap justify-end gap-2 pt-2">
                    <Button variant="outline" disabled={busy} onClick={closeDialog}><Translated text="Hủy" /></Button>
                    <Button disabled={busy || !ack} onClick={confirm}><Translated text="Xác nhận tác động" /></Button>
                  </div>
                </>
              )
            )}
          </div>
        </div>
      )}
    </div>
  );
}
