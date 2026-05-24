---
name: priority
description: "태스크 우선순위 및 실행 순서를 변경합니다. 사용자가 '우선순위 변경', '순서 변경', '먼저 실행'을 말하거나 /mst:priority를 호출할 때 사용. 태스크 상태 확인에는 /mst:inspect를, 태스크 취소에는 /mst:cancel을 사용."
user-invocable: true
argument-hint: "{TASK-ID} --before {TASK-ID}"
---

# maestro:priority

PM이 자동 결정한 태스크 실행 순서를 사용자가 오버라이드합니다.

## 실행 프로토콜

태스크 ID + 순서 지정 파싱 → `execution_order` 배열 변경 → 종속성 충돌 확인 (blockedBy 위반 시 경고) → 변경 결과 표시

## 사용법

```
/mst:priority REQ-001-02 --before REQ-001-01    # 02를 01보다 먼저 실행
/mst:priority REQ-001-03 --after REQ-001-01     # 03을 01 다음에 실행
/mst:priority REQ-001 --reorder 03,01,02        # 전체 순서 지정
```

## 출력 형식

```
실행 순서 변경됨:

REQ-001 태스크 실행 순서:
  1. REQ-001-02  로그인 UI 구현 [gemini]
  2. REQ-001-01  JWT 미들웨어 구현 [codex]
  3. REQ-001-03  유저 모델 테스트 [codex]

주의: REQ-001-01은 REQ-001-03에 의존합니다.
```

## 문제 해결

- "태스크 ID를 찾을 수 없음" → `REQ-NNN-NN` 형식 확인; `/mst:inspect {REQ-ID}`로 목록 조회
- "종속성 충돌" → 경고만 표시되며 강제 적용; `/mst:inspect`로 종속성 그래프 사전 확인 권장
- "이미 실행 중인 태스크" → pending/queued 태스크만 순서 변경 가능
