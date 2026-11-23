import type { RecommendedDimensionItem } from './api';

export type DimensionTier = RecommendedDimensionItem['tier'];

export interface DimensionGroup {
  tier: DimensionTier;
  items: RecommendedDimensionItem[];
}

export interface GroupedDimensions {
  groups: DimensionGroup[];
  alternates: RecommendedDimensionItem[];
  alternateCount: Map<number, number>;
}

const TIER_ORDER: DimensionTier[] = ['A', 'B', 'C', 'D'];

export const TIER_TITLES: Record<DimensionTier, string> = {
  A: 'Cùng bảng với chỉ số',
  B: 'Qua 1 liên kết',
  C: 'Qua 2 liên kết',
  D: 'Chi tiết dòng (1:N)',
};

function nameKey(item: RecommendedDimensionItem): string {
  return (item.business_name || item.column_name).trim().toLocaleLowerCase('vi');
}

/**
 * Group dimensions by join distance and keep one entry per business name.
 * The copy closest to the metric's base table stays in its group; farther copies
 * with the same name move to `alternates` so users see one obvious choice first.
 */
export function groupDimensions(items: RecommendedDimensionItem[]): GroupedDimensions {
  const ordered = [...items].sort((a, b) => TIER_ORDER.indexOf(a.tier) - TIER_ORDER.indexOf(b.tier));
  const primaries = new Map<string, RecommendedDimensionItem>();
  const alternates: RecommendedDimensionItem[] = [];
  const alternateCount = new Map<number, number>();
  for (const item of ordered) {
    const primary = primaries.get(nameKey(item));
    if (!primary) {
      primaries.set(nameKey(item), item);
      continue;
    }
    alternates.push(item);
    alternateCount.set(primary.column_id, (alternateCount.get(primary.column_id) ?? 0) + 1);
  }
  const kept = [...primaries.values()];
  const groups = TIER_ORDER.map((tier) => ({ tier, items: kept.filter((item) => item.tier === tier) })).filter(
    (group) => group.items.length > 0,
  );
  return { groups, alternates, alternateCount };
}

/** Human-readable join route, e.g. "Đơn hàng → Khách hàng"; empty when no join is needed. */
export function joinPathLabel(item: RecommendedDimensionItem): string {
  return (item.join_path ?? []).join(' → ');
}
