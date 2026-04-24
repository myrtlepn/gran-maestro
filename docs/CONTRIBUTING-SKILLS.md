# Contributing New MST Skills

본 가이드는 Gran Maestro 플러그인에 새 MST 스킬을 추가하려는 개발자를 위한 30분 내 체인 참여 경로를 제공합니다. MST 스킬은 Gran Maestro 플러그인의 핵심 역량으로, 구조화된 태스크를 수행하고, 다른 스킬과 체인을 이루며, Agentic Workflow를 가능하게 합니다.

이 문서의 목표는 여러분이 스킬의 뼈대를 생성하고(Scaffold), 필수 구조(SKILL.md)를 채우며, Hook/State 계약을 준수하여 30분 안에 첫 스킬을 동작시킬 수 있도록 안내하는 것입니다.

## 1. 개요

### MST 스킬의 역할
- **AGI-018 Flow Controller 통합**: MST 스킬은 단순한 프롬프트 모음이 아닙니다. Flow Controller의 라이프사이클 안에서 동작하며, `mst:on` 네임스페이스가 활성화되었을 때만 트리거됩니다.
- **체인 및 위임**: 하나의 스킬이 모든 것을 처리하지 않습니다. 서브스킬을 호출(예: `mst:plan` -> `mst:review`)하고, 결과를 반환받아 부모 스킬의 다음 Step으로 이어가는 Agentic 위임 구조를 가집니다.

### 핵심 원칙
- **AD-001 (원자성·관찰성·결정성)**: 스킬의 각 Step은 원자적(Atomic)으로 실행되어야 하며, 시스템 상태(Snapshot, HUD)에 명확히 관찰(Observable)되어야 하고, 동일한 조건에서는 항상 예측 가능한 형태(Deterministic)로 동작해야 합니다.
- **AD-003 (3계층 Gate)**:
  - **Layer 1**: `mst:on/off` 상태 기반의 최상위 차단. `mst:off` 상태에서는 어떤 스킬도 실행되지 않습니다.
  - **Layer 2**: `snapshot` 상태 기반 진입 차단. (예: 현재 작업 중인 파일이 없는 경우 리뷰 스킬 실행 불가)
  - **Layer 3**: MST 네임스페이스 Allowlist 차단. 등록되지 않은 스킬은 호출 자체가 불가합니다.

### 이 문서가 다루는 범위
1. 스킬 Scaffold를 통한 초기 뼈대 구축
2. `SKILL.md` 문서 내 필수 구조 (Frontmatter, Gate, Anti-Rationalization, 3 shared include 등) 이해
3. 체인 연동을 위한 Hook 및 State 계약 준수 방법
4. 검증 및 테스트 체크리스트 확인

---

## 2. Scaffold 사용

가장 빠르게 스킬 개발을 시작하는 방법은 `skill scaffold` 서브커맨드를 사용하는 것입니다. 이 도구는 필요한 디렉토리와 템플릿 파일을 자동으로 생성해 줍니다.

### 명령어 사용법

```bash
python3 scripts/mst.py skill scaffold <name> [--description "..."] [--force]
```

- `<name>`: 생성할 스킬의 이름입니다. 하이픈(`-`)과 소문자 영숫자 조합만 허용됩니다 (예: `my-awesome-skill`, `code-review`).
- `--description`: 선택 사항입니다. `skills/<name>/SKILL.md` 상단 Frontmatter의 `description` 초기값을 설정합니다.
- `--force`: 기존에 동일한 이름의 스킬 디렉토리가 있을 경우, 덮어쓸지 묻지 않고 강제로 재생성합니다. 주의해서 사용하세요.

### 생성 파일 확인

명령어를 실행하면 `skills/<name>/` 디렉토리 아래에 템플릿 기반의 `SKILL.md` 파일이 생성됩니다.

- `skills/<name>/SKILL.md`: 스킬의 메인 지시서입니다. Gate, Anti-Rationalization, 3 shared include, Step 0/1 Placeholder가 이미 구성되어 있습니다. 이 파일을 열어 구체적인 로직을 채워 넣게 됩니다.

---

## 3. SKILL.md 구조

생성된 `SKILL.md` 파일은 LLM이 읽고 따르는 실행 매뉴얼입니다. 다음 필수 요소들이 올바르게 작성되어야 스킬이 정상 동작합니다.

### 3.1. Frontmatter (YAML)
파일의 가장 첫 줄에 위치하며, 스킬의 메타데이터를 정의합니다. 스킬 파서가 이 영역을 읽어 처리합니다.

```yaml
---
name: <name>
description: "이 스킬이 수행하는 주요 역할과 목적을 간결하게 한 줄로 요약합니다."
type: command  # command | slash | trigger
---
```
- `type`: 스킬의 트리거 방식입니다. 주로 CLI 명령어 형태의 `command`나 채팅창에서 슬래시로 호출하는 `slash`를 사용합니다.

### 3.2. Gate 섹션
스킬이 실행되어도 되는지, 언제 종료되어야 하는지, 어떤 행동을 절대 해서는 안 되는지 규정하는 가장 중요한 섹션입니다.

```markdown
## Gate

### Entry
- [ ] 현재 프로젝트 내에 `README.md` 파일이 존재하는가?
- [ ] 사용자가 명시적으로 수정할 대상을 지정했는가?
(진입 조건을 명확한 체크리스트 형태로 작성)

### Exit
- [ ] 수정된 내용이 파일에 정상적으로 쓰였는가?
- [ ] 테스트를 통과하고 회귀 오류가 없음을 확인했는가?
(완료 조건을 달성해야만 스킬이 종료됨)

### 금지 패턴
- [ ] 파일 전체를 한 번에 다시 쓰지 말 것 (항상 replace 등 부분 수정 도구 사용)
- [ ] 사용자의 승인 없이 원격 저장소에 Push하지 말 것
```

### 3.3. Anti-Rationalization Checklist
LLM이 스스로 "이 정도면 충분하다"고 합리화하며 태스크를 조기 종료하거나 검증을 건너뛰는 것을 방지하기 위한 안전장치입니다.

- **합리화 패턴**: "에러 로그를 보아하니 A 문제가 확실하므로 테스트 없이 코드를 수정한다."
- **반증 방법**: 수정하기 전에 반드시 `pytest`나 테스트 스크립트를 실행해 실패하는 것을 육안으로 확인하고 (Empirical Reproduction) 이후 수정할 것.

### 3.4. 3 shared include (필수 참조)
모든 MST 스킬이 공통으로 따르는 핵심 규약입니다. 템플릿에 기본 포함되어 있으며, 지우지 말고 반드시 참조하도록 남겨두어야 합니다.

- `_shared/path-rules.md`: 작업 환경에서 상대 경로 대신 절대 경로 원칙을 사용해야 함을 명시합니다.
- `_shared/user-profile-read.md`: `~/.claude/user-profile.json`에 정의된 커뮤니케이션 스타일과 선호도를 읽고 반영하도록 합니다.
- `_shared/skill-execution-marker.md`: 스킬 응답의 최상단에 상태를 표시하는 마커 규약을 정의합니다.

### 3.5. Step Placeholder
스킬은 보통 2~5개의 Step으로 구성됩니다. 각 Step마다 명확한 목표와 사용할 도구가 정해져 있어야 합니다. scaffold로 생성된 `Step 0`과 `Step 1` 영역을 스킬 목적에 맞게 실제 로직으로 변경하세요.

---

## 4. Hook / State 계약

MST 플러그인은 CLI와 Hook, 그리고 스킬 파일 간의 철저한 규약(Contract)을 통해 상태를 관리합니다. 이 계약이 깨지면 스킬 체인이 끊어지거나 상태 불일치가 발생합니다.

### 4.1. 실행 마커 (Execution Marker)
LLM이 생성하는 모든 텍스트 응답의 **가장 첫 줄(Mandatory)**에는 반드시 현재 상태를 나타내는 마커가 포함되어야 합니다. Hook 스크립트(`mst-pre-tool-use.sh`, `mst-stop-hook.sh` 등)가 이 마커를 파싱합니다.

```text
# 독립적으로 실행되는 최상위 스킬의 경우
[MST skill={name} step={N}/{M} return_to=null]

# 부모 스킬(예: plan)에 의해 호출된 서브스킬(예: review)의 경우
[MST skill={name} step={N}/{M} return_to=parent_skill/X]

# 서브스킬이 모든 작업을 마치고 부모로 복귀할 때
[MST skill={subskill} step=returned return_to=parent/X]
```

### 4.2. state set CLI 호출
스킬 내에서 Step이 넘어갈 때, 혹은 중요한 상태 변화가 있을 때 시스템에 이를 알려야 합니다.
각 Step 진입 시 `run_shell_command` 도구를 사용하여 CLI를 호출해 snapshot 상태를 갱신하세요.

```bash
# {PLUGIN_ROOT}는 실제 워크스페이스 내 프로젝트 루트 경로로 치환해야 합니다.
python3 {PLUGIN_ROOT}/scripts/mst.py state set \
  --skill {name} --step {N} --total {M} --return-to "{parent_skill/step}"
```

### 4.3. return_to 규칙
스킬 체인을 구성할 때 가장 중요한 규칙입니다.
1. **서브스킬 호출**: 최상위 스킬에서 서브스킬을 호출할 때는 `--return-to parent_skill/step_number` 플래그를 넘겨, 서브스킬이 끝나고 돌아올 위치를 지정해야 합니다.
2. **복귀 표시**: 서브스킬은 자신의 마지막 Step을 마친 뒤, 응답 마커를 `step=returned`로 설정하여 명시적으로 제어권을 반환해야 합니다.
3. **Continuation Guard**: 서브스킬은 부모 스킬이 가지고 있는 연속성 규칙을 침범해서는 안 됩니다. 서브스킬 반환 직후, 부모 스킬이 대기 중이던 다음 Step을 이어서 실행하게 됩니다.

### 4.4. AD-001 원자성 원칙 보장
- 스킬 내부 로직에서 상태 파일(Snapshot)에 대해 Read-Modify-Write(RMW) 작업을 직접 수행해야 한다면, 반드시 제공되는 `_skill_state` 파이썬 헬퍼 스크립트를 사용하세요.
- `fcntl.flock` 기반의 파일 잠금(Locking)이 적용되어 있어 RMW 직렬화가 자동으로 보장됩니다. 동시에 여러 프로세스가 접근하여 상태가 오염되는 것을 막아줍니다 (S26 DOD-016 증분 #1 적용 사항).

---

## 5. 검증 체크리스트

새로운 스킬 개발을 완료한 후, PR을 올리기 전 다음 체크리스트를 순서대로 확인하세요.

### (a) Allowlist 등록 확인
- [ ] `.claude-plugin/plugin.json` 파일을 열어 `skills` 배열 목록에 새로 생성한 스킬 디렉토리 경로가 반영되어 있는지 확인합니다.
- [ ] (필요한 경우) `scripts/_mst_namespace.py`의 하드코딩된 allowlist가 있다면 수동으로 업데이트합니다. (참고: 향후 증분 #3에서 이 과정을 자동 Diff로 검증하는 기능이 제공될 예정입니다.)

### (b) 테스트 회귀 확인
새 스킬이 기존 시스템에 부작용을 일으키지 않았는지 자동화 테스트로 검증합니다.
- [ ] 단위 테스트 실행: `python3 -m pytest tests/ -q` (기존 baseline 통과 여부 확인, 회귀 0이어야 함)
- [ ] 타입 검사 실행: `npx tsc --noEmit` (TypeScript 타입 오류가 0이어야 함)

### (c) mst:on 활성 세션 실제 호출
로컬 환경에서 직접 스킬을 실행해 봅니다.
- [ ] 먼저 `/mst:on`을 입력해 MST 네임스페이스를 활성화합니다.
- [ ] 채팅창에서 슬래시 커맨드로 새 스킬을 호출해 봅니다 (예: `/mst:<name> -a "test"`).
- [ ] HUD(Head-Up Display) Statusline에 스킬 체인 상태가 정상적으로 표시되는지 확인합니다.
- [ ] `flow-detail.ndjson` 로그 파일에 스킬의 `enter` 및 `exit` 이벤트가 정확히 기록되었는지 확인하여 AD-001 원칙 준수 여부를 검증합니다.

### (d) 30분 온보딩 타임라인
초기 기획대로 30분 안에 온보딩이 가능한지 스스로 측정해 보세요.
- [ ] **00~05분**: `mst.py skill scaffold <name>` 명령어 실행 및 생성된 파일 구조 파악
- [ ] **05~15분**: `SKILL.md`의 Frontmatter, Gate, Anti-Rationalization 영역 명세 작성
- [ ] **15~25분**: Step 0/1 영역에 실제 수행할 로직 구현 및 `state set` CLI 호출 추가
- [ ] **25~30분**: Allowlist 등록, `pytest` 회귀 테스트 실행, `/mst:on` 환경에서 실호출 검증

---

## 6. 참고 자료

구체적인 구현 패턴이 궁금할 경우, 이미 운영 중인 핵심 스킬들을 참조하는 가장 좋습니다. 내부 구현 디테일은 아래 실제 스킬 코드로 위임합니다.

- **실제 작동 예시 (단일 스킬)**: [skills/plan/SKILL.md](../skills/plan/SKILL.md) — Gate/Anti-Rationalization/3 shared include/Step 구조의 정석을 보여줍니다.
- **실제 작동 예시 (체인 및 서브스킬)**: [skills/agile/SKILL.md](../skills/agile/SKILL.md) — 다른 스킬을 서브스킬로 호출하고 복귀하는 고급 패턴을 확인할 수 있습니다.
- **Flow Controller 설계 원칙**: [docs/FLOW-CONSTRAINTS.md](./FLOW-CONSTRAINTS.md) — 전체적인 상태 관리와 Flow 통제에 대한 백그라운드 지식입니다.
- **AGI-018 목표 정의**: [.gran-maestro/agile/AGI-018/objective/objective.md](../.gran-maestro/agile/AGI-018/objective/objective.md) — 이 문서를 작성하게 된 요구사항 및 도메인 배경지식입니다.
