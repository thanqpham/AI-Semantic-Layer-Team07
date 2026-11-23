import { describe, expect, it } from 'vitest';

import type { RecommendedDimensionItem } from './api';
import { groupDimensions, joinPathLabel } from './dimensionGroups';

function dim(
  column_id: number,
  business_name: string,
  tier: RecommendedDimensionItem['tier'],
  table_business_name: string,
  join_path: string[] = [],
): RecommendedDimensionItem {
  return {
    column_id,
    column_name: business_name.toLowerCase(),
    business_name,
    table_id: column_id * 10,
    table_name: table_business_name.toLowerCase(),
    table_business_name,
    tier,
    tier_label: tier,
    is_safe_join: true,
    requires_reaggregation: false,
    data_type: 'TEXT',
    join_path,
  };
}

describe('groupDimensions', () => {
  it('groups by join distance in A, B, C order', () => {
    const result = groupDimensions([
      dim(3, 'Vùng', 'C', 'Vùng miền'),
      dim(1, 'Trạng thái', 'A', 'Đơn hàng'),
      dim(2, 'Thành phố', 'B', 'Khách hàng'),
    ]);
    expect(result.groups.map((g) => g.tier)).toEqual(['A', 'B', 'C']);
    expect(result.alternates).toEqual([]);
  });

  it('keeps the copy closest to the base table and moves same-name copies aside', () => {
    const farther = dim(2, 'Channel', 'B', 'Order Facts', ['Orders', 'Order Facts']);
    const closest = dim(1, 'channel ', 'A', 'Orders');
    const result = groupDimensions([farther, closest]);
    expect(result.groups).toHaveLength(1);
    expect(result.groups[0].items).toEqual([closest]);
    expect(result.alternates).toEqual([farther]);
    expect(result.alternateCount.get(1)).toBe(1);
  });
});

describe('joinPathLabel', () => {
  it('joins table names with arrows and is empty without a join', () => {
    expect(joinPathLabel(dim(1, 'A', 'B', 'X', ['Đơn hàng', 'Khách hàng']))).toBe('Đơn hàng → Khách hàng');
    expect(joinPathLabel(dim(1, 'A', 'A', 'X'))).toBe('');
  });
});
