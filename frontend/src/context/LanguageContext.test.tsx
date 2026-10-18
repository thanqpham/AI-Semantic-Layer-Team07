import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { LanguageSwitch } from '@/components/ui/language-switch';
import { Translated } from '@/components/ui/translated';
import { LanguageProvider } from './LanguageContext';

describe('language selection', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => cleanup());

  it('switches text and document language, then restores the saved choice', async () => {
    const ui = (
      <LanguageProvider>
        <LanguageSwitch />
        <Translated text="Settings" />
      </LanguageProvider>
    );
    const { unmount } = render(ui);

    expect(screen.getByText('Cài đặt')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'en' } });
    expect(screen.getByText('Settings')).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('en');
    expect(window.localStorage.getItem('app_language')).toBe('en');

    unmount();
    render(ui);
    await waitFor(() => expect(screen.getByRole('combobox')).toHaveValue('en'));
    expect(screen.getByText('Settings')).toBeInTheDocument();
  });
});
