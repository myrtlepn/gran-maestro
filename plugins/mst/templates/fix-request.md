# Fix Request — Self-Exploration Mode

- Request: {{REQ_ID}} / Task: {{TASK_ID}} / Round: {{ROUND_NUM}}
- Worktree: {{WORKTREE_PATH}}
- Review Report: {{REVIEW_REPORT_PATH}}
- Spec: {{SPEC_PATH}}

## 수정 컨텍스트 (PM 작성 — 3~5줄 자유 형식)

{{FIX_CONTEXT}}

## 자기탐색 지시

아래 순서로 리뷰 결과를 직접 탐색하라. PM 요약 없이 원본 파일을 직접 읽어라.

1. 리뷰 리포트 직접 읽기: `cat {{REVIEW_REPORT_PATH}}` (또는 Read 도구)
2. 스펙 직접 읽기: `cat {{SPEC_PATH}}` (또는 Read 도구)
3. FAIL/PARTIAL 항목을 식별하고 수정
4. §5 테스트 명령어를 실행하고 출력 전체를 응답에 포함하세요 (커밋은 PM이 처리)

## 이전 피드백 (2라운드 이상 시)

{{PREV_FEEDBACK_PATH}}

(1라운드: N/A — 이 섹션을 무시하라)

## 규칙

- 리뷰에서 지적된 사항만 수정
- 새 기능/리팩토링 금지
- git commit은 하지 마세요 — PM이 직접 커밋합니다
- 수락 조건 재검증 후 §5 테스트 명령어를 실행하고 출력 전체를 응답에 포함하세요
