# Completion Summary - {REQ_ID}

- Title: {요청 제목}
- Completed: {DATE}
- Total Duration: {총 소요 시간}
- Feedback Rounds: {피드백 횟수}

## 요청 개요

{사용자의 원본 요청 요약}

## 완료된 태스크

| Task ID | 설명 | Agent | 소요 시간 | Feedback |
|---------|------|-------|----------|----------|
| {TASK_ID} | {설명} | {agent} | {시간} | {횟수}회 |

## 변경 요약

- 변경 파일: {N}개
- 추가: +{N} lines
- 삭제: -{N} lines
- 신규 파일: {목록}
- 수정 파일: {목록}
- 삭제 파일: {목록}

## 수락 조건 최종 결과

- [x] AC-1: {설명} — 통과
- [x] AC-2: {설명} — 통과
- [x] AC-3: {설명} — 통과

## 에이전트 활용 요약

| Agent | 역할 | 호출 횟수 | 총 소요 시간 |
|-------|------|----------|-------------|
| codex-dev | 코드 구현 | {N} | {시간} |
| gemini-dev | UI 구현 | {N} | {시간} |
| codex-reviewer | 코드 검증 | {N} | {시간} |

## Phase별 소요 시간

| Phase | 설명 | 소요 시간 |
|-------|------|----------|
| Phase 1 | PM 분석 | {시간} |
| Phase 2 | 외주 실행 | {시간} |
| Phase 3 | PM 리뷰 | {시간} |
| Phase 4 | 피드백 | {시간} (총 {N}회) |
| Phase 5 | 수락/완료 | {시간} |

## Git 정보

- Merge: squash merge to {branch}
- Commit: {commit hash}
- Branch cleanup: {삭제된 브랜치 목록}

## 교훈 (Lessons Learned)

{PM이 이번 요청에서 배운 점, 다음에 개선할 점}
