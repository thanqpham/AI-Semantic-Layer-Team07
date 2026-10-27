'use client';

import { LayoutList, Loader2, Network, Plus, Search, Sparkles } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';
import { STATUS_ORDER, STATUS_STYLE } from '@/lib/relationshipGraph';
import { cn } from '@/lib/utils';
import { statusTone } from './RelationshipStatusBadge';

export type RelationshipView = 'diagram' | 'list';

interface Props {
  search: string;
  onSearch: (value: string) => void;
  status: string;
  onStatus: (value: string) => void;
  view: RelationshipView;
  onView: (value: RelationshipView) => void;
  pending: number;
  canManage: boolean;
  busy: boolean;
  onSuggest: () => void;
  onAdd: () => void;
}

const pill = 'inline-flex h-7 items-center gap-1.5 rounded-full px-2.5 text-[11px] font-medium transition-colors';

function StatusFilter({ status, onStatus }: Pick<Props, 'status' | 'onStatus'>) {
  const { translate: t } = useLanguage();
  return (
    <select
      aria-label={t('Trạng thái liên kết')}
      className="h-8 max-w-full rounded-lg border border-border bg-card px-2.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-sky-500/40"
      value={status}
      onChange={(e) => onStatus(e.target.value)}
    >
      <option value="">{t('Tất cả trạng thái')}</option>
      {STATUS_ORDER.map((s) => (
        <option key={s} value={s}>
          {t(STATUS_STYLE[s].label)}
        </option>
      ))}
    </select>
  );
}

function ViewToggle({ view, onView }: Pick<Props, 'view' | 'onView'>) {
  const { translate: t } = useLanguage();
  const options = [
    { value: 'diagram' as const, label: 'Sơ đồ', Icon: Network },
    { value: 'list' as const, label: 'Danh sách', Icon: LayoutList },
  ];
  return (
    <div role="group" aria-label={t('Chế độ hiển thị')} className="flex items-center gap-0.5 rounded-lg border border-border bg-card p-0.5">
      {options.map(({ value, label, Icon }) => (
        <button
          key={value}
          type="button"
          aria-pressed={view === value}
          onClick={() => onView(value)}
          className={cn('inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[11px] font-medium transition-colors', view === value ? 'bg-muted text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')}
        >
          <Icon className="h-3.5 w-3.5" aria-hidden="true" />
          {t(label)}
        </button>
      ))}
    </div>
  );
}

/** Search, status pills, diagram/list toggle and manage actions for the relationship tab. */
export function RelationshipToolbar(props: Props) {
  const { search, onSearch, pending, canManage, busy, onSuggest, onAdd } = props;
  const { translate: t } = useLanguage();
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1 basis-56">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input aria-label={t('Tìm liên kết')} placeholder={t('Tìm bảng hoặc cột đầy đủ')} className="h-8 pl-8 text-xs" value={search} onChange={(event) => onSearch(event.target.value)} />
        </div>
        <ViewToggle view={props.view} onView={props.onView} />
        {canManage && (
          <Button size="sm" disabled={busy} onClick={onSuggest} className="h-8 gap-1.5 text-xs">
            {busy ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <Sparkles className="size-3.5" aria-hidden="true" />
            )}
            <Translated text={busy ? 'Đang phân tích…' : 'AI đề xuất'} />
          </Button>
        )}
        {canManage && <Button size="sm" variant="outline" disabled={busy} onClick={onAdd} className="h-8 gap-1.5 text-xs"><Plus className="size-3.5" aria-hidden="true" /><Translated text="Thêm liên kết" /></Button>}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <StatusFilter status={props.status} onStatus={props.onStatus} />
        <span className={cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px]', statusTone('pending_review').pill)}>
          <span className="font-semibold">{pending}</span> <Translated text="liên kết chờ review" />
        </span>
      </div>
    </div>
  );
}
