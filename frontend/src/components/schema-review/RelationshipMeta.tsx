'use client';

import { GitCommitHorizontal, Info } from 'lucide-react';
import type { ReactNode } from 'react';

import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';
import { CARDINALITY } from '@/lib/relationshipGraph';
import type { RelationshipItem } from '@/lib/relationshipReviewApi';

function Fact({ label, children }: { label: string; children: ReactNode }) {
  const { translate: t } = useLanguage();
  return (
    <div className="min-w-0 rounded-lg border border-border bg-background/60 px-3 py-2">
      <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">{t(label)}</dt>
      <dd className="mt-0.5 truncate font-mono text-xs">{children}</dd>
    </div>
  );
}

function formatTime(value?: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function Confidence({ value }: { value: number }) {
  const percent = Math.round((value <= 1 ? value * 100 : value));
  const color = percent >= 80 ? 'bg-emerald-500' : percent >= 50 ? 'bg-amber-500' : 'bg-red-500';
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground"><Translated text="Độ tin cậy:" /></span>
        <span className="font-mono font-semibold">{percent}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${Math.min(percent, 100)}%` }} />
      </div>
    </div>
  );
}

function Evidence({ evidence }: { evidence: Record<string, unknown> }) {
  const entries = Object.entries(evidence ?? {});
  if (!entries.length) return null;
  return (
    <div className="space-y-1.5">
      <p className="text-xs text-muted-foreground"><Translated text="Bằng chứng:" /></p>
      <dl className="divide-y divide-border rounded-lg border border-border text-xs">
        {entries.map(([key, value]) => (
          <div key={key} className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-2 px-3 py-1.5">
            <dt className="truncate font-mono text-muted-foreground">{key}</dt>
            <dd className="whitespace-pre-wrap break-words">{value !== null && typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** Read-only facts about a relationship: cardinality, source, reviewer, confidence, evidence. */
export function RelationshipMeta({ item }: { item: RelationshipItem }) {
  return (
    <div className="space-y-4 text-sm">
      <dl className="grid grid-cols-2 gap-2">
        <Fact label="Kiểu liên kết">{CARDINALITY[item.relationship_type]}</Fact>
        <Fact label="Nguồn">{item.source}</Fact>
        <Fact label="Người duyệt"><span>{item.reviewer_name ?? item.reviewed_by ?? '—'}</span></Fact>
        <Fact label="Thời điểm duyệt"><time>{formatTime(item.reviewed_at)}</time></Fact>
      </dl>
      {item.confidence != null && <Confidence value={item.confidence} />}
      {item.active_relationship_id && item.kind === 'candidate' && (
        <p className="flex items-start gap-2 rounded-lg border border-sky-500/30 bg-sky-500/10 p-2.5 text-xs text-sky-700 dark:text-sky-300">
          <GitCommitHorizontal className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span><Translated text="Bản sửa đang chờ; liên kết gốc vẫn hoạt động:" /> #{item.active_relationship_id}</span>
        </p>
      )}
      <Evidence evidence={item.evidence} />
      {item.errors.some((error) => error.code === 'INVALID_PAIR') && <pre className="whitespace-pre-wrap break-all rounded-lg bg-muted p-2 font-mono text-xs">{JSON.stringify(item.column_pairs)}</pre>}
      {item.unresolved_questions.map((question, index) => (
        <p key={index} className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 text-xs text-amber-700 dark:text-amber-300">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />{question}
        </p>
      ))}
    </div>
  );
}
