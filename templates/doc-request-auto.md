# Documentation Request — Self-Exploration Mode (Auto)

- Request: {{REQ_ID}} / Task: {{TASK_ID}}
- Worktree: {{WORKTREE_PATH}}
- Spec: {{SPEC_PATH}}
- Plan: {{PLAN_PATH}}

## 문서 컨텍스트 (PM 작성)

{{DOC_CONTEXT}}

## 자기탐색 지시

아래 순서로 스펙을 직접 탐색하라. PM이 제공한 요약에 의존하지 말고 원본 파일을 직접 읽어라.

0. `{{SPEC_PATH}}`의 `## §0 Context Manifest` 섹션을 확인하고, 나열된 파일 목록을 문서 작성 전 가장 먼저 Read하라 (목록이 비어있거나 파일이 없으면 경고 후 다음 단계 진행)
1. 스펙 직접 읽기: `cat {{SPEC_PATH}}` (또는 Read 도구)
1.1. plan 직접 읽기 (source_plan이 있는 경우만): `{{PLAN_PATH}}`가 `"N/A"`가 아니면 `cat {{PLAN_PATH}}` (또는 Read 도구), `"N/A"`면 source_plan 없음으로 보고 이 단계를 skip
2. `§2 변경 범위`와 `§3 수락 조건`에서 문서 대상 파일/섹션, TOC, 소스 목록, 검증 계획을 추출하라
3. 변경사항 수집: `git log`로 최신 변경사항을 수집하고 문서 목적(README/CHANGELOG/Release Notes)에 맞게 분류하라
4. 코드 구조 스캔: `ls`와 디렉토리 구조 스캔으로 현재 코드베이스 정보를 수집하고 문서 구조에 반영하라
5. 초안 작성: 수집한 변경/구조 정보를 정리하여 섹션별 본문을 작성하고 근거 소스를 연결하라
6. 구조 검증: 헤딩 체계(H1/H2/H3), 섹션 순서, TOC 대비 누락 여부를 점검하고 수정하라
7. 팩트체크/검증 분기: `sub_type=auto` (`verification=auto_extraction`) 규칙으로 claim 단위 `verified|failed|unverified` 판정 후 근거를 기록하라. 실패/미확정 claim은 재작성 후 재검증하라
   - `freshness_current`: 날짜/버전 정보가 최신 변경사항과 일치하는가
   - `install_commands_valid`: 설치/초기화 명령어가 유효한가
8. [MANDATORY] 최종 응답에 "git log 수집 → 코드 구조 스캔 → 최신성/명령어 검증" 결과를 순서대로 요약해 포함하라 (커밋은 PM이 처리)

## 이전 피드백 (Phase 4 → 재실행 시)

{{PREV_FEEDBACK_PATH}}

(첫 실행 시: N/A — 이 섹션을 무시하라)

## 규칙

- spec §2의 변경 범위 외 파일 수정 금지
- 추가 기능, 리팩토링, 스타일 변경 금지
- git commit은 하지 마세요 — PM이 직접 커밋합니다
- [MANDATORY] 자동 수집 검증 결과(최신성, 설치 명령어 유효성)와 claim별 판정(verified/failed/unverified)을 응답에 포함하세요
- 불확실한 내용은 단정하지 말고 `failed` 또는 `unverified`로 표시하세요
