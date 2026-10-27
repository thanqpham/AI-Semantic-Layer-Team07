import { describe, expect, it, vi } from 'vitest';
import { semanticRequest } from './api';
import { listRelationships, saveRelationship, decideRelationship, getRelationshipImpact } from './relationshipReviewApi';
vi.mock('./api', () => ({ semanticRequest: vi.fn() }));
describe('relationship review client', () => {
  it('uses the shared authenticated client, qualified filters and revision/impact payload', async () => {
    vi.mocked(semanticRequest).mockResolvedValue({});
    await listRelationships('7', 'pending_review', 'sales.orders.customer_id');
    expect(semanticRequest).toHaveBeenLastCalledWith('/api/v1/semantic/7/relationships?status=pending_review&search=sales.orders.customer_id');
    const draft = { from_entity_id: 1, to_entity_id: 2, column_pairs: [{ from_column_id: 10, to_column_id: 20 }], relationship_type: 'many_to_one' as const, expected_revision: 3 };
    await saveRelationship('7', draft, { kind: 'active', id: 4 });
    expect(semanticRequest).toHaveBeenLastCalledWith('/api/v1/semantic/7/relationships/4/edit', { method: 'POST', body: JSON.stringify(draft) });
    await getRelationshipImpact('7', { kind: 'candidate', id: 8 }, 'approve');
    expect(semanticRequest).toHaveBeenLastCalledWith('/api/v1/semantic/7/relationships/8/impact?kind=candidate&action=approve');
    await decideRelationship('7', {kind:'candidate', id:8}, 'approve', { expected_revision: 3, impact_token: 'token', acknowledge_impact: true });
    expect(semanticRequest).toHaveBeenLastCalledWith('/api/v1/semantic/7/relationships/candidates/8/approve', expect.objectContaining({method:'POST'}));
  });
});
