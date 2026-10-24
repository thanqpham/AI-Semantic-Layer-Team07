import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

import { MetricsCatalogView } from './MetricsCatalogView';
import * as api from '@/lib/api';
import { passingReview } from '@/test/metricReviewFixture';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it('requires review of the edited request and a separate human approval click', async () => {
  const definition: api.MetricDefinition = { metric: { name: 'Doanh thu', base_entity: 'orders',
    formula: { function: 'SUM', expression: 'amount' }, filters: [], status: 'pending_approval', confidence: 'high', excluded_notes: '' } };
  const request: api.MetricRequest = { id: 7, db_id: 1, requester_id: 2, assistant_message_id: 'assistant', suggestion_index: 0,
    definition, status: 'pending', proposal_id: 'original', review: passingReview, created_at: '', updated_at: '' };
  vi.spyOn(api, 'listMetricRequestsApi').mockResolvedValue([request]);
  const review = vi.spyOn(api, 'reviewMetricProposalApi').mockResolvedValue({
    proposal_id: 'revised', definition, review: passingReview, yaml_preview: '',
  });
  const approve = vi.spyOn(api, 'approveMetricRequestApi').mockResolvedValue({ ...request, status: 'approved' });
  render(<MetricsCatalogView dbId={1} metrics={[]} canManageMetrics canApproveMetrics />);
  fireEvent.click(await screen.findByRole('button', { name: 'Chỉnh sửa definition' }));
  fireEvent.click(screen.getByRole('button', { name: 'Thẩm định definition đã sửa' }));
  await waitFor(() => expect(review).toHaveBeenCalledWith('1', 'original', definition));
  expect(approve).not.toHaveBeenCalled();
  fireEvent.click(await screen.findByRole('button', { name: 'Duyệt definition đã thẩm định' }));
  await waitFor(() => expect(approve).toHaveBeenCalledWith('1', 7, definition, undefined, 'revised'));
});
