# Gran Maestro 용어 사전

이 문서는 Gran Maestro 플러그인에서 사용하는 공식 용어를 정의합니다.
일관된 용어 사용으로 커뮤니케이션 혼란을 방지합니다.

## 핵심 용어

| 공식 용어 | 설명 | 사용 금지 대체어 |
|----------|------|----------------|
| **Gran Maestro** | 플러그인 전체 이름 | Maestro (단독 사용 시 혼동 가능) |
| **PM Conductor** | Phase 1/3에서 팀을 이끄는 AI 리더 | PM, Claude, Claude Code |
| **Analysis Squad** | Phase 1에서 코드베이스를 분석하는 팀 | 분석팀, Team |
| **Design Wing** | Phase 1에서 설계 문서를 작성하는 에이전트 그룹 | 설계팀 |
| **Review Squad** | Phase 3에서 코드를 검증하는 팀 | 리뷰팀, Team |
| **Outsource Brief** | Phase 2에서 CLI 에이전트에 전달하는 프롬프트 문서 | 외주 명세, 프롬프트 |
| **Feedback Composer** | Phase 4에서 리뷰 결과를 수정 지침으로 변환하는 에이전트 | — |

## Phase 용어

| 용어 | 설명 |
|------|------|
| **Phase 1: PM 분석** | 요구사항 분석, 스펙 작성, 작업 분할, 사용자 승인 |
| **Phase 2: 외주 실행** | `/mst:codex` / `/mst:agy` 스킬이 worktree에서 코드 구현 |
| **Phase 3: PM 리뷰** | 구현 결과 검증, 수락 조건 매핑, PASS/FAIL 판정 |
| **Phase 4: 피드백 루프** | 실패 유형 분류, 피드백 문서 작성, Phase 2 또는 1로 회귀 |
| **Phase 5: 수락/완료** | rebase + squash merge, worktree 정리, 알림 |

## ID 체계

| 패턴 | 설명 | 예시 |
|------|------|------|
| `REQ-NNN` | 사용자 원본 요청 | REQ-001 |
| `REQ-NNN-NN` | PM이 분할한 태스크 | REQ-001-02 |
| `REQ-NNN-NN-RN` | 피드백 리비전 | REQ-001-02-R1 |
| `PLN-NNN` | 플랜 세션 | PLN-001 |
| `DBG-NNN` | 디버그 세션 | DBG-001 |
| `IDN-NNN` | 아이디에이션 세션 | IDN-001 |
| `DSC-NNN` | 디스커션 세션 | DSC-001 |
| `EXP-NNN` | 탐색 세션 | EXP-001 |
| `DES-NNN` | 디자인 세션 | DES-001 |
| `RV-NNN` | 리뷰 회차 (REQ 하위) | RV-001 |

## 태스크 상태 (FSM)

| 상태 | 설명 | Phase |
|------|------|-------|
| `pending` | Phase 1에서 생성됨, 실행 대기 | 1 |
| `queued` | 실행 큐에 진입 (병렬 슬롯 대기) | 2 |
| `executing` | CLI 실행 중 | 2 |
| `pre_check` | 사전 검증 (타입체크/테스트) | 2 |
| `pre_check_failed` | 사전 검증 실패 | 2 |
| `committed` | Phase 2 구현 완료 + git commit 완료 (리뷰 대기) | 2→3 |
| `review` | PM 리뷰 중 | 3 |
| `feedback` | 피드백 작성 → 재실행 대기 | 4 |
| `merging` | rebase + merge 진행 중 | 5 |
| `merge_conflict` | 충돌 발생 → 해결 대기 | 5 |
| `done` | 완료 (merged) | 5 |
| `failed` | 시스템 오류로 실패 | — |
| `cancelled` | 사용자 취소 | — |

## 에이전트 유형

| 유형 | agents.json 키 | 제공자 | Phase |
|------|---------------|--------|-------|
| 실행 에이전트 | `codex-dev`, `agy-dev` | `/mst:codex` / `/mst:agy` | 2 |
| 리뷰 에이전트 | `codex-reviewer`, `agy-reviewer` | `/mst:codex` / `/mst:agy` | 3 |
| 분석 에이전트 | `architect`, `schema-designer`, `ui-designer` | Claude Code | 1 |

## 모드

| 모드 | 설명 |
|------|------|
| **Maestro 모드** | Gran Maestro 활성. Claude Code는 PM 역할만 수행 |
