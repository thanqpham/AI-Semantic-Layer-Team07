"use client";

import { useMemo, useState, type ReactNode } from "react";

import type { MetricRecord, SemanticCatalog } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Translated } from "@/components/ui/translated";
import {
  groupMetrics,
  METRIC_KIND_LABELS,
  metricKind,
  type MetricKind,
} from "./catalogGrouping";

export interface CatalogGroupedListProps {
  metrics: MetricRecord[];
  catalog: SemanticCatalog | null;
  renderCard: (metric: MetricRecord) => ReactNode;
}

const ALL = "__all__";

/** Metrics grouped by business entity, with kind chips to narrow the list. */
export function CatalogGroupedList({
  metrics,
  catalog,
  renderCard,
}: CatalogGroupedListProps) {
  const [kind, setKind] = useState<MetricKind | typeof ALL>(ALL);
  const byKind = useMemo(
    () =>
      kind === ALL ? metrics : metrics.filter((m) => metricKind(m) === kind),
    [kind, metrics],
  );
  const groups = useMemo(
    () => groupMetrics(byKind, catalog),
    [byKind, catalog],
  );
  const kinds = (Object.keys(METRIC_KIND_LABELS) as MetricKind[]).filter((k) =>
    metrics.some((m) => metricKind(m) === k),
  );

  return (
    <div className="flex min-w-0 flex-col gap-5">
      {kinds.length > 1 && (
        <div
          role="group"
          aria-label="Loại chỉ số"
          className="flex flex-wrap gap-1.5"
        >
          <KindChip
            label="Tất cả loại"
            active={kind === ALL}
            onClick={() => setKind(ALL)}
          />
          {kinds.map((k) => (
            <KindChip
              key={k}
              label={METRIC_KIND_LABELS[k]}
              active={kind === k}
              onClick={() => setKind(k)}
            />
          ))}
        </div>
      )}
      {groups.map((group) => (
        <section
          key={group.key}
          aria-label={group.label}
          className="flex min-w-0 flex-col gap-2"
        >
          <h3 className="text-xs font-semibold text-muted-foreground">
            <span className="text-sm text-foreground">{group.label}</span> ·{" "}
            {group.metrics.length} <Translated text="chỉ số" />
          </h3>
          <div className="min-w-0 divide-y divide-border overflow-visible rounded-lg border border-border bg-card">
            {group.metrics.map(renderCard)}
          </div>
        </section>
      ))}
    </div>
  );
}

function KindChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "cursor-pointer rounded-full border px-3 py-1 text-xs transition-colors",
        active
          ? "border-primary bg-primary/10 font-semibold text-primary"
          : "border-border text-muted-foreground hover:text-foreground",
      )}
    >
      <Translated text={label} />
    </button>
  );
}
