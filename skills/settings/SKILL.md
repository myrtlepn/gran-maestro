---
name: settings
description: "Gran Maestro 설정을 조회하거나 변경합니다. 사용자가 '설정', '설정 변경', '환경 설정'을 말하거나 /mst:settings를 호출할 때 사용. 모드 전환에는 /mst:on 또는 /mst:off를 사용."
user-invocable: true
argument-hint: "[{key} [{value}] | preset {list|apply|diff|save|wizard} [id]]"
---

# maestro:config

`{PROJECT_ROOT}/.gran-maestro/config.json`의 설정을 조회하거나 변경합니다.

## 실행 프로토콜

<!-- @include _shared/path-rules.md -->
> **경로 규칙 (MANDATORY)**: 이 스킬의 모든 `.gran-maestro/` 경로는 **절대경로**로 사용합니다.
> 스킬 실행 시작 시 `PROJECT_ROOT`를 취득하고, 이후 모든 경로에 `{PROJECT_ROOT}/` 접두사를 붙입니다.
> ```bash
> PROJECT_ROOT=$(pwd)
> ```
>
> `{PLUGIN_ROOT}`는 이 스킬의 "Base directory"에서 `skills/{스킬명}/`을 제거한 **절대경로**입니다. 상대경로(`.claude/...`)는 절대 사용하지 않습니다.
<!-- @end-include -->

<!-- @include _shared/user-profile-read.md -->
### MANDATORY Read: `~/.claude/user-profile.json` (AskUserQuestion 컨텍스트, 비차단)

1. `~/.claude/user-profile.json`을 Read한다.
   - 파일이 없으면 `user_profile_context = null`로 처리하고 **기존 동작을 유지**한다 (graceful fallback).
2. 파일이 있으면 JSON을 파싱하고 아래 필드만 사용한다.
   - `role` (string)
   - `experience_level` (string)
   - `domain_knowledge` (string[])
   - `communication_style` (string)
3. JSON 파싱 실패 또는 타입 불일치 시 warn만 출력하고 `user_profile_context = null`로 처리한다 (워크플로우 차단 금지).
4. 이후 `AskUserQuestion`과 사용자 설명 텍스트 작성 시:
   - `communication_style`을 최우선 반영한다.
   - `experience_level`/`domain_knowledge`에 맞춰 용어 수준과 설명 깊이를 조절한다.
   - 누락 필드는 추정하지 않고, 존재하는 필드만 참고한다.
<!-- @end-include -->


1. 인자 없이 호출 시: 전체 설정 표시
2. key만 지정 시: 해당 설정값 표시
3. key와 value 모두 지정 시: 설정 변경
4. **MANDATORY (config 변경 후처리)**: `config.json`을 수정한 직후(예: key/value 변경, preset apply) 아래 명령을 실행한다.
   ```bash
   python3 {PLUGIN_ROOT}/scripts/mst.py config resolve || echo "[warning] config.resolved.json 갱신 실패. 수동으로 'python3 scripts/mst.py config resolve'를 실행하세요." >&2
   ```

## 설정 항목

| 키 | 설명 | 기본값 | 타입 |
|----|------|--------|------|
| `workflow.max_feedback_rounds` | 최대 피드백 반복 횟수 | `5` | number |
| `workflow.auto_approve_spec` | 스펙 자동 승인 여부 | `false` | boolean |
| `workflow.auto_accept_result` | Phase 3 리뷰 PASS 후 자동 수락 여부 | `true` | boolean |
| `workflow.auto_approve_on_unblock` | 의존성 해소 후 자동 approve 실행 여부 | `false` | boolean |
| `discussion.response_char_limit` | Discussion 라운드 응답 글자 제한 | `2000` | number |
| `discussion.critique_char_limit` | Discussion Critic 평가 글자 제한 | `2000` | number |
| `discussion.default_max_rounds` | Discussion 기본 최대 라운드 수 | `5` | number |
| `discussion.max_rounds_upper_limit` | Discussion 최대 라운드 상한 | `10` | number |
| `ideation.opinion_char_limit` | Ideation 의견 글자 제한 | `2000` | number |
| `ideation.critique_char_limit` | Ideation Critic 평가 글자 제한 | `2000` | number |
| `workflow.default_agent` | 기본 실행 에이전트 | `codex-dev` | string |
| `server.port` | 대시보드 포트 | `3847` | number |
| `server.host` | 대시보드 호스트 | `127.0.0.1` | string |
| `concurrency.max_parallel_tasks` | 최대 병렬 태스크 수 | `5` | number |
| `concurrency.max_parallel_reviews` | 최대 병렬 리뷰 수 | `3` | number |
| `concurrency.queue_strategy` | 큐 전략 | `fifo` | string |
| `timeouts.cli_default_ms` | CLI 기본 타임아웃 (ms) | `300000` | number |
| `timeouts.cli_large_task_ms` | 대규모 태스크 타임아웃 (ms) | `1800000` | number |
| `timeouts.pre_check_ms` | 사전 검증 타임아웃 (ms) | `120000` | number |
| `timeouts.merge_ms` | Merge 타임아웃 (ms) | `60000` | number |
| `worktree.root_directory` | worktree 루트 경로 | `.gran-maestro/worktrees` | string |
| `worktree.max_active` | 최대 활성 worktree 수 | `10` | number |
| `worktree.base_branch` | worktree 기준 브랜치 | `main` | string |
| `worktree.stale_timeout_hours` | stale 판정 시간 (시) | `24` | number |
| `retry.max_cli_retries` | 최대 CLI 재시도 횟수 | `2` | number |
| `retry.max_fallback_depth` | 최대 fallback 깊이 | `1` | number |
| `retry.backoff_base_ms` | 재시도 백오프 기준 (ms) | `1000` | number |
| `delegation.host` | host 감지/고정 (`auto` 권장) | `auto` | string |
| `delegation.default_provider` | 기본 위임 provider | `codex` | string |
| `agile.dispatch.provider` | Sprint dispatch provider | `codex` | string |
| `history.retention_days` | 이력 보존 기간 (일) | `30` | number |
| `history.auto_archive` | 자동 아카이브 | `true` | boolean |
| `ideation.agents.codex` | `{ count: 2, tier: "premium" }` | Ideation Codex 참여 설정 (0=제외) | object |
| `ideation.agents.gemini` | `{ count: 0, tier: "premium" }` | Ideation Gemini 참여 설정 (0=제외) | object |
| `ideation.agents.claude` | `{ count: 0, tier: "economy" }` | Ideation Claude 참여 설정 (0=제외) | object |
| `discussion.agents.codex` | `{ count: 2, tier: "premium" }` | Discussion Codex 참여 설정 (0=제외) | object |
| `discussion.agents.gemini` | `{ count: 0, tier: "premium" }` | Discussion Gemini 참여 설정 (0=제외) | object |
| `discussion.agents.claude` | `{ count: 0, tier: "economy" }` | Discussion Claude 참여 설정 (0=제외) | object |
| `notifications.terminal` | 터미널 알림 활성화 | `true` | boolean |
| `notifications.dashboard` | 대시보드 알림 활성화 | `true` | boolean |
| `debug.enabled` | 디버그 모드 | `false` | boolean |
| `debug.log_level` | 로그 레벨 | `info` | string |
| `debug.log_prompts` | 프롬프트 로깅 | `false` | boolean |
| `explore.agents.codex` | `{ count: 2, tier: "premium" }` | Explore Codex 탐색 에이전트 설정 (0=제외) | object |
| `explore.agents.gemini` | `{ count: 0, tier: "premium" }` | Explore Gemini 탐색 에이전트 설정 (0=제외) | object |
| `explore.agents.claude` | `{ count: 0, tier: "economy" }` | Explore Claude 탐색 에이전트 설정 (0=제외) | object |
| `auto_mode.plan` | `/mst:plan` Q&A 단계 자율 실행 (config 레벨 -a 활성화) | `false` | boolean |
| `auto_mode.request` | `/mst:request` 스펙 승인 자동 실행 (config 레벨 -a 활성화) | `false` | boolean |
| `auto_mode.review` | `/mst:review` fix 루프 자율 실행 (config 레벨 --auto 활성화) | `false` | boolean |
| `auto_mode.confidence_threshold` | PM 자율 판단 vs discussion 실행 경계값 (0.0~1.0) | `0.7` | number |
| `auto_mode.max_review_iterations` | 자율 review fix 루프 최대 반복 횟수 | `3` | number |

### debug.agents
| 키 | 기본값 | 설명 |
|---|---|---|
| `debug.agents.codex` | `{ count: 2, tier: "premium" }` | Debug 조사에 참여하는 Codex 에이전트 설정 (0=제외) |
| `debug.agents.gemini` | `{ count: 0, tier: "premium" }` | Debug 조사에 참여하는 Gemini 에이전트 설정 (0=제외) |
| `debug.agents.claude` | `{ count: 0, tier: "economy" }` | Debug 조사에 참여하는 Claude 에이전트 설정 (0=제외) |

- 총합: 1명 이상 6명 이하
- 프로바이더별 상한 없음
- 누락 시 기본값: `codex: { count: 2, tier: "premium" }`, `gemini: { count: 0, tier: "premium" }`, `claude: { count: 0, tier: "economy" }`

### config 마이그레이션

구 포맷(숫자) 설정을 신 포맷(객체)으로 변환:
```
python3 scripts/mst.py config migrate          # 변경 미리보기
python3 scripts/mst.py config migrate --apply   # 실제 적용
```

### preset 하위 명령

`/mst:settings preset <subcommand>` 형식으로 프리셋을 관리합니다.

#### preset list

프리셋 목록을 표시합니다.
- 실행: `python3 {PLUGIN_ROOT}/scripts/mst.py preset list`
- 출력: 내장 프리셋 12종 + 사용자 프리셋 목록

#### preset apply <preset_id>

프리셋을 현재 config에 적용합니다.
1. `python3 {PLUGIN_ROOT}/scripts/mst.py preset diff <preset_id>` 실행하여 변경 미리보기
2. AskUserQuestion으로 적용 확인
3. 확인 시 `python3 {PLUGIN_ROOT}/scripts/mst.py preset apply <preset_id>` 실행
4. 직후 `python3 {PLUGIN_ROOT}/scripts/mst.py config resolve || echo "[warning] config.resolved.json 갱신 실패. 수동으로 'python3 scripts/mst.py config resolve'를 실행하세요." >&2` 실행
5. 결과 표시

#### preset diff <preset_id>

프리셋 적용 시 변경될 항목을 미리 표시합니다 (적용하지 않음).
- 실행: `python3 {PLUGIN_ROOT}/scripts/mst.py preset diff <preset_id>`

#### preset save <preset_id>

현재 config를 사용자 프리셋으로 저장합니다.
- 실행: `python3 {PLUGIN_ROOT}/scripts/mst.py preset save <preset_id>`

#### preset wizard

대화형 위저드로 프리셋을 선택·적용합니다.
1. AskUserQuestion — AI 프로바이더 조합 선택 (Full / Codex Only / Gemini Only / Claude Only)
2. AskUserQuestion — 모델 등급 선택 (성능 / 효율 / 절약)
3. AskUserQuestion — 보조 도구 활성화 (multiSelect: Stitch 등)
→ 조합된 preset ID로 `preset apply` 실행

## 예시

```
/mst:settings                                        # 전체 설정 표시
/mst:settings workflow.max_feedback_rounds            # 특정 설정 조회
/mst:settings workflow.max_feedback_rounds 3          # 최대 피드백 3회로 변경
/mst:settings workflow.auto_approve_spec true         # 스펙 자동 승인 활성화
/mst:settings workflow.auto_accept_result false       # 최종 수락 수동 모드로 전환
/mst:settings workflow.auto_approve_on_unblock true  # 의존 체인 자동 실행 활성화
/mst:settings workflow.default_agent gemini-dev       # 기본 에이전트를 Gemini로 변경
/mst:settings auto_mode.plan true           # 플랜 Q&A 자율 실행 활성화
/mst:settings auto_mode.request true        # 스펙 승인 자동 실행 활성화
/mst:settings auto_mode.review true         # 리뷰 fix 루프 자율 실행 활성화
/mst:settings auto_mode.confidence_threshold 0.8  # PM 판단 신뢰도 임계값 상향
/mst:settings auto_mode.max_review_iterations 5   # 최대 리뷰 반복 5회로 변경
/mst:settings preset list                            # 프리셋 목록
/mst:settings preset apply full-performance          # 프리셋 적용
/mst:settings preset diff codex-only-budget          # 변경 미리보기
/mst:settings preset save my-config                  # 현재 설정 저장
/mst:settings preset wizard                          # 대화형 위저드
```

## 문제 해결

- "config.json 없음" → `/mst:on` 또는 `/mst:request`로 자동 생성
- "잘못된 키" → 점(`.`) 구분자로 중첩 접근 (예: `workflow.max_feedback_rounds`)
- "타입 불일치" → boolean은 `true`/`false`, number는 숫자만, string은 따옴표 없이
