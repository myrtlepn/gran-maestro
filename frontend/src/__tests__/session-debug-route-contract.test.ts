import { describe, expect, it } from 'vitest';
import { AppRoutes } from '@/routes';
import { TABS } from '@/components/layout/TabNav';
import {
  SESSION_DEBUG_PANEL_REGISTRY,
  SESSION_DEBUG_SUMMARY_CARD_IDS,
} from '@/views/DebugView';

function getRoutePaths(): string[] {
  const routesTree = AppRoutes() as { props?: { children?: unknown } };
  const children = routesTree?.props?.children;
  const routeElements = Array.isArray(children) ? children : [children];

  return routeElements
    .map((element) => (element as { props?: { path?: unknown } } | null)?.props?.path)
    .filter((path): path is string => typeof path === 'string');
}

describe('DOD-005 Session Debug route and tab contract', () => {
  it('reuses the existing Debug top-level tab without Debug-adjacent proliferation', () => {
    const debugTabs = TABS.filter((tab) => tab.id === 'debug' || tab.label === 'Debug');
    const tabSearch = TABS.map((tab) => `${tab.id}:${tab.label}:${tab.path}`.toLowerCase());

    expect(debugTabs).toHaveLength(1);
    expect(debugTabs[0]).toMatchObject({ id: 'debug', label: 'Debug', path: '/debug' });
    expect(tabSearch.some((value) => value.includes('session debug'))).toBe(false);
    expect(tabSearch.some((value) => value.includes('hud'))).toBe(false);
    expect(tabSearch.some((value) => value.includes('statusline'))).toBe(false);
    expect(tabSearch.some((value) => value.includes('compact_display'))).toBe(false);
  });

  it('keeps Session Debug inside /debug and /debug/:sessionId routes only', () => {
    const paths = getRoutePaths();

    expect(paths).toContain('/debug');
    expect(paths).toContain('/debug/:sessionId');
    expect(paths).not.toContain('/session-debug');
    expect(paths).not.toContain('/debug/session-debug');
    expect(paths).not.toContain('/debug/:sessionId/session-debug');
    expect(
      paths.filter(
        (path) =>
          path.includes('hud') ||
          path.includes('statusline') ||
          path.includes('compact_display')
      )
    ).toEqual([]);
  });
});

describe('DOD-005 Session Debug panel registry contract', () => {
  it('defines the deterministic summary card set', () => {
    expect(SESSION_DEBUG_SUMMARY_CARD_IDS).toEqual([
      'identity',
      'current_work',
      'prompt',
      'writers',
      'integrity',
      'projection',
    ]);
  });

  it('registers all drill-down panels and excludes HUD/statusline from the dashboard IA', () => {
    expect(SESSION_DEBUG_PANEL_REGISTRY.map((panel) => panel.id)).toEqual([
      'summary',
      'identity',
      'prompt_timeline',
      'current_work',
      'execution_flow',
      'writer_coverage',
      'integrity_freshness',
      'policy_block',
    ]);
    expect(SESSION_DEBUG_PANEL_REGISTRY.map((panel) => panel.label)).toEqual([
      'Summary',
      'Identity Mapping',
      'Prompt Timeline',
      'Current Work',
      'Execution Flow',
      'Writer Coverage',
      'Integrity & Freshness',
      'Policy/Block',
    ]);

    const registryText = JSON.stringify(SESSION_DEBUG_PANEL_REGISTRY).toLowerCase();
    expect(registryText).not.toContain('hud');
    expect(registryText).not.toContain('statusline');
    expect(registryText).not.toContain('compact_display');
  });
});
