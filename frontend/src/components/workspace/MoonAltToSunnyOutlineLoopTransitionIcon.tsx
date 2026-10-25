'use client';

import { useId, type SVGProps } from 'react';

export function MoonAltToSunnyOutlineLoopTransitionIcon({ size = 24, theme, className, ...props }: SVGProps<SVGSVGElement> & { size?: number; theme: 'light' | 'dark' }) {
  const maskId = useId();
  const outerMaskId = useId();

  if (theme === 'dark') {
    return (
      <svg width={size} height={size} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" aria-hidden="true" className={`theme-toggle-icon ${className ?? ''}`} {...props}>
        <path data-theme-moon fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" d="M20.985 12.486A9 9 0 1 1 11.514 3.015a7 7 0 0 0 9.471 9.471Z">
          <animateTransform attributeName="transform" type="rotate" values="-80 12 12;0 12 12" dur="0.7s" fill="freeze" />
          <animate attributeName="opacity" values="0;1" dur="0.7s" fill="freeze" />
        </path>
      </svg>
    );
  }

  return (
    <svg width={size} height={size} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" aria-hidden="true" className={`theme-toggle-icon ${className ?? ''}`} {...props}>
      <defs>
        <mask id={maskId}>
          <path fill="#fff" d="M12 6c3.31 0 6 2.69 6 6c0 3.31 -2.69 6 -6 6c-3.31 0 -6 -2.69 -6 -6c0 -3.31 2.69 -6 6 -6Z">
            <animate fill="freeze" attributeName="d" dur="0.4s" values="M12 2c5.52 0 10 4.48 10 10c0 5.52 -4.48 10 -10 10c-5.52 0 -10 -4.48 -10 -10c0 -5.52 4.48 -10 10 -10Z;M12 6c3.31 0 6 2.69 6 6c0 3.31 -2.69 6 -6 6c-3.31 0 -6 -2.69 -6 -6c0 -3.31 2.69 -6 6 -6Z" />
          </path>
          <path d="M22 -4c3.31 0 6 2.69 6 6c0 3.31 -2.69 6 -6 6c-3.31 0 -6 -2.69 -6 -6c0 -3.31 2.69 -6 6 -6Z">
            <animate fill="freeze" attributeName="d" dur="0.4s" values="M18 -4c5.52 0 10 4.48 10 10c0 5.52 -4.48 10 -10 10c-5.52 0 -10 -4.48 -10 -10c0 -5.52 4.48 -10 10 -10Z;M22 -4c3.31 0 6 2.69 6 6c0 3.31 -2.69 6 -6 6c-3.31 0 -6 -2.69 -6 -6c0 -3.31 2.69 -6 6 -6Z" />
            <set fill="freeze" attributeName="opacity" begin="0.4s" to="0" />
          </path>
          <path d="M12 8c2.21 0 4 1.79 4 4c0 2.21 -1.79 4 -4 4c-2.21 0 -4 -1.79 -4 -4c0 -2.21 1.79 -4 4 -4Z">
            <animate fill="freeze" attributeName="d" dur="0.4s" values="M12 4c4.42 0 8 3.58 8 8c0 4.42 -3.58 8 -8 8c-4.42 0 -8 -3.58 -8 -8c0 -4.42 3.58 -8 8 -8Z;M12 8c2.21 0 4 1.79 4 4c0 2.21 -1.79 4 -4 4c-2.21 0 -4 -1.79 -4 -4c0 -2.21 1.79 -4 4 -4Z" />
          </path>
        </mask>
        <mask id={outerMaskId}>
          <path fill="#fff" d="M22 -6c4.42 0 8 3.58 8 8c0 4.42 -3.58 8 -8 8c-4.42 0 -8 -3.58 -8 -8c0 -4.42 3.58 -8 8 -8Z">
            <animate fill="freeze" attributeName="d" dur="0.4s" values="M18 -6c6.62 0 12 5.38 12 12c0 6.62 -5.38 12 -12 12c-6.62 0 -12 -5.38 -12 -12c0 -6.62 5.38 -12 12 -12Z;M22 -6c4.42 0 8 3.58 8 8c0 4.42 -3.58 8 -8 8c-4.42 0 -8 -3.58 -8 -8c0 -4.42 3.58 -8 8 -8Z" />
            <set fill="freeze" attributeName="opacity" begin="0.4s" to="0" />
          </path>
          <path d="M22 -4c3.31 0 6 2.69 6 6c0 3.31 -2.69 6 -6 6c-3.31 0 -6 -2.69 -6 -6c0 -3.31 2.69 -6 6 -6ZM6 12v-20h26v26h-20c3.31 0 6 -2.69 6 -6c0 -3.31 -2.69 -6 -6 -6c-3.31 0 -6 2.69 -6 6Z">
            <animate fill="freeze" attributeName="d" dur="0.4s" values="M18 -4c5.52 0 10 4.48 10 10c0 5.52 -4.48 10 -10 10c-5.52 0 -10 -4.48 -10 -10c0 -5.52 4.48 -10 10 -10ZM2 12v-20h30v30h-20c5.52 0 10 -4.48 10 -10c0 -5.52 -4.48 -10 -10 -10c-5.52 0 -10 4.48 -10 10Z;M22 -4c3.31 0 6 2.69 6 6c0 3.31 -2.69 6 -6 6c-3.31 0 -6 -2.69 -6 -6c0 -3.31 2.69 -6 6 -6ZM6 12v-20h26v26h-20c3.31 0 6 -2.69 6 -6c0 -3.31 -2.69 -6 -6 -6c-3.31 0 -6 2.69 -6 6Z" />
            <set fill="freeze" attributeName="opacity" begin="0.4s" to="0" />
          </path>
        </mask>
      </defs>
      <g fill="currentColor">
        <path d="M0 0h24v24H0z" mask={`url(#${maskId})`} />
        <path d="M0 0h24v24H0z" mask={`url(#${outerMaskId})`} />
      </g>
      <g fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2">
        <path d="M12 21v1M21 12h1M12 3v-1M3 12h-1" opacity="0">
          <animateTransform attributeName="transform" dur="30s" repeatCount="indefinite" type="rotate" values="0 12 12;360 12 12" />
          <set fill="freeze" attributeName="opacity" begin="0.4s" to="1" />
          <animate fill="freeze" attributeName="d" begin="0.4s" dur="0.2s" values="M12 19v1M19 12h1M12 5v-1M5 12h-1;M12 21v1M21 12h1M12 3v-1M3 12h-1" />
        </path>
        <path d="M18.5 18.5l0.5 0.5M18.5 5.5l0.5 -0.5M5.5 5.5l-0.5 -0.5M5.5 18.5l-0.5 0.5" opacity="0">
          <animateTransform attributeName="transform" dur="30s" repeatCount="indefinite" type="rotate" values="0 12 12;360 12 12" />
          <set fill="freeze" attributeName="opacity" begin="0.6s" to="1" />
          <animate fill="freeze" attributeName="d" begin="0.6s" dur="0.2s" values="M17 17l0.5 0.5M17 7l0.5 -0.5M7 7l-0.5 -0.5M7 17l-0.5 0.5;M18.5 18.5l0.5 0.5M18.5 5.5l0.5 -0.5M5.5 5.5l-0.5 -0.5M5.5 18.5l-0.5 0.5" />
        </path>
      </g>
    </svg>
  );
}
