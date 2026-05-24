# Pass A Protocol

> 이 Step의 목적: AC 충족 여부를 확정해 Pass B 진입 가능성을 결정한다 / 핵심 출력물: `pass_a_result`, `failed_ac_ids`, `failure_class`, `evidence`
> ⚠️ CRITICAL: MUST AC가 1개라도 FAIL이면 `pass_a_failed`로 즉시 전환하고 Pass B로 진행하지 않는다.

**책임**: PM이 최종 판정 수행 (개발자 자가 보고 신뢰 안 함). 단, `[browser-test]` AC 실행은 `review.roles.browser_tester` 설정 시 서브에이전트 위임 가능.

#### AC 등급별 판정 의사결정

| AC 등급 | PASS | FAIL 시 동작 |
|---|---|---|
| MUST | Pass A 계속 진행 | `pass_a_failed`로 전환, Pass B 진입 차단, `pass-a-result.md` 작성 후 approve에 반환 |
| SHOULD | 경고 없이 계속 진행 | 경고로 기록하고 Pass A는 계속 진행 (Pass B 진입 허용) |

#### automatable AC 검증 (PM 독립 실행)

1. spec.md의 각 automatable AC에 정의된 `Test:` 명령을 PM이 직접 실행
2. **Playwright 조건부 실행**: 프로젝트에 Playwright가 있으면 (`package.json`에 `playwright` 의존성 또는 `playwright.config.*` 파일 존재) `npx playwright test` 실행 후 스크린샷 증거 수집. Playwright가 없으면 이 단계 건너뜀.
3. 실행 결과가 `Then:` 기대값과 일치 여부 판정
4. 테스트 코드가 없으면 → `failure_class: ac_unclear`

#### browser-test 위임 모드 (선택)

1. `config.resolved.json.review.roles.browser_tester.agent`가 설정되어 있으면 PM은 `[browser-test]` AC 실행을 해당 에이전트에 위임한다.
2. 위임 에이전트는 `skills/review/SKILL.md`의 browser-test 실행 분기 규칙(도구 감지, 사전 검증, 스크린샷 저장, 결과 스키마)을 동일하게 따른다.
3. PM은 반환된 결과를 검토해 `results.json`에 기록하고 PASS/FAIL/SKIP을 최종 판정한다.
4. `browser_tester`가 미설정이면 기존 PM 직접 실행 모드를 유지한다 (하위 호환).

#### manual AC 검증 (PM 직접 확인)

1. PM이 직접 동작 확인 (클릭, 실행, 결과 관찰)
2. 확인 완료: 증거 텍스트 또는 스크린샷 기록
3. 불명확하면 → `failure_class: ac_unclear`

#### automatable AC가 없는 경우

spec.md에 automatable AC가 없고 manual AC만 존재하는 경우: automatable 검증 단계를 건너뛰고 manual AC 검증만 수행.

#### Pass A 체크리스트

- [ ] AC-시나리오 추적성: 모든 AC가 1개 이상 시나리오에 매핑됨
- [ ] 실행 증거: 시나리오별 로그/출력/스크린샷 중 최소 1개
- [ ] 기대 결과 일치: 실제 결과 = 기대값
- [ ] 음수/경계 케이스: 최소 1개 포함 (신규 기능 필수)
- [ ] 회귀 확인: 영향 모듈 핵심 회귀 통과
- [ ] 모호성 차단: AC 불명확 시 pass 금지
- [ ] 실패 분류 강제: fail 시 `ac_unclear` | `interpretation` | `implementation` 중 1개 지정

#### Pass A 출력

- `pass_a_result`: `pass` | `fail`
- `failed_ac_ids`: 실패한 AC-ID 목록
- `failure_class`: `ac_unclear` | `interpretation` | `implementation`
- `evidence`: 실행 로그/스크린샷 경로/확인 기록 목록

**MUST AC 하나라도 fail → Pass B 진입 차단 → approve에 `pass_a_failed` 상태 반환 (review는 mst:feedback을 직접 호출하지 않고 종료)**

Pass A 결과를 `reviews/RV-NNN/pass-a-result.md`에 저장:

```markdown
# Pass A 결과 — RV-NNN

pass_a_result: pass | fail
failed_ac_ids: [AC-XX, ...]
failure_class: ac_unclear | interpretation | implementation
evidence:
  - <로그/스크린샷 경로 또는 확인 기록>
```

MUST AC가 하나라도 실패한 경우: `pass-a-result.md`를 저장하고 `pass_a_failed` 상태를 approve에 반환한다 (review는 mst:feedback을 직접 호출하지 않고 종료). Pass B는 진행하지 않음. SHOULD AC만 실패한 경우: 경고로 기록하고 Pass B 진입 허용.
