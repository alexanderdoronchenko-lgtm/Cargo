export default function TabBar({ tabs, active, onChange }) {
  return (
    <nav className="border-t border-border bg-bg-elevated" style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}>
      <div className="flex">
        {tabs.map((tab) => {
          const isActive = tab.id === active;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => onChange(tab.id)}
              aria-current={isActive ? 'page' : undefined}
              className={`flex-1 py-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terracotta focus-visible:ring-inset ${
                isActive ? 'text-terracotta' : 'text-ink-muted'
              }`}
            >
              <span className="block">{tab.label}</span>
              <span
                className={`mx-auto mt-1.5 block h-0.5 w-6 rounded-full transition-colors ${
                  isActive ? 'bg-terracotta' : 'bg-transparent'
                }`}
              />
            </button>
          );
        })}
      </div>
    </nav>
  );
}
