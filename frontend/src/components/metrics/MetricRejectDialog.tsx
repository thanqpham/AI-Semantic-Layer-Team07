'use client';

import { useState } from 'react';
import { AlertTriangle, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';

interface MetricRejectDialogProps {
  metricId: number;
  metricName: string;
  /** Disables inputs while the request is in flight. */
  pending?: boolean;
  onReject: (metricId: number, reason: string) => Promise<void> | void;
  onClose: () => void;
  /** Copy overrides so the same dialog serves the delete-with-reason flow. */
  title?: string;
  hint?: string;
  reasonLabel?: string;
  confirmLabel?: string;
  blankReasonError?: string;
  fallbackError?: string;
}

/** Mandatory-reason confirmation for rejecting or deleting a metric. */
export function MetricRejectDialog({
  metricId,
  metricName,
  pending = false,
  onReject,
  onClose,
  title = 'Từ chối chỉ số',
  hint = 'Metric bị từ chối sẽ giải phóng tên và công thức để lưu lại bản mới.',
  reasonLabel = 'Lý do từ chối',
  confirmLabel = 'Xác nhận từ chối',
  blankReasonError = '⚠️ Vui lòng nhập lý do từ chối trước khi bấm Từ chối.',
  fallbackError = 'Không thể từ chối chỉ số. Vui lòng thử lại.',
}: MetricRejectDialogProps) {
  const { translate } = useLanguage();
  const [reason, setReason] = useState('');
  const [showReasonError, setShowReasonError] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleConfirm = async () => {
    const trimmed = reason.trim();
    if (!trimmed) {
      setShowReasonError(true);
      return;
    }
    try {
      await onReject(metricId, trimmed);
      onClose();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : fallbackError);
    }
  };

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !pending) onClose();
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            <Translated text={title} />
          </DialogTitle>
        </DialogHeader>

        <p className="text-xs text-muted-foreground">
          <Translated text={'Chỉ số:'} after />{' '}
          <span className="font-medium text-foreground">{metricName}</span>
        </p>
        <p className="text-[11px] text-muted-foreground">
          <Translated text={hint} />
        </p>

        <textarea
          aria-label={translate(reasonLabel)}
          value={reason}
          disabled={pending}
          onChange={(event) => {
            setReason(event.target.value);
            if (event.target.value.trim()) setShowReasonError(false);
          }}
          placeholder={translate(`${reasonLabel} (bắt buộc)`)}
          className={`min-h-24 w-full rounded-md border bg-background p-2 text-xs text-foreground ${
            showReasonError ? 'border-red-500 ring-1 ring-red-500' : 'border-border'
          }`}
        />
        {showReasonError && (
          <p className="text-[11px] font-medium text-red-500">
            <Translated text={blankReasonError} />
          </p>
        )}
        {errorMessage && (
          <p role="alert" className="flex items-start gap-1.5 rounded-md border border-red-500/30 bg-red-500/10 p-2 text-[11px] font-medium text-red-600 dark:text-red-400">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {errorMessage}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" disabled={pending} onClick={onClose} className="text-xs cursor-pointer">
            <Translated text={'Hủy'} />
          </Button>
          <Button
            variant="destructive"
            size="sm"
            disabled={pending}
            onClick={() => void handleConfirm()}
            className="gap-1.5 text-xs cursor-pointer"
          >
            <X className="h-3.5 w-3.5" />
            <Translated text={confirmLabel} />
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
