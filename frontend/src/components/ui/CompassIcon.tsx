import type { SVGProps } from 'react';

/** Compass whose needle swings and settles on hover, like a real compass finding north. */
export function CompassIcon({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg aria-hidden="true" className={`compass-icon ${className ?? ''}`} fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" viewBox="0 0 24 24" {...props}>
      <circle cx="12" cy="12" r="9.25" />
      <circle className="compass-ping" cx="12" cy="12" r="3" />
      <path className="compass-needle" d="M15.9 8.1 13.4 13.4 8.1 15.9l2.5-5.3 5.3-2.5Z" />
      <circle cx="12" cy="12" r="0.6" fill="currentColor" stroke="none" />
    </svg>
  );
}
