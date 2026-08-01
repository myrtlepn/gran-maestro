import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { DispatchRunCard } from '@/components/DispatchPanel'
import type { DispatchStreamItem } from '@/hooks/useDispatchStream'

function item(overrides: Partial<DispatchStreamItem>): DispatchStreamItem {
  return {
    task_id: 'TASK-1',
    attempt_id: 'attempt-1',
    phase: 'running',
    provider: 'codex',
    model: 'gpt-5',
    execution_transport: 'native',
    requested_launch_surface: 'direct',
    launch_surface: 'direct',
    launch_surface_status: 'disabled',
    orca_launch_status: null,
    route_reason: 'same_host_native_capable',
    provider_task_id: 'provider-task-1',
    completion_signal: null,
    exit_code: null,
    fallback_from: null,
    fallback_to: null,
    provider_reconciliation_required: false,
    reconciliation_required: false,
    reconciliation_invariant_gap: false,
    reconciliation_action: null,
    mst_session_id: 'MST-REQ-939-20260711T131345269Z-test0001',
    root_mst_id: 'REQ-939',
    parent_session_id: 'MST-REQ-939-20260711T131345269Z-test0001',
    running_log_path: '/tmp/running.log',
    trace_path: '/tmp/trace.json',
    output_path: '/tmp/result.md',
    terminal: false,
    heartbeat_age_sec: 5,
    stale: false,
    ...overrides,
  }
}

describe('DispatchRunCard', () => {
  it('shows native route evidence and renders a nullable exit code as N/A', () => {
    const html = renderToStaticMarkup(createElement(DispatchRunCard, {
      item: item({
        phase: 'reconciling',
        reconciliation_action: {
          action_id: 'provider-reconcile:abc',
          status: 'pending',
        },
      }),
    }))

    expect(html).toContain('native')
    expect(html).toContain('route: same_host_native_capable')
    expect(html).toContain('provider task: provider-task-1')
    expect(html).toContain('completion: N/A')
    expect(html).toContain('exit: N/A')
    expect(html).not.toContain('exit: 0')
    expect(html).toContain('reconcile: provider-reconcile:abc · pending')
  })

  it('shows external fallback linkage and preserves a real zero exit code', () => {
    const html = renderToStaticMarkup(createElement(DispatchRunCard, {
      item: item({
        attempt_id: 'external-a2',
        execution_transport: 'external',
        route_reason: 'external_fallback_after_definitive_not_created',
        provider_task_id: null,
        completion_signal: 'completed',
        exit_code: 0,
        fallback_from: 'native-a1',
      }),
    }))

    expect(html).toContain('external')
    expect(html).toContain('completion: completed')
    expect(html).toContain('exit: 0')
    expect(html).toContain('fallback: native-a1 → external-a2')
  })

  it('shows the Orca launch surface independently from external transport', () => {
    const html = renderToStaticMarkup(createElement(DispatchRunCard, {
      item: item({
        execution_transport: 'external',
        requested_launch_surface: 'orca',
        launch_surface: 'orca',
        launch_surface_status: 'ready',
        orca_launch_status: 'created',
      }),
    }))

    expect(html).toContain('external')
    expect(html).toContain('orca · created')
  })

  it('shows an Orca preflight fallback instead of hiding it as direct', () => {
    const html = renderToStaticMarkup(createElement(DispatchRunCard, {
      item: item({
        execution_transport: 'external',
        requested_launch_surface: 'orca',
        launch_surface: 'direct',
        launch_surface_status: 'preflight_failed',
      }),
    }))

    expect(html).toContain('orca · fallback · preflight_failed')
  })

  it('distinguishes resolved reconciliation evidence from a terminal invariant gap', () => {
    const resolved = renderToStaticMarkup(createElement(DispatchRunCard, {
      item: item({
        phase: 'terminated',
        terminal: true,
        reconciliation_action: {
          action_id: 'provider-reconcile:resolved',
          status: 'resolved',
          completion_accepted: true,
        },
      }),
    }))
    const corrupt = renderToStaticMarkup(createElement(DispatchRunCard, {
      item: item({
        phase: 'done',
        terminal: true,
        provider_reconciliation_required: true,
        reconciliation_invariant_gap: true,
        reconciliation_action: {
          action_id: 'provider-reconcile:corrupt',
          status: 'pending',
          completion_accepted: false,
        },
      }),
    }))

    expect(resolved).toContain('reconcile: provider-reconcile:resolved · resolved')
    expect(resolved).not.toContain('reconciliation invariant gap')
    expect(corrupt).toContain('reconciliation invariant gap')
    expect(corrupt).toContain('reconcile: provider-reconcile:corrupt · pending')
  })
})
