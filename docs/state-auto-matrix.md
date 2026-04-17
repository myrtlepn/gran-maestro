# REQ-638 T03 — `state set-workflow` AUTO_MODE 감사 매트릭스

수집 명령:

```bash
grep -rn "state set-workflow" skills/ hooks/ scripts/ docs/ 2>/dev/null | grep -v "matrix.md"
```

| 파일:라인 | 호출 시점 (Step/조건) | `--auto` 인자 출처 | 예상 AUTO_MODE 값 (호출 시점) | 검토 결과 |
|---|---|---|---|---|
| skills/plan/SKILL.md:255 | plan Step 1.5, `AUTO_MODE=true` 분기에서 workflow 시작 기록 | 상수 `true` (`--auto true`) | `true` | OK |
| skills/request/SKILL.md:237 | request Step 4, `AUTO_APPROVE=true` 분기에서 request→approve 전이 기록 | 상수 `true` (`--auto true`) | `true` | OK |
| skills/approve/SKILL.md:221 | approve 단건 프로토콜 진입 직후, `AUTO_MODE=true` 분기 | 상수 `true` (`--auto true`) | `true` | OK |
| skills/accept/SKILL.md:176 | accept Step 5.1, `agile_loop_active=true` 시 agile 복귀 상태 복원 | 변수 `AUTO_MODE` (`--auto {AUTO_MODE}`) | accept Step 0.1 판정값 유지 (`true`/`false`) | 교정 완료 (누락 보완) |
| skills/accept/SKILL.md:192 | accept Step 5.1, `agile_loop_active!=true` 시 workflow 종료(clear) | 상수 `false` (`--auto false`) | `false` (종료 경로) | OK |
| skills/agile/SKILL.md:156 | agile Step 0.2, `--resume` 경로 진입 시 workflow 활성 | 변수 `AUTO_MODE` (`--auto {AUTO_MODE}`) | Step 0.1 판정값 (`true`/`false`) | OK |
| skills/agile/SKILL.md:175 | agile Step 0.3, 신규 세션 진입 시 workflow 활성 | 변수 `AUTO_MODE` (`--auto {AUTO_MODE}`) | Step 0.1 판정값 (`true`/`false`) | OK |
| skills/agile/SKILL.md:386 | agile Step 2.2 루프 시작 공통 게이트 (retrospective 이후 재진입 포함) | 변수 `AUTO_MODE` (`--auto {AUTO_MODE}`) | 현재 루프 AUTO_MODE 유지 (`true`/`false`) | OK |
| skills/agile/SKILL.md:946 | agile Step 2.3 종료 보고 후 workflow 비활성 | 미지정 (active=false clear 경로) | `false` (state.py 기본값) | OK (종료 경로) |
| skills/agile/SKILL.md:1161 | agile 자동 중단 트리거 후 workflow 비활성 | 미지정 (active=false clear 경로) | `false` (state.py 기본값) | OK (종료 경로) |
| docs/mst-loop.md:110 | 문서 예시(실행 코드 아님): set-workflow + queue enqueue 동시 기록 | 상수 `true` (`--auto true`) | 예시값 `true` | OK (문서 샘플) |

## 감사 결론

- agile 루프 핵심 경로(plan→request→approve→accept→retrospective→새 sprint)에서 `AUTO_MODE=true` 전파가 끊기는 실질 누락은 `skills/accept/SKILL.md:176` 1건이었다.
- 해당 지점은 `--auto {AUTO_MODE}` 승계 규칙을 추가해 교정했다.
- `active=false`로 워크플로우를 닫는 clear 경로(`accept:192`, `agile:946`, `agile:1161`)는 `auto_mode` 의미가 없으므로 false 유지(명시 또는 state.py 기본값)로 판정했다.
- agile의 `active=true` 경로(`:156`, `:175`, `:386`)는 모두 `--auto {AUTO_MODE}`가 이미 명시되어 추가 교정 없음.
