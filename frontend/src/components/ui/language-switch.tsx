'use client';

import { useLanguage } from '@/context/LanguageContext';

export function LanguageSwitch({ className = '' }: { className?: string }) {
  const { language, setLanguage } = useLanguage();

  return (
    <select
      aria-label={language === 'vi' ? 'Ngôn ngữ' : 'Language'}
      value={language}
      onChange={(event) => setLanguage(event.target.value === 'en' ? 'en' : 'vi')}
      className={`rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground ${className}`}
    >
      <option value="vi">Tiếng Việt</option>
      <option value="en">English</option>
    </select>
  );
}
