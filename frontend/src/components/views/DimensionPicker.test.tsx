import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { DimensionPicker } from '@/components/views/DimensionPicker';
import type { RecommendedDimensionItem } from '@/lib/api';

function dim(
  column_id: number,
  business_name: string,
  tier: RecommendedDimensionItem['tier'],
  table_business_name: string,
  join_path: string[] = [],
): RecommendedDimensionItem {
  return {
    column_id,
    column_name: business_name,
    business_name,
    table_id: column_id,
    table_name: table_business_name,
    table_business_name,
    tier,
    tier_label: tier,
    is_safe_join: true,
    requires_reaggregation: false,
    data_type: 'TEXT',
    join_path,
  };
}

const ITEMS = [
  dim(1, 'Channel', 'A', 'Orders'),
  dim(2, 'Payment Method', 'B', 'Payments', ['Orders', 'Payments']),
  dim(3, 'Channel', 'B', 'Order Facts', ['Orders', 'Order Facts']),
];

describe('DimensionPicker', () => {
  afterEach(() => cleanup());

  it('shows group headers, a duplicate badge, and hides farther copies until expanded', () => {
    render(<DimensionPicker items={ITEMS} selectedIds={new Set()} onToggle={() => {}} />);
    expect(screen.getByText('Cùng bảng với chỉ số')).toBeInTheDocument();
    expect(screen.getByText('Qua 1 liên kết')).toBeInTheDocument();
    expect(screen.getAllByRole('checkbox', { name: 'Channel' })).toHaveLength(1);
    expect(screen.getByText('+1')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Cùng tên, ở bảng khác/ }));
    expect(screen.getAllByRole('checkbox', { name: 'Channel' })).toHaveLength(2);
    expect(screen.getByText('Orders → Order Facts')).toBeInTheDocument();
  });

  it('keeps a selected farther copy visible and reports toggles by column id', () => {
    const onToggle = vi.fn();
    render(<DimensionPicker items={ITEMS} selectedIds={new Set([3])} onToggle={onToggle} />);
    expect(screen.getByText('Orders → Order Facts')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Payment Method' }).closest('button')!);
    expect(onToggle).toHaveBeenCalledWith(2);
  });

  it('renders search results as one flat list', () => {
    render(<DimensionPicker items={ITEMS} selectedIds={new Set()} onToggle={() => {}} searching />);
    expect(screen.queryByText('Cùng bảng với chỉ số')).not.toBeInTheDocument();
    expect(screen.getAllByRole('checkbox', { name: 'Channel' })).toHaveLength(2);
  });
});
