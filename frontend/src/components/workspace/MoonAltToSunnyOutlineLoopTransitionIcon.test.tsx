import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MoonAltToSunnyOutlineLoopTransitionIcon } from './MoonAltToSunnyOutlineLoopTransitionIcon';

describe('MoonAltToSunnyOutlineLoopTransitionIcon', () => {
  it('shows rotating sun rays only in light mode', () => {
    const { container, rerender } = render(<MoonAltToSunnyOutlineLoopTransitionIcon theme="light" />);
    expect(container.querySelector('svg')).toHaveClass('theme-toggle-icon');
    expect(container.querySelectorAll('animateTransform')).toHaveLength(2);

    rerender(<MoonAltToSunnyOutlineLoopTransitionIcon theme="dark" />);
    expect(container.querySelector('svg')).toHaveClass('theme-toggle-icon');
    const moon = container.querySelector('path[data-theme-moon]');
    expect(moon).toBeInTheDocument();
    expect(moon?.querySelector('animateTransform')).toBeInTheDocument();
  });
});
