import { describe, expect, it } from 'vitest'
import { SETTING_DESCRIPTIONS } from '@/config/settingDescriptions'

const adversarialReviewKeys = [
  'agile.adversarial_review',
  'agile.adversarial_review.enabled',
  'agile.adversarial_review.perspectives.edge.enabled',
  'agile.adversarial_review.perspectives.flow.enabled',
  'agile.adversarial_review.perspectives.integration.enabled',
  'agile.adversarial_review.perspectives.persona.enabled',
  'agile.adversarial_review.perspectives.nfr.enabled',
  'agile.adversarial_review.max_rounds',
  'agile.adversarial_review.auto_apply_severity_threshold',
  'agile.adversarial_review.clarification_blocking_severities',
  'agile.adversarial_review.clarification_batch_max_items',
  'agile.adversarial_review.parallel_in_auto_mode',
]

describe('setting descriptions', () => {
  it('documents all agile adversarial review settings', () => {
    for (const key of adversarialReviewKeys) {
      expect(SETTING_DESCRIPTIONS).toHaveProperty(key)
    }
  })

  it('uses AGY as the canonical large-context provider option', () => {
    const providerFields = [
      'workflow.default_agent',
      'agile.dispatch.provider',
      'delegation.default_provider',
      'models.roles.developer.1.provider',
      'models.roles.reviewer.1.provider',
    ]

    for (const key of providerFields) {
      const entry = SETTING_DESCRIPTIONS[key]
      expect(typeof entry).toBe('object')
      if (typeof entry === 'object') {
        expect(entry.options).toContain(key === 'workflow.default_agent' ? 'agy-dev' : 'agy')
        expect(entry.options?.join(',')).not.toContain('gemini')
      }
    }

    expect(SETTING_DESCRIPTIONS).toHaveProperty('models.providers.agy.default_tier')
    expect(SETTING_DESCRIPTIONS).not.toHaveProperty('models.providers.gemini.default_tier')
  })

  it('exposes canonical native delegation controls and explains legacy aliases', () => {
    const transportPolicy = SETTING_DESCRIPTIONS['delegation.transport_policy']
    const nativeScope = SETTING_DESCRIPTIONS['delegation.native.scope']

    expect(transportPolicy).toMatchObject({
      options: ['same-host-native-first', 'external-only'],
    })
    expect(nativeScope).toMatchObject({
      options: [
        'all',
        'review-and-exploration-only',
        'review-only',
        'exploration-only',
        'implementation-only',
        'none',
      ],
    })
    expect(SETTING_DESCRIPTIONS).toHaveProperty('delegation.native.enabled')
    expect(SETTING_DESCRIPTIONS).toHaveProperty('delegation.orca.enabled')

    for (const key of [
      'delegation.native_codex_subagents.enabled',
      'delegation.native_codex_subagents.scope',
    ]) {
      expect(SETTING_DESCRIPTIONS[key]).toMatch(/legacy|alias/i)
      expect(SETTING_DESCRIPTIONS[key]).toMatch(/delegation\.native/)
    }
  })
})
