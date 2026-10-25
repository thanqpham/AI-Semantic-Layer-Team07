import type { SVGProps } from 'react';

export function BotMessageSquareIcon({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg aria-hidden="true" className={`bot-message-icon ${className ?? ''}`} fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" viewBox="0 0 24 24" {...props}>
      <path d="M12 6V2H8" />
      <path d="M2 12h2" />
      <path d="M20 12h2" />
      <path className="bot-message-frame" d="M20 16a2 2 0 0 1-2 2H8.828a2 2 0 0 0-1.414.586l-2.202 2.202A.71.71 0 0 1 4 20.286V8a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2z" />
      <path className="bot-message-eye bot-message-eye-left" d="M9 11v2" />
      <path className="bot-message-eye bot-message-eye-right" d="M15 11v2" />
      <circle className="bot-message-dot bot-message-dot-1" cx="10" cy="18" r="0.5" />
      <circle className="bot-message-dot bot-message-dot-2" cx="12" cy="18" r="0.5" />
      <circle className="bot-message-dot bot-message-dot-3" cx="14" cy="18" r="0.5" />
    </svg>
  );
}
