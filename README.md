# Gran Maestro

[한국어](README.md) | [English](README.en.md)

> **"I am the Maestro — I conduct, I don't code."**

AI에게 모호한 요청을 던지면 빠르게 엉뚱한 결과가 나옵니다.
필요한 건 코드를 짜기 전, AI와 함께 계획을 세우는 단계입니다.
Gran Maestro는 그 계획 수립 단계에서 AI를 사고 파트너로 만들고, 검증된 계획을 자동으로 구현까지 이어주는 **plan 중심 end-to-end AI 오케스트레이션 플랫폼**입니다.

```bash
/plugin marketplace add myrtlepn/gran-maestro
```

![계획이 토론되고 검증되는 실제 화면](docs/assets/dashboard-ideation.png)

[Q&A 계획 수립](#기능-요약) | [다각도 브레인스토밍](#기능-요약) | [팀 토론](#기능-요약) | [UI 시각화](#기능-요약) | [코드 탐색](docs/skills-reference.md)

---

가장 중요한 것은 계획입니다. 기존 스펙 문서나 PRD는 작성과 구현 사이에 단절을 만듭니다. 문맥이 끊긴 채 구현에 들어가면, 시간과 집중과 신뢰를 함께 잃습니다. Gran Maestro는 **계획 → 스펙 작성 → 구현 → 검증 → 머지**의 전 과정을 하나의 흐름으로 연결합니다.

`/mst:plan`은 코드를 짜는 대신 핵심 결정을 질문으로 꺼냅니다. 답변이 돌아올 때마다 다음 질문이 구체화되어, 모호했던 요청이 실행 가능한 플랜으로 정제됩니다. 막히면 AI 팀이 다각도로 의견을 모으고(ideation), 합의에 도달할 때까지 토론합니다(discussion).

```
> /mst:plan "로그인 화면 개선해줘"

[PM] 두 가지 결정이 필요합니다:
  1. 소셜 로그인을 추가할까요, 기존 폼을 개선할까요?
  2. 세션 유지는 JWT로 바꿀까요?

> 막히면 ideation으로 AI 팀의 의견을 모을 수 있습니다.
```

텍스트만으로 합의하면 빈칸이 남습니다 — 화면은 Stitch로 즉석 시각화하고, 완성된 플랜은 다중 AI가 역할별로 검토합니다(Plan Review). 검증된 플랜은 `/mst:request`로 구현 스펙이 되고, `/mst:approve`로 Codex와 Gemini 개발팀에 전달되어 자동으로 구현됩니다. 구현이 끝나면 `/mst:review`가 AC 기준으로 검증하고, `/mst:accept`로 머지까지 완료됩니다. 대시보드에서 진행 상태와 근거를 실시간으로 확인할 수 있습니다. 아래 Quick Start에서 바로 시작하세요.

## Quick Start

**사전 요구사항**: Claude Code(v1.0.33 이상), [Codex CLI](https://github.com/openai/codex), [Gemini CLI](https://github.com/google-gemini/gemini-cli) — 멀티 에이전트 구현에 사용됩니다.

```bash
/plugin marketplace add myrtlepn/gran-maestro
/plugin install mst@gran-maestro
```

```
# 1. plan으로 상세화 → request로 스펙 생성
/mst:plan 로그인 화면 개선        # → PLN-001
/mst:request --plan PLN-001       # → REQ-001

# 2. 또는 바로 request (plan + spec 한번에)
/mst:request 대시보드 오류 수정   # → REQ-002

# 3. 스펙 확인 후 승인
/mst:list
/mst:approve REQ-001 REQ-002
```

상세 설치 가이드: [docs/quick-start.md](docs/quick-start.md)

## What's New

**0.54.x** 주요 업데이트:

- **적대적 검토(Adversarial Review) 게이트**: `/mst:plan`·`/mst:agile-plan`의 D3 Gate 직전과 `/mst:request`의 질문 생성 직전에, 독립 에이전트가 plan/objective를 적대적으로 검토해 사용자가 **놓친 엣지케이스·빠진 흐름·페르소나/NFR/통합 gap**을 찾아 DoD/AC에 보강합니다. 대시보드 Settings 탭 "적대적 검토" 섹션에서 전체/perspective별 on/off가 가능하고, config로는 `agile.adversarial_review.enabled=false`로 끌 수 있습니다.
- **Intent 시스템**: 기능 의도(JTBD)를 저장·추적하여 plan에서 구현·검증까지 의도 일관성을 보장합니다 (`/mst:intent`)
- **브라우저 UI 테스트**: UI 변경 시 plan/request/review에서 브라우저 테스트를 자동 연계하고, 스크린샷을 캡처·검증합니다
- **Q&A 컨텍스트 캡처**: 사용자 질문/답변을 자동 학습하여 선호 패턴을 축적, 반복 질문을 줄입니다
- **Gardening**: stale plan/request/intent를 자동 감지하여 리포트합니다 (`/mst:gardening`)
- **Chrome Extension picks**: 브라우저에서 UI 요소를 직접 캡처하고, `/mst:picks`로 선택하여 plan으로 전환할 수 있습니다

## 기능 요약

35개 이상의 스킬을 제공합니다.

**핵심 실행 체인**

| 기능 | 명령 | 용도 |
|------|------|------|
| Q&A 계획 수립 | `/mst:plan` | 질문으로 요구사항 정제, 검증된 플랜 생성 |
| 구현 스펙 작성 | `/mst:request` | 플랜을 구현 가능한 스펙(spec.md)으로 변환 |
| 스펙 승인 & 실행 | `/mst:approve` | 스펙 검증 후 Codex/Gemini 개발팀에 자동 전달 |
| AC 검증 리뷰 | `/mst:review` | 다중 AI가 수락 조건 기준으로 병렬 검증 |
| 머지 & 정리 | `/mst:accept` | worktree 머지 + 정리 완료 |

**협업 & 분석**

| 기능 | 명령 | 용도 |
|------|------|------|
| 다각도 브레인스토밍 | `/mst:ideation` | AI 팀이 병렬로 의견 수집, PM이 종합 |
| 팀 토론 | `/mst:discussion` | 합의에 도달할 때까지 반복 토론 |
| 버그 조사 | `/mst:debug` | 3 AI가 병렬로 버그 조사, 종합 리포트 |
| 기능 의도 관리 | `/mst:intent` | JTBD 기반 의도 저장·추적·검증 |

**도구 & 유틸리티**

| 기능 | 명령 | 용도 |
|------|------|------|
| UI 시각화 | `/mst:stitch` | Stitch로 UI 목업 즉석 생성 |
| 코드 탐색 | `/mst:explore` | 코드베이스 자율 탐색, 스펙 근거 확보 |
| 캡처 관리 | `/mst:picks` | Chrome Extension 캡처 선택 → plan 전환 |
| 대시보드 | `/mst:dashboard` | 대시보드 서버 시작/관리 |
| 정리 리포트 | `/mst:gardening` | stale plan/request/intent 자동 감지 |

전체 스킬 목록: [docs/skills-reference.md](docs/skills-reference.md)

## 문서

**시작하기**
- [빠른 시작 가이드](docs/quick-start.md) — 사전 요구사항, 설치, Stitch MCP 설정, 인증 방법
- [설정 관리](docs/configuration.md) — config.json 전체 옵션 레퍼런스
- [Chrome Extension 설치](docs/extension-setup.md) — 브라우저 캡처 확장 설치 가이드
- [에이전트 할당 설정](docs/config-agent-assignments.md) — 도메인별 에이전트 매핑 가이드

**심화**
- [스킬 레퍼런스](docs/skills-reference.md) — 35개 스킬 상세 사용법
- [대시보드](docs/dashboard.md) — 허브 구조, 뷰, API 엔드포인트
- [베스트 프랙티스](docs/best-practices.md) — 효율적인 워크플로우 패턴
- [OMX 가이드](docs/omx-guide.md) — oh-my-codex 설치, AGENTS.md 커스터마이징, 트리거 레퍼런스
- [Hook 설정](docs/HOOK-SETUP.md) — Git Hook 설정 가이드

**레퍼런스**
- [용어 사전](docs/glossary.md) — 공식 용어 및 ID 체계
- [변경 이력](CHANGELOG.md) — 버전별 변경사항

## 보안 및 민감정보 주의

**Dashboard 서빙**: 기본값으로 `127.0.0.1`(localhost-only)에 바인딩됩니다. 외부 네트워크로부터의 접근은 기본적으로 차단됩니다.

**flow-detail.ndjson 민감정보 경고**: `.gran-maestro/state/<session_id>/flow-detail.ndjson` 파일은 hook 자율 기록 로그로, **다음과 같은 민감정보를 포함할 수 있습니다**:
- 내부 파일/디렉토리 경로 (워크트리, 프로젝트 구조)
- 사용자 프롬프트 일부 및 `last_assistant_message` 발췌
- session_id, PPID 등 프로세스 식별자

의도치 않은 공유(gist, PR 첨부, 스크린샷, Slack 파일 업로드 등)를 피하고, 공유가 필요한 경우 해당 파일을 검토 후 필요한 부분만 발췌하십시오. `flow.ndjson`(스킬 레벨)은 상대적으로 민감도가 낮지만 동일 원칙 적용을 권장합니다.

## 운영 및 트러블슈팅

**오래된 아카이브 삭제**: `/mst:archive --purge`는 `.gran-maestro/*/archived/*.tar.gz` 중 retention 기간보다 오래된 파일을 삭제합니다. 신규 프로젝트 기본값은 `archive.archive_retention_days: 90`이며, 임시로 기준을 바꾸려면 `--max-age-days`를 사용합니다.

```bash
python3 scripts/mst.py archive purge --dry-run
python3 scripts/mst.py archive purge --max-age-days 30 --dry-run
python3 scripts/mst.py archive purge
```

먼저 `--dry-run`으로 삭제 대상을 확인한 뒤 실제 purge를 실행하세요. `archive_retention_days`는 아카이브를 만드는 시점의 보관 개수가 아니라, 이미 만들어진 tar.gz를 며칠 뒤 삭제할지 정하는 보존 기간입니다.

**진행 중 요청 보호**: cleanup/gardening은 `phase1_analysis`, `phase2_execution`, `phase3_review`, `merging`, `merge_conflict` 같은 active phase 요청을 오래되었다는 이유만으로 stale 후보에 넣지 않습니다. 보호 건수는 gardening scan 요약의 `protected_active_requests`에서 확인할 수 있습니다.

**MST session history ledger 조회**: 실행 중 PM flow의 MST 호출, skill lifecycle event, hook event는
`.gran-maestro/sessions/{mst_session_id}/history.*` 단일 ledger를 source of truth로 사용합니다.

```bash
python3 scripts/mst.py history log --session {mst_session_id}
python3 scripts/mst.py history verify --session {mst_session_id}
python3 scripts/mst.py history head --session {mst_session_id}
```

`history log`는 event row를 seq 순서로 검증해 표시하고, `history verify`/`history head`는 append-only
ledger tail과 `history.head`, policy mirror head, `history.verify`를 같은 `mst_session_id` 기준으로 대조합니다.
PPID, Claude hook `session_id`, `owner_session_id`, global hook ledger, default history는 fallback이 아닙니다.
`mst.py hook log`는 hook event 확인용 subset이며 canonical query는 `mst.py history ... --session`입니다.
이 조회 범위는 recover bundle restoration이나 dashboard/execution-flow projection 완료를 의미하지 않습니다.

## 라이선스

MIT License — 자세한 내용은 [LICENSE](LICENSE)를 참조하세요.
