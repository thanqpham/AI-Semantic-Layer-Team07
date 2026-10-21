import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

import { SchemaReviewView } from './SchemaReviewView';

vi.mock('@/lib/api', () => ({
  getSchemaReviewApi: vi.fn(),
  approveSchemaReviewApi: vi.fn(),
  updateColumnReviewApi: vi.fn(),
  updateTableReviewApi: vi.fn(),
}));

afterEach(cleanup);

it('keeps the full-width header outside the scrollable review content without shrinking', () => {
  const { container } = render(<SchemaReviewView />);
  const header = screen.getByRole('banner');
  const view = container.firstElementChild;
  const content = header.nextElementSibling;

  expect(view).toHaveClass('h-full', 'w-full', 'overflow-hidden');
  expect(header).toHaveClass('shrink-0');
  expect(content).toHaveClass('min-h-0', 'flex-1', 'overflow-y-auto');
});
