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
  'agile.adversarial_review.parallel_in_auto_mode',
]

describe('setting descriptions', () => {
  it('documents all agile adversarial review settings', () => {
    for (const key of adversarialReviewKeys) {
      expect(SETTING_DESCRIPTIONS).toHaveProperty(key)
    }
  })
})
