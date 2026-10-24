import type { MetricReview } from '@/lib/api';

export const passingReview: MetricReview = {
  status: 'pass', summary: 'Khớp yêu cầu và metadata.', issues: [], sources: [],
  revised: false, repair_count: 0, requirement: 'Doanh thu trước thuế của đơn hoàn tất',
};

export const reviewedSuggestionFields = {
  proposal_id: '00000000-0000-0000-0000-000000000001', review: passingReview,
};
