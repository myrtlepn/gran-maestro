# cache_control.ttl=1h 설정 노출 여부 조사 리포트

> **조사일**: 2026-04-17  
> **목적**: Claude Code 및 Anthropic API/SDK가 `cache_control.ttl=1h` 설정을 사용자/플러그인 레벨에서 노출하는지 1차 소스 기반으로 확인하고, Gran Maestro 워크플로우에서의 적용 가이드를 제시한다.  
> **연관**: REQ-632 / PLN-476 / `docs/analysis/2026-04-prompt-cache-cost.md`  
> **상태**: 1차 조사 완료 (2026-04-17)

---

## 요약

> **최종 결론: 노출됨** — Claude Code 레벨에서 환경 변수(`ENABLE_PROMPT_CACHING_1H=true`) 경로로, API/SDK 레벨에서 `cache_control.ttl=1h` 파라미터로 노출됨. 단, Gran Maestro 플러그인 hook이나 settings.json을 통한 직접 제어는 현재 지원되지 않는다.

---

## 조사 방법 및 소스

아래 1차 소스 4종을 직접 조사하였다.

| 소스 | URL | 조사 내용 |
|------|-----|---------|
| Anthropic 프롬프트 캐싱 공식 문서 | https://platform.claude.com/docs/en/build-with-claude/prompt-caching | `cache_control` 파라미터 스키마 및 TTL 옵션 확인 |
| Anthropic Messages API 문서 | https://docs.anthropic.com/en/api/messages | API 레벨 `cache_control` 파라미터 정의 및 `ttl` 필드 지원 여부 |
| Claude Code GitHub 리포지터리 / 이슈 | https://github.com/anthropics/claude-code | env var 노출 여부, 이슈 #46829 (TTL regression 2026-03) |
| Claude Code 공식 문서 (changelog) | https://code.claude.com/docs/en/changelog | 환경 변수 `ENABLE_PROMPT_CACHING_1H` 확인 (2026-04-14 기준) |

추가 참고 (보조):
- Anthropic TypeScript SDK 이슈: https://github.com/anthropics/anthropic-sdk-typescript/issues/793

---

## 소스별 조사 결과

### 1. Anthropic Messages API 레벨

출처: https://docs.anthropic.com/en/api/messages

`cache_control` 파라미터는 다음 스키마로 정의된다:

```json
{
  "cache_control": {
    "type": "ephemeral",
    "ttl": "1h"
  }
}
```

- `ttl` 필드 허용값: `"5m"` (기본값, 5분) / `"1h"` (1시간 확장 캐시)
- API Key 사용자는 요청 본문에 `ttl: "1h"` 명시로 즉시 1h TTL 적용 가능

**결론: 노출됨** — API 직접 호출 시 사용자가 TTL을 완전히 제어 가능.

---

### 2. Python / TypeScript SDK 레벨

출처: https://platform.claude.com/docs/en/build-with-claude/prompt-caching

**Python SDK 예시:**

```python
import anthropic

client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-opus-4-7",
    system=[{
        "type": "text",
        "text": "Your system prompt here",
        "cache_control": {"type": "ephemeral", "ttl": "1h"}
    }],
    messages=[{"role": "user", "content": "Hello"}],
    max_tokens=4096
)
```

출처(보조): https://github.com/anthropics/anthropic-sdk-typescript/issues/793

**TypeScript SDK 예시:**

```typescript
const response = await client.messages.create({
  model: "claude-opus-4-7",
  system: [{
    type: "text",
    text: "Your system prompt here",
    cache_control: { type: "ephemeral", ttl: "1h" }
  }],
  messages: [{ role: "user", content: "Hello" }],
  max_tokens: 4096
});
```

**결론: 노출됨** — Python/TypeScript SDK 모두 `cache_control.ttl=1h` 파라미터 지원.

---

### 3. Claude Code (CLI/IDE 도구) 레벨

출처: https://code.claude.com/docs/en/changelog (버전 2.1.108, 2026-04-14)  
출처: https://github.com/anthropics/claude-code (이슈 #46829, TTL regression)

Claude Code는 내부적으로 자동 캐시를 관리하며, 사용자/플러그인이 `cache_control.ttl`을 직접 주입하는 설정 인터페이스(settings.json, hook 파라미터 등)는 제공하지 않는다. 그러나 **환경 변수**를 통한 사용자 레벨 노출이 확인되었다.

```bash
# 1시간 TTL 활성화 (API Key / Pro / Bedrock / Vertex / Foundry 사용자)
export ENABLE_PROMPT_CACHING_1H=true

# 5분 TTL 강제 적용 (기본 동작으로 복원)
export FORCE_PROMPT_CACHING_5M=true
```

| 구독 플랜 | 기본 TTL | 1h TTL 활성화 방법 |
|-----------|---------|------------------|
| Max plan | **1시간** (기본 활성화) | 별도 설정 불필요 |
| Pro plan | 5분 | `ENABLE_PROMPT_CACHING_1H=true` 설정 |
| API Key 사용자 | 5분 | `ENABLE_PROMPT_CACHING_1H=true` 설정 |

**제약**:
- `settings.json` 또는 플러그인 hook(SessionStart/Stop/PreToolUse/PostToolUse/PreCompact 등)에서 `cache_control.ttl`을 직접 주입하는 공식 인터페이스 없음
- 환경 변수는 프로세스 시작 시점에만 적용 (세션 중 동적 변경 불가)
- Gran Maestro 플러그인이 hook을 통해 Claude Code 내장 캐시 TTL을 제어하는 경로는 현재 노출되어 있지 않음

**결론: 노출됨 (환경 변수 경로)** — plugin hook/settings.json 경로는 지원 안됨.

---

## 최종 결론 요약

> **결론: 노출됨** (레벨별 차등 지원)

| 접근 경로 | 노출 여부 | 방법 |
|-----------|---------|------|
| Anthropic Messages API 직접 호출 | **노출됨** | `"cache_control": {"type": "ephemeral", "ttl": "1h"}` |
| Python SDK | **노출됨** | `cache_control={"type": "ephemeral", "ttl": "1h"}` |
| TypeScript SDK | **노출됨** | `cache_control: { type: "ephemeral", ttl: "1h" }` |
| Claude Code 환경 변수 | **노출됨** | `ENABLE_PROMPT_CACHING_1H=true` |
| Claude Code settings.json | **노출 안됨** | 현재 공식 인터페이스 없음 |
| Claude Code plugin hook | **노출 안됨** | 현재 공식 인터페이스 없음 |

Gran Maestro 플러그인 관점에서는 **환경 변수 설정 경로**가 현재 가장 현실적이고 즉시 적용 가능한 무코드 경로다. 직접 API wrapper 경로(경로 B)는 workspace isolation 이슈를 수반한다.

---

## 적용 가이드

### 경로 A: 환경 변수 설정 (권장 — 즉시 적용 가능, 코드 변경 없음)

**설정 위치**: 사용자 쉘 프로파일

```bash
# ~/.zshrc 또는 ~/.bashrc 에 추가
export ENABLE_PROMPT_CACHING_1H=true
```

또는 Claude Code 실행 시 일회성 적용:

```bash
ENABLE_PROMPT_CACHING_1H=true claude
```

**효과**: Claude Code 세션 전체의 자동 캐시가 1h TTL로 전환 → Gran Maestro 모든 워크플로우(agile/review/discussion 등)에서 외부 CLI 대기(최대 30분) 후에도 cache hit 유지.

**제약**:
- Pro plan / API Key 사용자에게만 필요 (Max plan 구독자는 기본 1h TTL 활성화 상태)
- Claude Code 버전 2.1.108 이상 (2026-04-14 기준 changelog)
- 1h TTL 캐시 쓰기는 5m TTL 대비 **추가 단가 프리미엄** 적용 (정확한 배율은 https://www.anthropic.com/pricing 교차 확인 필요; PLN-476은 "2x 단가" 언급)

### 경로 B: Anthropic SDK 직접 호출 (Gran Maestro wrapper)

Gran Maestro의 `mst.py` 또는 스킬에서 Claude Code 내장 캐시 대신 **Anthropic Python SDK로 직접 API 호출** 시 `cache_control.ttl=1h`를 명시적으로 지정 가능.

```python
# scripts/ 내 wrapper 활용 시 참고 패턴
import anthropic

client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-opus-4-7",
    system=[{
        "type": "text",
        "text": system_prompt,
        "cache_control": {"type": "ephemeral", "ttl": "1h"}
    }],
    messages=conversation_history,
    max_tokens=4096
)
```

**제약 — workspace isolation**:
- Claude Code가 관리하는 내장 세션 컨텍스트와 분리된 독립 API 호출
- Claude Code의 자동 캐시(시스템 프롬프트 + 대화 이력)와 공유되지 않음 → 대화 이력 직접 관리 필요
- Gran Maestro의 현재 아키텍처(mst.py → Claude Code 세션 위임)와 충돌 가능성
- 실제 구현 시 별도 REQ로 분리 권장

---

## PoC 측정

> **방법**: 이론 계산 (실측 미수행, 2026-04-17 기준). 실측은 Anthropic console 청구 로그에서 수행 권장.

### 5m TTL vs 1h TTL 비용 비교 (Scenario 1: 30분 대기, Opus, 1.5 MTok)

**가정**:
- 세션 캐시 prefix: 1.5 MTok
- 외부 CLI 대기: 30분 (`cli_large_task_ms`)
- Opus 기본 입력 단가: $15.00/MTok
- 5m TTL 캐시 쓰기: 1.25× ($18.75/MTok), 캐시 읽기: 0.10× ($1.50/MTok)
- 1h TTL 캐시 쓰기: 2.50× 추정 ($37.50/MTok; PLN-476 "2x 단가" 근거), 캐시 읽기: 0.10× 동일

출처: https://platform.claude.com/docs/en/build-with-claude/prompt-caching

| 항목 | 5m TTL (기존) | 1h TTL (적용 후) |
|------|--------------|----------------|
| 캐시 쓰기 단가 | 1.25× ($18.75/MTok) | 2.50× ($37.50/MTok) *추정* |
| 30분 대기 후 cache 상태 | **MISS** (TTL 만료) | **HIT** (TTL 이내) |
| 캐시 쓰기 비용 (1.5 MTok, 1회) | $28.13 | $56.25 |
| 재개 후 입력 처리 비용 | $22.50 (base input, miss) | $2.25 (cache read, hit) |
| **1회 왕복 총 입력 비용** | **$50.63** | **$58.50** |

> ⚠️ 1h TTL 쓰기 단가는 PLN-476 "2x 단가" 언급 기반 추정. 실제 단가는 https://www.anthropic.com/pricing 교차 확인 필요.

### 손익분기점 계산 (동일 캐시 블록 재사용 횟수 기준)

```
5m TTL 총비용  = write(1.25×) + N × miss(1.00×)
1h TTL 총비용  = write(2.50×) + N × read(0.10×)

1h TTL이 유리한 조건:
  2.50 + 0.10N < 1.25 + 1.00N
  1.25 < 0.90N
  N > 1.39  →  N ≥ 2 (재개 2회부터 1h TTL이 경제적)
```

→ **동일 시스템 프롬프트로 2회 이상 세션을 재개하면 1h TTL이 write 프리미엄을 상쇄하고 경제적이다.** Gran Maestro의 agile/review 루프(시나리오 4, 10회 cache miss 예상)에서는 1h TTL 적용이 명확히 유리.

### 시나리오 4 누적 비교 (agile 5 Sprint × 2 CLI, Opus, 3.0 MTok)

| 항목 | 5m TTL | 1h TTL |
|------|--------|--------|
| 10회 cache miss 추가 비용 | **$405.00** | ~$0 (모두 HIT) |
| write 프리미엄 차이 (1회, 3 MTok) | — | +$84.38 (추가 쓰기 비용) |
| **누적 절감 (10회 기준)** | — | **약 $320 절감** |

→ agile 루프에서 1h TTL 적용 시 Sprint당 Opus $32 이상 절감 기대.

---

## 지금 시점 권장 조치

> **[2026-04-17 기준]** Pro plan / API Key 사용자는 쉘 프로파일에 `export ENABLE_PROMPT_CACHING_1H=true`를 즉시 추가하라 — Max plan 구독자는 기본 활성화 상태이며, Gran Maestro 플러그인 hook 경로로는 현재 TTL 제어가 불가하므로 환경 변수 설정이 무코드 적용의 유일한 경로다.

---

## 참고 자료 (REF)

| REF ID | 내용 | URL |
|--------|------|-----|
| REF-009 | Anthropic prompt cache sliding TTL — refresh on each access (5m 기본, 1h 선택) | https://platform.claude.com/docs/en/build-with-claude/prompt-caching |
| REF-001 | Anthropic prompt caching TTL 정책 2026 | https://platform.claude.com/docs/en/build-with-claude/prompt-caching |
| REF-002 | Claude Code cache TTL regression 2026-03 (1h→5m silent downgrade) | https://github.com/anthropics/claude-code/issues/46829 |
