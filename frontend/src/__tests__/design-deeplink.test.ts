import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

let hookState: unknown[] = []
let hookCursor = 0

vi.mock('react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react')>()
  return {
    ...actual,
    useState: (initial: unknown) => {
      const cursor = hookCursor++
      if (hookState.length === cursor) {
        hookState.push(typeof initial === 'function' ? (initial as () => unknown)() : initial)
      }
      const setState = (value: unknown) => {
        hookState[cursor] = typeof value === 'function'
          ? (value as (current: unknown) => unknown)(hookState[cursor])
          : value
      }
      return [hookState[cursor], setState]
    },
  }
})

import { useAuth } from '@/hooks/useAuth'
import { apiFetch } from '@/hooks/useApi'

function renderHook<T>(hookFn: () => T) {
  hookCursor = 0
  return { current: hookFn() }
}

describe('design deep link runtime contract', () => {
  beforeEach(() => {
    hookState = []
    hookCursor = 0
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('restores projectId from query into sessionStorage and removes the query from URL', () => {
    const storage = new Map<string, string>()
    const replaceState = vi.fn()

    vi.stubGlobal('sessionStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value)
      },
      removeItem: (key: string) => {
        storage.delete(key)
      },
      clear: () => {
        storage.clear()
      },
    })

    vi.stubGlobal('window', {
      location: {
        search: '?project=4843d2',
        pathname: '/designs/DES-011',
        hash: '#screen-001',
      },
      history: {
        replaceState,
      },
    })

    const hook = renderHook(() => useAuth())

    expect(hook.current.projectId).toBe('4843d2')
    expect(storage.get('gm_project')).toBe('4843d2')
    expect(replaceState).toHaveBeenCalledWith({}, '', '/designs/DES-011#screen-001')
  })

  it('falls back to stored project when query is absent', () => {
    const storage = new Map<string, string>([['gm_project', 'stored-project']])
    const replaceState = vi.fn()

    vi.stubGlobal('sessionStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value)
      },
      removeItem: (key: string) => {
        storage.delete(key)
      },
      clear: () => {
        storage.clear()
      },
    })

    vi.stubGlobal('window', {
      location: {
        search: '',
        pathname: '/designs/DES-011',
        hash: '',
      },
      history: {
        replaceState,
      },
    })

    const hook = renderHook(() => useAuth())

    expect(hook.current.projectId).toBe('stored-project')
    expect(replaceState).not.toHaveBeenCalled()
  })

  it('rewrites design list and detail requests into project-scoped API paths', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true }),
    })

    vi.stubGlobal('fetch', fetchMock)

    await apiFetch('/api/designs', '4843d2')
    await apiFetch('/api/designs/DES-011', '4843d2')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/projects/4843d2/designs')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/projects/4843d2/designs/DES-011')
  })
})
