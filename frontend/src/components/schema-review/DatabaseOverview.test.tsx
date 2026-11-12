import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { DatabaseOverview } from './DatabaseOverview';
import { getDatabaseOverviewApi, saveDatabaseOverviewApi } from '@/lib/api';
vi.mock('@/lib/api', () => ({ getDatabaseOverviewApi: vi.fn(), saveDatabaseOverviewApi: vi.fn(), generateDatabaseOverviewApi: vi.fn(), approveDatabaseOverviewApi: vi.fn() }));
const data = { description: 'Đã duyệt', draft_description: 'Nháp cũ', ai_description: null, revision: 1, reviewed_at: null, reviewed_by: null };
it('keeps the approved description visible while saving a new draft', async () => {
  vi.mocked(getDatabaseOverviewApi).mockResolvedValue(data);
  vi.mocked(saveDatabaseOverviewApi).mockResolvedValue({ ...data, description: 'Nháp mới', draft_description: null, revision: 2 });
  render(<DatabaseOverview dbId="7" canManage canApprove />);
  fireEvent.change(await screen.findByLabelText('Mô tả database'), { target: { value: 'Nháp mới' } });
  fireEvent.click(screen.getByRole('button', { name: 'Lưu mô tả' }));
  await waitFor(() => expect(saveDatabaseOverviewApi).toHaveBeenCalledWith('7', 'Nháp mới', 1));
  expect(screen.getByDisplayValue('Nháp mới')).toBeInTheDocument();
});
