import { useId, useState } from 'react';
import { ChevronRight, MoreHorizontal, Check, Edit2, History, RotateCcw, ShieldAlert, Sparkles, Trash2, User, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { MetricRecord } from '@/lib/api';
import { YamlCodeViewer } from '@/components/studio/YamlCodeViewer';
import { StatusPill } from '@/components/workspace/shared';
import { formatMetricFormula, metricName, renderMetricYaml } from '@/lib/metrics';
import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';

interface MetricCardProps {
  metric: MetricRecord;
  selected?: boolean;
  onToggleSelect?: (id: number) => void;
  onEdit?: (item: MetricRecord) => void;
  onDelete?: (id: number) => Promise<void> | void;
  onPermanentDelete?: (id: number) => Promise<void> | void;
  onHistory: (id: number) => Promise<void>;
  onApprove?: (id: number) => Promise<void> | void;
  /** Opens the reject dialog — the mandatory reason is collected there, not here. */
  onReject?: (id: number) => void;
  onRestore?: (id: number) => Promise<void> | void;
}

export function MetricCard({
  metric,
  selected = false,
  onToggleSelect,
  onEdit,
  onDelete,
  onPermanentDelete,
  onHistory,
  onApprove,
  onReject,
  onRestore,
}: MetricCardProps) {
  const { translate, t } = useLanguage();
  const definition = metric.definition;
  const isDeleted = Boolean(metric.is_deleted);
  const isRejected = metric.status === 'rejected';
  const isPending = metric.status !== 'approved' && !isRejected;

  const [expanded, setExpanded] = useState(false);
  const [tab, setTab] = useState<'definition' | 'yaml'>('definition');
  const detailId = useId();
  const formula = definition
    ? formatMetricFormula(definition)
    : t('No definition', 'Chưa có định nghĩa');

  return (
    <article className={`@container min-w-0 transition-colors first:rounded-t-lg last:rounded-b-lg ${selected ? 'bg-primary/5' : 'bg-card'}`}>
      <div className="flex items-start gap-2 px-3 py-3 sm:gap-3 sm:px-4 hover:bg-secondary/40">
        {onToggleSelect && (
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelect(metric.metric_id)}
            className="mt-1.5 h-4 w-4 shrink-0 cursor-pointer accent-primary"
            aria-label={`Select ${metricName(metric)}`}
          />
        )}
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={detailId}
          onClick={() => setExpanded(!expanded)}
          className="grid min-w-0 flex-1 cursor-pointer grid-cols-[16px_minmax(0,1fr)] items-start gap-x-2 gap-y-2 rounded-sm text-left focus-visible:outline-2 focus-visible:outline-primary @3xl:grid-cols-[16px_minmax(0,1fr)_minmax(0,0.7fr)_140px] @3xl:gap-x-4"
        >
          <ChevronRight aria-hidden="true" className={`mt-1 h-4 w-4 text-muted-foreground transition-transform ${expanded ? 'rotate-90' : ''}`} />
          <span className="min-w-0">
            <span className="block break-words text-sm font-medium text-foreground [overflow-wrap:anywhere]">{metricName(metric)}</span>
            <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
              {definition?.metric.name !== metricName(metric) && <span className="break-all font-mono">{definition?.metric.name}</span>}
              {definition && <span className="break-all">· {definition.metric.base_entity}</span>}
              <span>· v{metric.version || 1}</span>
              <span className="inline-flex items-center gap-1" title={translate(metric.source === 'manual' ? 'Tạo thủ công' : 'AI đề xuất')}>
                {metric.source === 'manual' ? <User className="h-3 w-3" /> : <Sparkles className="h-3 w-3" />}
                {metric.source === 'manual' ? <Translated text="Thủ công" /> : 'AI'}
              </span>
            </span>
          </span>
          <code className="col-start-2 line-clamp-2 min-w-0 break-all font-mono text-xs leading-5 text-muted-foreground @3xl:col-start-auto" title={formula}>{formula}</code>
          <span className="col-start-2 flex flex-wrap items-center gap-1.5 @3xl:col-start-auto">
            {isDeleted ? (
              <span className="inline-flex items-center rounded-full bg-destructive/15 px-2 py-0.5 text-[11px] font-medium text-destructive border border-destructive/30">
                <Translated text={"Đã xóa"} />
              </span>
            ) : (
              <>
                {metric.has_pending_version && (
                  <span className="inline-flex items-center rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] font-medium text-amber-500 border border-amber-500/30">
                    ⚡ v{metric.pending_version_number || (metric.version || 1) + 1} <Translated text={"chờ duyệt"} /></span>
                )}
                <StatusPill status={metric.status} />
              </>
            )}
          </span>
        </button>
        <div className="flex shrink-0 flex-col items-end justify-end gap-1 sm:w-28 sm:flex-row sm:items-center">
          {!isDeleted && isPending && onApprove && (
            <Button
              size="sm"
              className="h-8 justify-start gap-1.5 text-xs cursor-pointer"
              onClick={() => {
                void onApprove(metric.metric_id);
              }}
              title={translate("Phê duyệt chỉ số này")}
              aria-label={translate('Duyệt chỉ số này')}
            >
              <Check className="h-3.5 w-3.5" />
              {t('Approve', 'Duyệt')}
            </Button>
          )}

          {!isDeleted && isPending && onReject && (
            <Button
              size="sm"
              variant="outline"
              className="h-8 justify-start gap-1.5 text-xs text-red-600 hover:bg-red-50 hover:text-red-600 dark:text-red-400 dark:hover:bg-red-950/30 cursor-pointer"
              onClick={() => {
                onReject(metric.metric_id);
              }}
              title={translate("Từ chối chỉ số này")}
              aria-label={translate('Từ chối chỉ số này')}
            >
              <X className="h-3.5 w-3.5" />
              {t('Reject', 'Từ chối')}
            </Button>
          )}

          <details className="relative" onBlur={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false;
          }} onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.currentTarget.open = false;
              event.currentTarget.querySelector('summary')?.focus();
            }
          }}>
            <summary
              aria-label={`${t('Actions for', 'Thao tác với')} ${metricName(metric)}`}
              className="flex h-8 w-8 cursor-pointer list-none items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary [&::-webkit-details-marker]:hidden"
            >
              <MoreHorizontal className="h-4 w-4" />
            </summary>
            <div className="absolute right-0 top-10 z-20 w-64 max-w-[80vw] rounded-lg border border-border bg-card p-2 shadow-lg" onClick={(event) => {
              if ((event.target as HTMLElement).closest('button')) {
                event.currentTarget.closest('details')?.removeAttribute('open');
              }
            }}>
              <div className="flex flex-col gap-2">
                <div className="flex flex-col items-stretch gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-8 justify-start gap-2 text-xs text-muted-foreground hover:text-foreground cursor-pointer"
                    onClick={() => {
                      void onHistory(metric.metric_id);
                    }}
                    title={translate("Xem lịch sử phiên bản")}
                  >
                    <History className="h-3.5 w-3.5" />
                    <span>{t('Version history', 'Lịch sử phiên bản')}</span>
                  </Button>

                  {!isDeleted && onEdit && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 justify-start gap-1 text-xs text-muted-foreground hover:text-foreground cursor-pointer"
                      onClick={() => {
                        onEdit(metric);
                      }}
                    >
                      <Edit2 className="h-3 w-3" />
                      <Translated text={definition ? 'Chỉnh sửa' : 'Chuẩn hóa'} />
                    </Button>
                  )}

                  {!isDeleted && onDelete && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 justify-start gap-2 text-xs text-muted-foreground hover:text-destructive cursor-pointer"
                      onClick={() => {
                        if (window.confirm(`Chuyển metric "${metricName(metric)}" vào Thùng rác?`)) {
                          void onDelete(metric.metric_id);
                        }
                      }}
                      title={translate("Chuyển vào Thùng rác")}
                      aria-label={`Delete ${metricName(metric)}`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      <span>{t('Move to trash', 'Chuyển vào Thùng rác')}</span>
                    </Button>
                  )}
                </div>

                {isDeleted && (
                  <div className="flex flex-col items-stretch gap-1">
                    {onPermanentDelete && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-8 justify-start gap-1.5 text-xs text-destructive hover:text-destructive hover:bg-destructive/10 cursor-pointer"
                        onClick={() => {
                          if (window.confirm(`Bạn có chắc chắn muốn xóa vĩnh viễn metric "${metricName(metric)}"? Hành động này không thể hoàn tác!`)) {
                            void onPermanentDelete(metric.metric_id);
                          }
                        }}
                        title={translate("Xóa vĩnh viễn khỏi hệ thống")}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        <Translated text={"Xóa vĩnh viễn"} />
                      </Button>
                    )}
                    {onRestore && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-8 justify-start gap-1.5 text-xs text-primary hover:text-primary cursor-pointer"
                        onClick={() => {
                          void onRestore(metric.metric_id);
                        }}
                        title={translate("Khôi phục metric")}
                      >
                        <RotateCcw className="h-3.5 w-3.5" />
                        <Translated text={"Khôi phục"} />
                      </Button>
                    )}
                  </div>
                )}
              </div>
            </div>
          </details>
        </div>
      </div>
      {expanded && (
        <div id={detailId} className="min-w-0 border-t border-border/60 bg-secondary/20 px-4 py-4 sm:pl-10">
          {definition ? (
            <>
              <div role="group" aria-label={t('Metric details', 'Chi tiết chỉ số')} className="mb-4 flex gap-1 border-b border-border">
                {(['definition', 'yaml'] as const).map((value) => (
                  <button key={value} type="button" aria-pressed={tab === value} aria-controls={`${detailId}-panel`}
                    onClick={() => setTab(value)}
                    className={`cursor-pointer border-b-2 px-3 py-2 text-xs font-medium focus-visible:outline-2 focus-visible:outline-primary ${tab === value ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}`}>
                    {value === 'yaml' ? 'YAML' : t('Definition', 'Định nghĩa')}
                  </button>
                ))}
              </div>
              <div id={`${detailId}-panel`}>
                {tab === 'yaml' ? <YamlCodeViewer yaml={renderMetricYaml(definition)} /> : (
                  <dl className="grid min-w-0 grid-cols-1 gap-x-6 gap-y-3 text-xs leading-6 sm:grid-cols-[140px_minmax(0,1fr)]">
                    <dt className="text-muted-foreground"><Translated text="Công thức" /></dt>
                    <dd className="min-w-0 whitespace-pre-wrap break-all font-mono text-foreground">{formula}</dd>
                    <dt className="text-muted-foreground">{t('Source table', 'Bảng nguồn')}</dt>
                    <dd className="break-all font-mono">{definition.metric.base_entity}</dd>
                    {metric.description && <><dt className="text-muted-foreground"><Translated text="Mô tả nghiệp vụ" /></dt><dd className="whitespace-pre-wrap [overflow-wrap:anywhere]">{metric.description}</dd></>}
                    {definition.metric.filters.length > 0 && <>
                      <dt className="text-muted-foreground"><Translated text="Bộ lọc cố định" /></dt>
                      <dd className="min-w-0 space-y-1 font-mono">{definition.metric.filters.map((filter, index) => (
                        <div key={index} className="whitespace-pre-wrap break-all">{filter.field} {filter.operator} {JSON.stringify(filter.value)}</div>
                      ))}</dd>
                    </>}
                    {definition.metric.excluded_notes && <><dt className="text-muted-foreground"><Translated text="Ghi chú loại trừ" /></dt><dd className="whitespace-pre-wrap [overflow-wrap:anywhere]">{definition.metric.excluded_notes}</dd></>}
                  </dl>
                )}
              </div>
            </>
          ) : (
            <p className="text-xs text-amber-600 dark:text-amber-400"><ShieldAlert className="mr-1 inline h-4 w-4" /><Translated text="Metric legacy chưa có canonical definition." /></p>
          )}
        </div>
      )}
    </article>
  );
}
