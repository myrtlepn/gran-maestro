import { describe, expect, it } from 'vitest'
import { AppRoutes } from '@/routes'
import { resolveAgileMainTab, resolveAgileSelectedSessionId } from '@/views/AgileView'

function getRoutePaths(): string[] {
  const routesTree = AppRoutes() as { props?: { children?: unknown } }
  const children = routesTree?.props?.children
  const routeElements = Array.isArray(children) ? children : [children]

  return routeElements
    .map((element) => (element as { props?: { path?: unknown } } | null)?.props?.path)
    .filter((path): path is string => typeof path === 'string')
}

describe('agile deep link routes', () => {
  it('registers agile route variants for backward compatibility and deep link', () => {
    const paths = getRoutePaths()

    expect(paths).toContain('/agile')
    expect(paths).toContain('/agile/:agiId')
    expect(paths).toContain('/agile/:agiId/objective')
  })
})

describe('agile selected session resolution', () => {
  const sessions = [{ id: 'AGI-001' }, { id: 'AGI-004' }, { id: 'AGI-007' }]

  it('selects agiId-matched session for deep link', () => {
    expect(resolveAgileSelectedSessionId(sessions, null, 'AGI-004')).toBe('AGI-004')
  })

  it('falls back to first session when agiId is unknown', () => {
    expect(resolveAgileSelectedSessionId(sessions, null, 'AGI-999')).toBe('AGI-001')
  })

  it('keeps previous selection when agiId is absent and previous session still exists', () => {
    expect(resolveAgileSelectedSessionId(sessions, 'AGI-007', undefined)).toBe('AGI-007')
  })

  it('falls back to first session when agiId is absent and previous session is missing', () => {
    expect(resolveAgileSelectedSessionId(sessions, 'AGI-999', undefined)).toBe('AGI-001')
  })

  it('returns null when no sessions exist', () => {
    expect(resolveAgileSelectedSessionId([], null, undefined)).toBeNull()
  })
})

describe('agile main tab resolution', () => {
  it('activates objective tab for objective deep link route', () => {
    expect(resolveAgileMainTab(true)).toBe('objective')
  })

  it('activates overview tab for non-objective routes', () => {
    expect(resolveAgileMainTab(false)).toBe('overview')
  })
})
