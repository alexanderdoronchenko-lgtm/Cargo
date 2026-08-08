/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: 'var(--color-bg)',
        'bg-elevated': 'var(--color-bg-elevated)',
        'bg-subtle': 'var(--color-bg-subtle)',
        border: 'var(--color-border)',
        ink: 'var(--color-text-primary)',
        'ink-muted': 'var(--color-text-muted)',
        'on-accent': 'var(--color-text-on-accent)',
        terracotta: {
          DEFAULT: 'var(--color-accent-terracotta)',
          hover: 'var(--color-accent-terracotta-hover)',
          active: 'var(--color-accent-terracotta-active)',
          soft: 'var(--color-accent-terracotta-soft)',
        },
        ruby: {
          DEFAULT: 'var(--color-tier-ruby)',
          soft: 'var(--color-tier-ruby-soft)',
        },
        emerald: {
          DEFAULT: 'var(--color-tier-emerald)',
          soft: 'var(--color-tier-emerald-soft)',
        },
        diamond: {
          DEFAULT: 'var(--color-tier-diamond)',
          soft: 'var(--color-tier-diamond-soft)',
        },
      },
      fontFamily: {
        heading: ['var(--font-heading)'],
        body: ['var(--font-body)'],
        mono: ['var(--font-mono)'],
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
      },
      boxShadow: {
        elevated: 'var(--shadow-elevated)',
      },
    },
  },
  plugins: [],
};
