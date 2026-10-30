'use client';

import { Check, Code2, Copy, Edit3, MessageSquareWarning, RefreshCw, Save } from 'lucide-react';
import React, { useState } from 'react';

import { Button } from '@/components/ui/button';
import { MetricSuggestion, SuggestionLifecycle } from '@/lib/api';
import { MetricReviewPanel } from '@/components/metrics/MetricReviewPanel';
import { cn } from '@/lib/utils';
import { StatusPill } from '@/components/workspace/shared';
import { ConflictWarningStrip } from '@/components/studio/DedupeWarnings';
import { getMetricUsedColumns } from '@/lib/metrics';
import { Translated } from '@/components/ui/translated';

export function SuggestionCard({
  suggestion,
  embedded = false,
  lifecycle,
  catalogNameConflict,
  onSave,
  onEdit,
  onRefine,
  onOpenCatalog,
  onRename,
  onUseExisting,
  action,
  isSubmitted,
  isApproved,
  onSubmitRequest,
}: {
  suggestion: MetricSuggestion;
  embedded?: boolean;
  lifecycle?: SuggestionLifecycle | null;
  catalogNameConflict: boolean;
  onSave: () => Promise<void>;
  onEdit?: () => void;
  onRefine?: () => void;
  onOpenCatalog?: () => void;
  onRename?: () => void;
  onUseExisting?: () => void;
  action?: 'save_metric' | 'submit_metric_request' | null;
  isSubmitted?: boolean;
  isApproved?: boolean;
  onSubmitRequest?: () => Promise<void>;
}) {
  const [showYaml, setShowYaml] = useState(false);
  const [showRejectReason, setShowRejectReason] = useState(false);
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);

  /** Saved = the proposal became a metric; rejected = it was rejected (metric freed). */
  const isSaved = lifecycle?.metric_id != null;
  const isRejected = lifecycle?.metric_id == null && lifecycle?.rejection_reason != null;
  /**
   * A rejected proposal is released server-side, so its annotation carries
   * metric_status: null — the pill status must come from isRejected, not the field.
   */
  const pillStatus = isRejected ? 'rejected' : isSaved ? lifecycle?.metric_status ?? null : null;

  const def = suggestion.definition.metric;
  const yamlContent = suggestion.yaml_preview || JSON.stringify(suggestion.definition, null, 2);
  const usedColumns = getMetricUsedColumns(suggestion.definition);
  const ratio = def.formula.ratio;
  const filters = [
    ...(def.filters || []).map((filter) => ({ ...filter, scope: '' })),
    ...(ratio?.numerator.filters || []).map((filter) => ({ ...filter, scope: 'Tử số' })),
    ...(ratio?.denominator.filters || []).map((filter) => ({ ...filter, scope: 'Mẫu số' })),
  ];

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave();
    } catch {
      // Handled by parent error notification
    } finally {
      setSaving(false);
    }
  };

  const handleSubmitRequest = async () => {
    setSaving(true);
    try {
      await onSubmitRequest?.();
    } catch {
      // Handled by parent error notification
    } finally {
      setSaving(false);
    }
  };

  const copyYaml = () => {
    void navigator.clipboard?.writeText(yamlContent);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className={cn('w-full overflow-hidden', !embedded && 'rounded-lg border border-border bg-card shadow-xs')}>
      {/* ⚠️ Conflict clarify strip — same name as a saved metric, different formula */}
      {suggestion.conflict && (
        <div className="border-b border-border bg-secondary/20 p-3">
          <ConflictWarningStrip
            conflict={suggestion.conflict}
            onRename={() => onRename?.()}
            onUseExisting={() => onUseExisting?.()}
          />
        </div>
      )}
      {catalogNameConflict && !suggestion.conflict && !isSaved && !isRejected && (
        <div role="status" className="border-b border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
          Tên này đã có trong catalog. Kiểm tra metric hiện tại trước khi lưu biến thể.
        </div>
      )}

      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-secondary/30 px-4 py-2.5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-foreground text-sm">{def.name}</h3>
            {pillStatus && <StatusPill status={pillStatus} />}
          </div>
        </div>

        <div className="flex items-center gap-1">
          {isRejected && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 gap-1.5 text-xs text-muted-foreground hover:text-foreground cursor-pointer"
              onClick={() => setShowRejectReason(!showRejectReason)}
            >
              <MessageSquareWarning className="h-3.5 w-3.5" />
              <Translated text={"Lý do từ chối"} />
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1.5 text-xs text-muted-foreground hover:text-foreground cursor-pointer"
            onClick={() => setShowYaml(!showYaml)}
          >
            <Code2 className="h-3.5 w-3.5" />
            <Translated text={showYaml ? 'Ẩn mã YAML' : 'Hiển thị mã YAML'} />
          </Button>
          {onRefine && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 gap-1.5 text-xs text-muted-foreground hover:text-foreground cursor-pointer"
              onClick={onRefine}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <Translated text={"Nhờ AI tinh chỉnh"} />
            </Button>
          )}
          {onEdit && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 gap-1.5 text-xs text-muted-foreground hover:text-foreground cursor-pointer"
              onClick={onEdit}
            >
              <Edit3 className="h-3.5 w-3.5" />
              <Translated text={"Chỉnh sửa thủ công"} />
            </Button>
          )}
        </div>
      </div>

      {/* 🚫 Rejection reason panel — plain text from the Data Lead's reject decision */}
      {isRejected && showRejectReason && (
        <div className="border-b border-border bg-secondary/20 px-4 py-3 text-xs">
          <span className="font-mono text-[10px] uppercase font-semibold text-muted-foreground">
            <Translated text={"Lý do từ chối"} />
          </span>
          <p className="mt-1 break-words text-foreground">{lifecycle?.rejection_reason}</p>
        </div>
      )}

      {/* Visual Properties */}
      <div className="space-y-2 p-4 text-xs">
        {suggestion.review && <MetricReviewPanel review={suggestion.review} definition={suggestion.definition} />}
        <div data-testid="metric-properties-grid" className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div className="min-w-0 rounded-md border border-border bg-secondary/30 p-2.5">
            <span className="font-mono text-[10px] uppercase text-muted-foreground">
              <Translated text={"Công thức tính"} />
            </span>
            <p className="mt-0.5 break-words font-mono text-xs font-medium text-foreground">
              <span className="text-primary font-bold">{def.formula.function}</span>(
              <span>{def.formula.expression}</span>)
            </p>
          </div>
          <div className="min-w-0 rounded-md border border-border bg-secondary/30 p-2.5">
            <span className="font-mono text-[10px] uppercase text-muted-foreground">
              <Translated text={"Dựa vào bảng gốc"} />
            </span>
            <p className="mt-1 break-words font-mono text-xs font-medium text-foreground">
              {def.base_entity}
            </p>
          </div>
          <div className="min-w-0 rounded-md border border-border bg-secondary/30 p-2.5">
            <span className="font-mono text-[10px] uppercase text-muted-foreground">
              <Translated text={"Cột dữ liệu sử dụng"} />
            </span>
            <div className="mt-1 flex flex-wrap gap-1">
              {usedColumns.length ? usedColumns.map((column) => (
                <code key={column} className="rounded bg-secondary px-1.5 py-0.5 font-mono text-[11px] text-foreground">
                  {column}
                </code>
              )) : <span className="text-muted-foreground">Không có cột dữ liệu</span>}
            </div>
          </div>
          <div className="min-w-0 rounded-md border border-border bg-secondary/30 p-2.5">
            <span className="font-mono text-[10px] uppercase text-muted-foreground">
              <Translated text={"Bộ lọc điều kiện"} />
            </span>
            <p className="mt-1 break-words text-xs text-muted-foreground">
              {filters.length
                ? filters.map((filter) => {
                  const scope = filter.scope ? `${filter.scope}: ` : '';
                  const value = Array.isArray(filter.value)
                    ? filter.value.join(', ')
                    : String(filter.value ?? '');
                  return `${scope}${filter.field} ${filter.operator}${value ? ` ${value}` : ''}`;
                }).join(' · ')
                : 'Không có bộ lọc'}
            </p>
          </div>
        </div>
      </div>

      {(def.excluded_notes || showYaml) && (
        <div className="space-y-2 px-4 pb-4 text-xs">
          {def.excluded_notes && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-2.5">
              <span className="font-mono text-[10px] uppercase text-amber-700 dark:text-amber-300 font-semibold">
                <Translated text={"Giả định cần xác nhận"} />
              </span>
              <p className="mt-0.5 text-xs text-amber-800 dark:text-amber-200">
                {def.excluded_notes}
              </p>
            </div>
          )}

          {showYaml && (
            <div className="overflow-hidden rounded-md border border-border bg-secondary/20">
              <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
                <span className="font-mono text-[11px] text-muted-foreground"><Translated text={"YAML preview"} /></span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 gap-1 text-[11px] cursor-pointer"
                  onClick={copyYaml}
                >
                  {copied ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
                  <Translated text={copied ? 'Đã copy' : 'Copy YAML'} />
                </Button>
              </div>
              <pre className="overflow-x-auto p-3 font-mono text-xs leading-relaxed text-foreground">
                {yamlContent}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between gap-2 border-t border-border bg-secondary/20 px-4 py-2.5">
        <span className="font-mono text-[11px] text-muted-foreground">
          <Translated text={suggestion.conflict
            ? 'Xử lý cảnh báo trùng tên trước khi lưu'
            : 'Chỉ khả dụng để truy vấn sau khi được phê duyệt'} />
        </span>

        {/* ⛔ No Save/Submit while the conflict strip is unresolved — user must clarify first */}
        {!suggestion.conflict &&
          (action === 'submit_metric_request' ? (
            isApproved || isSaved ? (
              <Button
                size="sm"
                variant="secondary"
                className="h-8 gap-1.5 text-xs text-emerald-600 dark:text-emerald-400"
                disabled
              >
                <Check className="h-3.5 w-3.5" />
                <Translated text={"Đã được Data Lead duyệt"} />
              </Button>
            ) : isSubmitted ? (
              <Button
                size="sm"
                variant="secondary"
                className="h-8 gap-1.5 text-xs text-emerald-600 dark:text-emerald-400"
                disabled
              >
                <Check className="h-3.5 w-3.5" />
                <Translated text={"Đã gửi cho Data Lead"} />
              </Button>
            ) : (
              <Button
                size="sm"
                className="h-8 gap-1.5 text-xs cursor-pointer"
                onClick={() => void handleSubmitRequest()}
                disabled={saving || !suggestion.proposal_id || suggestion.review?.status !== 'pass'}
              >
                <Save className="h-3.5 w-3.5" />
                <Translated text={saving ? 'Đang gửi...' : 'Gửi Data Lead xem xét'} />
              </Button>
            )
          ) : isSaved ? (
            <Button
              size="sm"
              variant="secondary"
              className="h-8 gap-1.5 text-xs text-emerald-600 dark:text-emerald-400 cursor-pointer"
              onClick={onOpenCatalog}
            >
              <Check className="h-3.5 w-3.5" />
              <Translated text={"Đã lưu — mở catalog"} />
            </Button>
          ) : (
            <Button
              size="sm"
              className="h-8 gap-1.5 text-xs cursor-pointer"
              onClick={() => void handleSave()}
              disabled={saving || !suggestion.proposal_id || suggestion.review?.status !== 'pass'}
            >
              <Save className="h-3.5 w-3.5" />
              <Translated text={saving ? 'Đang lưu...' : 'Lưu vào Semantic Layer'} />
            </Button>
          ))}
      </div>
    </div>
  );
}
