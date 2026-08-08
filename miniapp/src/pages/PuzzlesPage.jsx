export default function PuzzlesPage() {
  return (
    <section className="space-y-4">
      <header>
        <p className="font-mono text-xs uppercase tracking-wider text-terracotta mb-1">!! Задачки</p>
        <h1 className="font-heading text-2xl font-bold">Тактические задачки</h1>
        <p className="text-ink-muted text-sm mt-2 max-w-[60ch]">
          Позиции из критических моментов твоих собственных партий — найди лучший ход так же,
          как это делает движок в разборе.
        </p>
      </header>
      <div className="rounded-md border border-border bg-bg-elevated p-6 text-center text-ink-muted text-sm">
        Раздел в разработке — скоро здесь появятся задачки.
      </div>
    </section>
  );
}
