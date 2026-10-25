import type { SVGProps } from 'react';

export function ClipboardDocumentListIcon({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg aria-hidden="true" className={`clipboard-list-icon ${className ?? ''}`} fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" viewBox="0 0 24 24" {...props}>
      <path d="M15.75 18.75H18a2.25 2.25 0 0 0 2.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 0 0-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 0 0 .75-.75 2.25 2.25 0 0 0-.1-.664m-5.8 0A2.251 2.251 0 0 1 13.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25Z" />
      <path className="clipboard-list-dot clipboard-list-dot-1" d="M6.75 12h.008v.008H6.75V12Z" />
      <path className="clipboard-list-line clipboard-list-line-1" d="M9 12h3.75" />
      <path className="clipboard-list-dot clipboard-list-dot-2" d="M6.75 15h.008v.008H6.75V15Z" />
      <path className="clipboard-list-line clipboard-list-line-2" d="M9 15h3.75" />
      <path className="clipboard-list-dot clipboard-list-dot-3" d="M6.75 18h.008v.008H6.75V18Z" />
      <path className="clipboard-list-line clipboard-list-line-3" d="M9 18h3.75" />
    </svg>
  );
}
