import { AlertTriangle, CheckCircle2, ShieldAlert } from 'lucide-react';
import type { ActionCardData } from './utils';

interface ActionBoardProps {
  cards: ActionCardData[];
}

function toneClass(tone: ActionCardData['tone']): string {
  switch (tone) {
    case 'danger':
      return 'border-red-200 bg-red-50/50 text-red-700';
    case 'warning':
      return 'border-amber-200 bg-amber-50/50 text-amber-700';
    default:
      return 'border-sky-200 bg-sky-50/50 text-sky-700';
  }
}

function toneStripeClass(tone: ActionCardData['tone']): string {
  switch (tone) {
    case 'danger':
      return 'bg-red-500';
    case 'warning':
      return 'bg-amber-500';
    default:
      return 'bg-sky-500';
  }
}

function toneIcon(tone: ActionCardData['tone']) {
  switch (tone) {
    case 'danger':
      return <ShieldAlert className="h-4 w-4" aria-hidden="true" />;
    case 'warning':
      return <AlertTriangle className="h-4 w-4" aria-hidden="true" />;
    default:
      return <CheckCircle2 className="h-4 w-4" aria-hidden="true" />;
  }
}

export function ActionBoard({ cards }: ActionBoardProps) {
  const visibleCards = cards.length > 0
    ? cards
    : [{
      id: 'stable',
      tone: 'neutral' as const,
      eyebrow: 'Action Required',
      title: '즉시 개입 항목 없음',
      description: '승인 대기, drift, 통합 부채 경고가 현재는 없습니다.',
    }];

  return (
    <section className="rounded-md border border-zinc-200 bg-white p-6">
      <div className="mb-5 flex items-end justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">Hero</p>
          <h2 className="mt-1 text-lg font-semibold tracking-tight text-zinc-950">Action Required</h2>
        </div>
        <p className="text-xs text-zinc-500">지금 승인하거나 개입해야 할 신호</p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {visibleCards.map((card) => (
          <article key={card.id} className="relative overflow-hidden rounded-md border border-zinc-200 bg-zinc-50/40 p-5">
            <div className={`absolute inset-y-0 left-0 w-1 ${toneStripeClass(card.tone)}`} aria-hidden="true" />
            <div className="pl-3">
              <div className="flex items-start justify-between gap-3">
                <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">{card.eyebrow}</span>
                <span className={`inline-flex items-center rounded-full border px-2 py-1 ${toneClass(card.tone)}`}>
                  {toneIcon(card.tone)}
                </span>
              </div>

              <div className="mt-8 space-y-2">
                {typeof card.count === 'number' ? (
                  <div className="flex items-end gap-2">
                    <span className="text-4xl font-black tracking-tight text-zinc-950">{card.count}</span>
                    <span className="pb-1 text-xs font-medium text-zinc-500">건</span>
                  </div>
                ) : null}
                <p className="text-base font-semibold text-zinc-950">{card.title}</p>
                <p className="text-sm leading-6 text-zinc-600">{card.description}</p>
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
