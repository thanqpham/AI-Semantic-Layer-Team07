'use client';

import { createContext, useContext, useEffect, useSyncExternalStore } from 'react';
import catalog from '@/i18n/catalog.json';

export type Language = 'vi' | 'en';

const LanguageContext = createContext<{
  language: Language;
  setLanguage: (language: Language) => void;
}>({ language: 'vi', setLanguage: () => {} });

function readLanguage(): Language {
  const saved = window.localStorage.getItem('app_language');
  return saved === 'en' ? 'en' : 'vi';
}

function subscribe(listener: () => void) {
  window.addEventListener('storage', listener);
  window.addEventListener('app-language-change', listener);
  return () => {
    window.removeEventListener('storage', listener);
    window.removeEventListener('app-language-change', listener);
  };
}

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const language = useSyncExternalStore(subscribe, readLanguage, (): Language => 'vi');
  const setLanguage = (next: Language) => {
    window.localStorage.setItem('app_language', next);
    window.dispatchEvent(new Event('app-language-change'));
  };

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  return (
    <LanguageContext.Provider value={{ language, setLanguage }}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage() {
  const { language, setLanguage } = useContext(LanguageContext);
  return {
    language,
    locale: language === 'vi' ? 'vi-VN' : 'en-US',
    setLanguage,
    t: (en: string, vi: string) => language === 'vi' ? vi : en,
    translate: (text: string) => (catalog as Record<string, { vi: string; en: string }>)[text]?.[language] ?? text,
  };
}
