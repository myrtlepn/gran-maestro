import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ActionBoard } from '@/components/agile/ActionBoard';
import { AlignmentView } from '@/components/agile/AlignmentView';
import { HealthSummary } from '@/components/agile/HealthSummary';
import { SprintTimeline } from '@/components/agile/SprintTimeline';
import {
  buildActionCards,
  computeDodProgress,
  getLatestNewIslandRatio,
  resolveDefaultSprintId,
  resolveObjectiveMarkdownPath,
  sortSprints,
} from '@/components/agile/utils';
import type { AgileSprint, ObjectiveParsedDod } from '@/components/agile/types';

describe('agile dashboard helpers', () => {
  it('resolves default sprint using current sprint when present', () => {
    expect(resolveDefaultSprintId(
      sortSprints([{ sprint_id: 'S02' }, { sprint_id: 'S01' }, { sprint_id: 'S03' }] as AgileSprint[]),
      2,
      null,
    )).toBe('S02');
  });

  it('resolves markdown objective links relative to current file', () => {
    expect(resolveObjectiveMarkdownPath('./details/api.md', 'objective.md')).toBe('details/api.md');
    expect(resolveObjectiveMarkdownPath('https://example.com', 'objective.md')).toBeNull();
  });

  it('builds action cards from approvals, drift, and integration debt', () => {
    const cards = buildActionCards(
      { deferred_dod_count: 2 },
      [{
        sprint_id: 'S04',
        target_dod: 'DOD-004',
        alignmentCheck: { verdict: 'drift_warning', raw_excerpt: 'drift detected' },
        integrationReview: { ratios: { new_island: 0.25 }, force_wire_recommended: true },
      }] as AgileSprint[],
      'S04',
    );

    expect(cards.map((card) => card.id)).toEqual(['approvals', 'steering', 'escalation']);
  });

  it('computes DoD progress and latest new island ratio', () => {
    const dods: ObjectiveParsedDod[] = [
      { dod: 'DOD-001', status: 'done', priority: 'must' },
      { dod: 'DOD-002', status: 'todo', priority: 'must' },
      { dod: 'DOD-003', status: 'done', priority: 'should' },
    ];
    const ratio = getLatestNewIslandRatio([
      { sprint_id: 'S01', integrationReview: { ratios: { new_island: 0.11 } } },
      { sprint_id: 'S02', integrationReview: { ratios: { new_island: 0.24 } } },
    ] as AgileSprint[], 'S02');

    expect(computeDodProgress(dods)).toBe(67);
    expect(ratio).toBe(0.24);
  });
});

describe('agile dashboard components', () => {
  it('renders action board approval and escalation cards', () => {
    const html = renderToStaticMarkup(createElement(ActionBoard, {
      cards: [
        { id: 'approvals', tone: 'neutral', eyebrow: '승인 대기', title: '승인 대기 2건', description: '검토 필요', count: 2 },
        { id: 'escalation', tone: 'danger', eyebrow: 'Escalation', title: '강제 wire 검토 필요', description: 'S04 · new_island_ratio 0.25' },
      ],
    }));

    expect(html).toContain('승인 대기 2건');
    expect(html).toContain('강제 wire 검토 필요');
  });

  it('renders health summary warning ratio badge', () => {
    const html = renderToStaticMarkup(createElement(HealthSummary, {
      dodProgress: 68,
      openIssuesCount: 4,
      newIslandRatio: 0.24,
    }));

    expect(html).toContain('68%');
    expect(html).toContain('0.24');
    expect(html).toContain('미해결 이슈');
  });

  it('renders alignment view traffic-light verdicts', () => {
    const html = renderToStaticMarkup(createElement(AlignmentView, {
      dods: [{ dod: 'DOD-001', status: 'done', priority: 'must', contentText: '핵심 플로우', anchorText: null }],
      sprints: [{ sprint_id: 'S02', target_dod: 'DOD-001', alignmentCheck: { verdict: 'aligned', raw_excerpt: 'aligned' } }],
    }));

    expect(html).toContain('DoD x alignment-check');
    expect(html).toContain('정합');
    expect(html).toContain('DOD-001');
  });

  it('renders sprint timeline with user observable copy and force wire warning', () => {
    const html = renderToStaticMarkup(createElement(SprintTimeline, {
      sprints: [{
        sprint_id: 'S03',
        sprint_kind: 'user_observable',
        user_observable_change: '사용자가 plan 호출 후 즉시 Q&amp;A를 시작할 수 있다.',
        integrationReview: { ratios: { new_island: 0.21 }, force_wire_recommended: true },
        status: 'done',
      }],
      currentSprintId: 'S03',
      selectedSprintId: 'S03',
      onSprintSelect: () => undefined,
    }));

    expect(html).toContain('User Observable');
    expect(html).toContain('wire 권고');
    expect(html).toContain('즉시 Q&amp;amp;A');
  });
});
