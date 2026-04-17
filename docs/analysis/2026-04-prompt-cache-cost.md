# Anthropic Prompt Cache 비용 분석: Gran Maestro 외부 CLI 대기 패턴의 영향

> **작성일**: 2026-04-17  
> **목적**: Anthropic prompt cache 5분 TTL과 Gran Maestro의 외부 CLI 대기·dispatch 패턴이 결합될 때 발생하는 캐시 회전 비용을 정량화하여, 후속 mst:request 최적화 우선순위 결정의 근거 자산으로 사용한다.  
> **상태**: 이론 계산 (실측 미수행) — `## 가정과 한계` 섹션 참조

---

## 메커니즘

### Anthropic Prompt Cache TTL

Anthropic은 API 레벨에서 prompt cache prefix matching을 지원한다. 2026-04-17 기준 TTL 정책은 다음과 같다.

| 항목 | 값 | 출처 |
|------|-----|------|
| 기본 TTL | **5분** (300초) | [platform.claude.com/docs prompt-caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) |
| 명시 TTL | **1시간** (3600초) (`cache_control.ttl=3600` 지정 시) | 위 동일 |
| TTL 하향 이력 | 2026-03-06경 1h → 5m silent downgrade 확인 | [github.com/anthropics/claude-code/issues/46829](https://github.com/anthropics/claude-code/issues/46829) |

> ⚠️ **TTL 하향 이력**: REF-002에 따르면 Anthropic은 2026-03-06경 기본 TTL을 1시간에서 5분으로 예고 없이 하향했다. Claude Code 자동 캐시는 TTL 지정 없이 기본값(5분)을 사용한다. 정책 재변경 가능성이 있으므로 본 분석의 모든 수치는 **2026-04-17 기준**으로 시점을 고정한다.

### Cache Write / Read 단가

cache prefix matching은 **최소 1,024 토큰** 이상의 prefix에 적용된다. 단가 구조 (2026-04-17 기준, 출처: [platform.claude.com/docs prompt-caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)):

| 항목 | 배수 | Claude Opus (추정) | Claude Sonnet (추정) |
|------|------|---------------------|----------------------|
| 기본 Input | 1.00× | $15.00/MTok | $3.00/MTok |
| Cache Write | **1.25×** | $18.75/MTok | $3.75/MTok |
| Cache Read (HIT) | **0.10×** | $1.50/MTok | $0.30/MTok |

> 모델 단가는 2026-04-17 기준 추정치. Opus = claude-opus-4-7, Sonnet = claude-sonnet-4-6 기준.  
> 최신 단가는 [anthropic.com/pricing](https://www.anthropic.com/pricing)에서 반드시 교차 확인하라.

**Cache miss 추가 비용 (1회, per MTok)**:

```
cache_miss_extra = (base_input - cache_read) × prompt_size
                 = (1.00 - 0.10) × base_input × prompt_size
                 = 0.90 × base_input × prompt_size
```

- Opus: 0.90 × $15.00 = **$13.50/MTok**
- Sonnet: 0.90 × $3.00 = **$2.70/MTok**

### Prefix Matching 동작

- Anthropic은 **최장 일치 prefix**를 캐시 단위로 사용한다. 시스템 프롬프트와 대화 이력의 앞부분이 변경 없이 유지되면 cache hit이 발생한다.
- Cache prefix는 **변경 불가** 순서로 고정되어야 하며, 중간 삽입 시 이후 전체가 cache miss로 처리된다.
- Claude Code는 세션 내부적으로 자동 캐시를 사용하며, 사용자가 TTL을 직접 제어할 수 없다 (기본 5분 적용).
- 메인 PM 세션이 외부 CLI 응답을 기다리는 동안 세션은 유휴(idle) 상태이며, 이 시간이 5분을 초과하면 cache가 만료된다.

---

## 설정값 매핑

### Gran Maestro 타임아웃 값과 5분 TTL 경계 비교

| 설정 키 | 값 (ms) | 초 | 분 | TTL 대비 | Cache Hit 가능성 |
|---------|---------|-----|-----|----------|-----------------|
| `timeouts.cli_default_ms` | 300,000 | 300s | 5분 | **= TTL 경계** | 대기 시작 시점에 따라 miss 가능 (마진 0초) |
| `timeouts.wait_files_ms` | 600,000 | 600s | 10분 | **TTL 2배** | 5분 초과 — cache miss **확실** |
| `timeouts.merge_ms` | 600,000 | 600s | 10분 | **TTL 2배** | 5분 초과 — cache miss **확실** |
| `timeouts.cli_large_task_ms` | 1,800,000 | 1800s | 30분 | **TTL 6배** | 5분 초과 — cache miss **확실** |
| `timeouts.pre_check_ms` | 120,000 | 120s | 2분 | TTL의 0.4배 | 5분 이내 — cache hit **가능** |

> 출처: `.gran-maestro/config.resolved.json`, `timeouts` 섹션 (2026-04-17 기준 실측값)

### Dispatch 패턴별 캐시 영향

| Dispatch 패턴 | 발생 컨텍스트 | 대기 유형 | TTL 노출 | Cache Miss 위험 |
|--------------|-------------|----------|----------|----------------|
| 순차 단일 CLI (`mst.py run`) | request 워크플로우 (codex/gemini 단독 실행) | 동기 블록킹 | cli_default_ms 또는 cli_large_task_ms | 높음 (대기=30분) |
| 병렬 Bash dispatch | discussion/ideation/debug/explore | 동기 블록킹 (완료 대기) | 가장 오래 걸리는 태스크 기준 | 높음 (max 15~30분) |
| 파일 heartbeat 모니터링 | dispatch.py `cmd_dispatch_build` 패턴 | 폴링 대기 | wait_files_ms = 10분 | 중간~높음 |
| pre_check 단독 | 사전 검증 단계 | 동기 블록킹 | 2분 | 낮음 (TTL 이내) |

> 핵심 발견: `cli_default_ms = 300,000 ms`는 정확히 5분 TTL 경계와 일치한다. 외부 CLI가 deadline에 가까울 때 cache miss가 발생할 수 있다. `cli_large_task_ms = 1,800,000 ms`는 TTL의 6배로 cache miss가 구조적으로 보장된다.

### dispatch.py 동기 대기 확인

`scripts/mst_cmds/dispatch.py`의 `cmd_dispatch_build` 함수는 다음 셸 파이프라인을 생성한다:

```bash
{register_cmd};
set -o pipefail;
{cli_cmd} < /dev/null 2>&1 | tee {log_file};   # ← 블록킹 실행
EC=${PIPESTATUS[0]};
{heartbeat_cmd};
exit $EC
```

`SKILL.md`의 `mst.py run -- codex exec ...` 또는 `-- gemini -p ...` 호출도 마찬가지로 동기 블록킹이다. **메인 Claude Code 세션은 외부 CLI 프로세스가 종료될 때까지 응답을 생성하지 않으며**, 이 idle 기간 전체가 cache TTL 소비 시간이 된다.

---

## 시나리오 비용

> **공통 가정**: 2026-04-17 기준 공식 Anthropic 단가 구조 적용 (cache read = 0.10×, cache write = 1.25×, base input 1.00×). 모든 시나리오는 이론 계산이며 실측 미수행.

### 시나리오 1: 메인 PM 세션이 외부 CLI 대기 (cli_large_task_ms)

**가정**:
- 메인 세션 캐시 prefix 크기: **1.5 MTok** (시스템 프롬프트 ~500K + 대화 이력 + 현재 REQ 파일 컨텍스트)
- 외부 CLI (codex/gemini) 대기 시간: **30분** (`cli_large_task_ms = 1,800,000 ms`)
- 5분 TTL → 대기 종료 후 메인 세션 재개 시 cache miss 1회 발생

**계산식**:
```
cache_miss_extra = (base_input - cache_read) × prompt_size
                 = (1.00 - 0.10) × base_input × 1.5 MTok
```

| 모델 | Base Input | Cache Read (HIT) | Cache Miss | 추가 비용 (1회 cache miss) |
|------|-----------|-----------------|------------|--------------------------|
| Opus | $15.00/MTok | $2.25 | $22.50 | **+$20.25** |
| Sonnet | $3.00/MTok | $0.45 | $4.50 | **+$4.05** |

→ Opus 기준 **30분 대기 1회**로 $20.25 손실. request 10회면 $202.50.

---

### 시나리오 2: 메인 세션이 서브스킬 결과 파일 대기 (wait_files_ms)

**가정**:
- 서브스킬(codex review/gemini analysis) 결과 파일 대기: **10분** (`wait_files_ms = 600,000 ms`)
- 메인 세션 캐시 prefix 크기: **2.0 MTok** (discussion/ideation 실행 후 누적 컨텍스트 포함)
- 대기 10분 = TTL 2배 → cache miss 1회 발생

**계산식**:
```
cache_miss_extra = 0.90 × base_input × 2.0 MTok
```

| 모델 | Base Input | Cache Read (HIT) | Cache Miss | 추가 비용 (1회 cache miss) |
|------|-----------|-----------------|------------|--------------------------|
| Opus | $15.00/MTok | $3.00 | $30.00 | **+$27.00** |
| Sonnet | $3.00/MTok | $0.60 | $6.00 | **+$5.40** |

→ Sonnet을 PM 모델로 사용해도 **서브스킬 대기 1회**마다 $5.40 추가 비용. discussion 5회이면 $27.00.

---

### 시나리오 3: 병렬 dispatch 중 메인 대기 (discussion/ideation/debug)

**가정**:
- 병렬 dispatch: `discussion` 설정 기준 — codex ×3, gemini ×2, claude ×3 = 최대 8개 동시 실행
- 각 에이전트 평균 실행 시간: **15분** (Longest task 기준, 3× TTL)
- 메인 세션 캐시 prefix 크기: **1.0 MTok** (discussion 시작 시점, 비교적 초기 컨텍스트)
- 병렬 완료 대기 = 가장 느린 에이전트 완료 시까지 → cache miss 1회

**계산식**:
```
cache_miss_extra = 0.90 × base_input × 1.0 MTok
```

| 모델 | Base Input | Cache Read (HIT) | Cache Miss | 추가 비용 (1회 cache miss) |
|------|-----------|-----------------|------------|--------------------------|
| Opus | $15.00/MTok | $1.50 | $15.00 | **+$13.50** |
| Sonnet | $3.00/MTok | $0.30 | $3.00 | **+$2.70** |

추가 고려: 병렬 에이전트 8개 각각도 자체 캐시를 사용한다. 각 sub-Claude 세션 역시 독립적인 cache miss 위험에 노출되지만, 본 시나리오에서는 **메인 PM 세션만** 산정한다.

→ ideation/discussion을 포함한 워크플로우 1사이클마다 Opus 기준 최소 **$13.50** 추가.

---

### 시나리오 4: review/agile 루프 반복 누적

**가정**:
- agile 루프: `workflow.max_feedback_rounds = 5`, `review.max_iterations = 10`
- 각 Sprint round에서 외부 CLI 2회 실행 (codex 구현 + gemini 리뷰)
- 외부 CLI 1회 실행 평균 대기: **20분** (cli_large_task_ms 범위)
- 메인 세션 컨텍스트 크기: Sprint 진행에 따라 점증, 평균 **3.0 MTok** (누적 review 피드백 포함)
- 총 cache miss 횟수: 5 Sprint × 2 CLI/Sprint = **10회**
- (보수적 가정: Sprint 간 메인 세션 재개 시 항상 cache miss)

**계산식**:
```
total_cost_extra = 0.90 × base_input × 3.0 MTok × 10회
```

| 모델 | 1회 cache miss 추가 비용 | 10회 누적 추가 비용 | 만약 hit이었다면 (10회) |
|------|------------------------|-------------------|----------------------|
| Opus | $40.50 | **$405.00** | $45.00 |
| Sonnet | $8.10 | **$81.00** | $9.00 |

→ **최대 비용 비율**: agile 5라운드 누적 cache miss = cache hit 대비 Opus는 **9×**, Sonnet은 **9×** 비용 증가.  
→ `agile.retrospective` 포함 시 추가 review CLI 실행이 더해져 실제 누적 비용은 더 높을 수 있다.

---

## 완화 옵션

### 옵션 A: 1시간 TTL 명시 캐시 사용

**설명**: Anthropic API의 `cache_control.ttl=3600` 파라미터를 사용하여 캐시 TTL을 1시간으로 명시 설정한다. 출처: [platform.claude.com/docs prompt-caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

| 항목 | 내용 |
|------|------|
| **장점** | TTL 만료 빈도 12배 감소 (300초→3600초). cli_large_task_ms (30분) 케이스 완전 해소. 추가 구현 없이 API 파라미터만 변경으로 즉시 효과. |
| **단점** | Claude Code CLI는 내부적으로 자동 캐시를 사용하며 현재 TTL 직접 제어 불가. API 직접 호출 패턴이 필요하거나 Claude Code SDK의 캐시 설정 인터페이스가 노출되어야 한다. |
| **예상 절감률** | 시나리오 1~3: **90% 이상** (5분 TTL로 발생했던 cache miss의 대부분 제거). 시나리오 4 (agile 30분 루프): **약 95%** |
| **구현 복잡도** | **중간** — Claude Code에서 캐시 TTL을 제어하는 공식 경로가 있다면 설정 추가만으로 가능. 없다면 `mst.py` 또는 스킬에서 Anthropic SDK 직접 호출 패턴 도입 필요. |

---

### 옵션 B: 외부 CLI 비동기·배치화 (Fire-and-forget)

**설명**: 메인 Claude Code 세션이 외부 CLI 완료를 동기 대기하지 않고, CLI를 백그라운드로 기동한 뒤 결과 파일이 생성될 때 재개하는 패턴으로 전환한다. `dispatch.py`의 heartbeat 파일 기반 상태 관리가 기반 구조를 이미 제공하고 있다.

| 항목 | 내용 |
|------|------|
| **장점** | 메인 세션의 유휴 시간(idle) 자체를 제거 → cache TTL 소비 없음. 시나리오 1~3의 cache miss를 원천적으로 차단. `dispatch.py`의 기존 heartbeat 구조를 확장하면 구현 가능. |
| **단점** | 워크플로우 재설계 필요 (`mst.py run`, `skills/codex/SKILL.md`, `skills/gemini/SKILL.md`의 실행 프로토콜 변경). 에러 처리·타임아웃 로직 복잡화. 중간 결과를 메인 세션에 전달하는 통신 채널 설계 필요. |
| **예상 절감률** | 시나리오 1~3: **100%** (cache miss 자체 발생 제거). 시나리오 4: **약 80~90%** (Sprint 간 재개 시 짧은 idle은 유지될 수 있음). |
| **구현 복잡도** | **높음** — request 워크플로우의 핵심 실행 경로 변경. `mst.py run` 동기 모드 → 비동기 polling 모드 전환, 각 SKILL.md dispatch 프로토콜 업데이트 필요. |

---

### 옵션 C: 프롬프트 Prefix 슬림화 (컨텍스트 압축)

**설명**: 메인 세션의 캐시 prefix 크기(MTok)를 줄여, cache miss가 발생하더라도 건당 추가 비용을 낮춘다. CLAUDE.md / 시스템 프롬프트 최적화, 대화 이력 압축, 불필요한 파일 인라이닝 제거가 해당한다.

| 항목 | 내용 |
|------|------|
| **장점** | 코드 변경 없이 프롬프트 엔지니어링만으로 즉시 적용 가능. Cache miss 발생 자체를 막지는 않지만 발생 시 비용을 선형적으로 낮춤. |
| **단점** | Cache miss 횟수는 동일하므로 절감에 한계. 컨텍스트 축소가 품질(분석 정확도, 코드 이해도)에 영향을 줄 수 있음. 지속적인 프롬프트 관리 오버헤드. |
| **예상 절감률** | prefix 크기 50% 감소 시 cache miss 비용 **50% 절감**. (예: 시나리오 4 Opus $405 → $202.50). 절감률은 prefix 크기 감소율에 정비례. |
| **구현 복잡도** | **낮음** — `CLAUDE.md`, 스킬 SKILL.md 내 시스템 프롬프트, `skills/*/SKILL.md` 컨텍스트 전달 부분 수정. 코드 변경 없음. |

---

## 권장 다음 액션

| 순위 | 후속 mst:request 후보 | 근거 | 예상 효과 |
|------|----------------------|------|-----------|
| **1순위** | **외부 CLI 비동기화 구현** (옵션 B) | cache miss를 구조적으로 제거. `dispatch.py` 기반 구조 이미 존재하여 확장 가능. 시나리오 4 Opus $405/사이클 절감 가능. | 시나리오 1~3 100%, 시나리오 4 80~90% 비용 절감 |
| **2순위** | **1시간 TTL 명시 캐시 구현** (옵션 A) | API 파라미터 변경만으로 즉각적 효과. 비동기화 대비 구현 복잡도 낮음. 단기 완화로 먼저 적용 권장. | 시나리오 1~3 90% 이상 절감 |
| **3순위** | **프롬프트 prefix 슬림화** (옵션 C) | 비용 절감보다 품질·관리성 개선 효과도 있음. 1~2순위 구현 전 즉시 적용 가능한 단기 조치. | cache miss 비용 50% (prefix 50% 감소 기준) |

**실측 검증 권고**: 이론 계산의 한계를 보완하기 위해 Anthropic console의 청구 로그에서 실제 cache hit/miss 비율을 1회 측정하는 후속 REQ를 추가로 제안한다. 실측 없이는 시나리오별 "대기 시간 = cache miss 발생"이라는 가정이 항상 성립하지 않을 수 있다.

---

## 가정과 한계

### 이론 계산 기반

본 분석은 **공개된 Anthropic 가격 정책 및 TTL 문서**와 Gran Maestro 설정값을 바탕으로 한 **이론 계산**이다. 실제 세션 로그, Anthropic console 청구 데이터, 또는 프로파일링 결과에 기반하지 않는다.

### 주요 가정

| 가정 | 내용 | 불확실성 |
|------|------|---------|
| Cache miss = 대기 시간 > TTL | 외부 CLI 대기가 5분을 초과하면 항상 cache miss 발생 | 실제로는 세션 재개 타이밍, Claude Code 내부 캐시 관리 로직에 따라 다를 수 있음 |
| Prompt cache prefix 크기 | 시나리오별 1.0~3.0 MTok 임의 설정 | 실제 크기는 세션 컨텍스트, CLAUDE.md 길이, 인라인 파일에 따라 크게 다름 |
| Cache miss 횟수 | 시나리오 4에서 Sprint별 2회, 총 10회 산정 | retry, fallback, review 반복 등에 따라 횟수 변동 가능 |
| 모델 단가 | 2026-04-17 기준 추정치 (Opus $15/MTok, Sonnet $3/MTok) | Anthropic 가격 정책은 공지 없이 변경될 수 있음. 실제 청구 전 [anthropic.com/pricing](https://www.anthropic.com/pricing) 교차 확인 필수 |
| Cache prefix matching 동작 | prefix 전체가 단일 cache 단위로 처리된다고 가정 | 실제 prefix splitting, partial matching 동작의 세부 구현은 일부 비공개 |

### 분석 제외 범위

- Bedrock·Vertex 채널의 캐시 정책 (비-Anthropic 채널 분석 범위 외)
- 서브에이전트(codex/gemini) 자체 API 비용 — 본 분석은 메인 Claude Code 세션만 대상
- 실측 데이터 수집 및 Anthropic console 청구 분석

### 정책 변경 가능성

모든 수치는 **2026-04-17 기준**으로 고정된다. REF-002(github.com/anthropics/claude-code/issues/46829)가 보여주듯 Anthropic은 TTL 정책을 예고 없이 변경한 선례가 있다. 본 분석 이후 캐시 정책 재변경 시 시나리오 비용 및 완화 옵션 효과를 재검토해야 한다.
