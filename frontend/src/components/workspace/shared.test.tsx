import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { LanguageProvider } from '@/context/LanguageContext';
import { StatusPill } from '@/components/workspace/shared';

describe('StatusPill', () => {
  it('labels the rejected status in Vietnamese with a red dot color', () => {
    render(
      <LanguageProvider>
        <StatusPill status="rejected" />
      </LanguageProvider>,
    );

    expect(screen.getByText('Đã từ chối')).toBeInTheDocument();
    expect(screen.getByText('Đã từ chối').closest('span')!.innerHTML).toContain('bg-red-500');
  });
});
