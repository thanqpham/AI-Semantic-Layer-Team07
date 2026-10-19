'use client';

import { useLanguage } from '@/context/LanguageContext';

export function Translated({ text, after }: { text: string; after?: boolean }) {
  const { translate } = useLanguage();
  return <>{translate(text)}{after ? ' ' : null}</>;
}
