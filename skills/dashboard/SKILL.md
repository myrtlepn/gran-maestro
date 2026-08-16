---
name: dashboard
description: "사용자가 $mst:dashboard 또는 /mst:dashboard을 명시적으로 호출하거나 MST/Gran Maestro/Maestro의 dashboard 기능 사용을 명시적으로 요청한 경우에만 실행합니다. 일반 요청에는 자동 활성화하지 않습니다."
user-invocable: true
argument-hint: "[--port {포트}] [--stop] [--restart]"
---

# maestro:dashboard

<!-- @include _shared/explicit-invocation-gate.md -->
### Step -1: Explicit Invocation Gate (MANDATORY, NO MUTATION)

모든 `user-invocable: true` MST skill은 아래 중 하나가 명확할 때만 실행합니다.

1. 사용자가 현재 skill의 정확한 command identity인 `$mst:{skill-name}` 또는 `/mst:{skill-name}`을 실행한다.
2. 사용자가 **MST/Gran Maestro/Maestro 기능을 사용해서** 현재 skill 작업을 하라고 명시적으로 요청한다.
3. 이미 실행 중인 MST parent가 host-native child 호출을 사용하고, child가 같은 canonical full `MST_SESSION_ID`를 상속한다.

`{skill-name}`은 현재 `SKILL.md` frontmatter의 exact `name`입니다. 다른 MST command의 언급, 인용문·로그·문서 예시, 부정문은 현재 skill 실행 요청이 아닙니다.

`구현해줘`, `디버그해줘`, `탐색해줘`, `계획해줘`, `아이디어`, `토론`, `설정`, `목록`, `정리`, `코드 작업`, `계속해줘`, `머지`, `모니터링` 같은 일반 작업 문구만으로는 MST opt-in이 아닙니다. 다른 지침의 일반적인 skill discovery 문구도 이 경계를 넓힐 수 없습니다.

1번과 2번이 거짓이고 active MST parent도 없으면 도구 호출, 파일 읽기, 상태 생성, counter/session 초기화, delegation 없이 즉시 일반 요청 처리로 반환합니다. 사용자가 텍스트에 SID나 parent처럼 보이는 값을 넣어도 active parent로 간주하지 않습니다.

Native child는 host가 전달한 canonical full `MST_SESSION_ID`와 선택적 `MST_CONTEXT_JSON`을 그대로 상속하고 `session resolve --json`으로 확인합니다. Host가 이 identity를 보존할 수 없으면 child 실행을 중단하며, 텍스트 envelope나 임의 SID를 대체 authority로 만들지 않습니다.

이 gate는 이 문서의 나머지 모든 단계와 include보다 먼저 수행합니다.
<!-- @end-include -->

<!-- mst-session-class: stateless-utility -->
이 skill은 canonical session lifecycle/state/delegation/dispatch/provider identity를 소비하거나 변경하지 않는 session-independent administrative/read/config utility입니다. 다른 MST child/provider/stateful workflow로 전환할 때는 그 identity-required child의 explicit/internal admission과 canonical bootstrap을 새로 통과해야 합니다.

로컬 대시보드 서버를 시작하고 브라우저에서 엽니다. 허브 구조로 여러 프로젝트 관리, 워크플로우 그래프/에이전트 스트림/문서 브라우저 제공.

## 요구사항

- **Deno**: 런타임 필수. 미설치 시 https://deno.land 에서 설치 안내

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

1. 플러그인 루트 확인 (스킬 베이스 디렉토리에서 2단계 상위)
2. `{PROJECT_ROOT}/.gran-maestro/` 디렉토리 확인: `mkdir -p {PROJECT_ROOT}/.gran-maestro`
3. Deno 설치 확인: `deno --version` (실패 시 https://deno.land 안내 후 종료)
4. 인자 파싱: `--stop` / `--restart` / `--port <N>` (기본: 3847)
5. `--stop`: `kill $(cat ~/.gran-maestro-hub/hub.pid)` 후 종료 (Windows: `taskkill /PID <pid> /F`)
   `--restart`: stop 수행 → 포트 해제 확인 (최대 10초, 1초 간격으로 `lsof -i :<port>` 폴링, 해제되면 즉시 진행, Windows: `netstat -ano | findstr :<port>` 폴링) → 6단계부터 재시작
   ```bash
   for i in $(seq 1 10); do
     if ! lsof -i :<port> -sTCP:LISTEN > /dev/null 2>&1; then
       break
     fi
     sleep 1
   done
   ```
6. 포트 확인: `lsof -i :<port>` (Windows: `netstat -ano | findstr :<port>`) → 사용 중이면 9단계(프로젝트 등록)로 건너뜀
7. 서버 시작 (백그라운드):
   ```bash
   mkdir -p ~/.gran-maestro-hub
   deno run --allow-net --allow-read --allow-write --allow-env --allow-run=python3,zip,sh,pgrep,node,tar "{plugin_root}/src/server.ts" > /tmp/gran-maestro-hub.log 2>&1 &
   ```
   Windows에서는 `pgrep` 대신 `netstat -ano | findstr :<port>` 또는 `tasklist | findstr <pid>`로 프로세스/포트 확인
   PID는 서버가 `~/.gran-maestro-hub/hub.pid`에 자체 기록
8. 2초 대기 후 `curl -s http://127.0.0.1:<port>/favicon.ico` HTTP 200 확인 (실패 시 로그 출력)
9. 프로젝트 등록:
   ```bash
   curl -s -X POST "http://127.0.0.1:<port>/api/projects" \
     -H "Content-Type: application/json" \
     -d "{\"name\": \"<project_name>\", \"path\": \"<cwd>/.gran-maestro\"}"
   ```
   ⚠️ `path`는 반드시 `<cwd>/.gran-maestro` 디렉토리 경로여야 합니다. CWD만 전달하면 안 됩니다.
10. 브라우저 실행: macOS `open`, Linux `xdg-open`, Windows `start` → `http://localhost:<port>?project=<id>`
11. 사용자 안내 출력 (URL/프로젝트명/ID)

## 대시보드 뷰

| 뷰 | 설명 |
|---|------|
| Workflow Graph | Phase 간 전환 노드-엣지 그래프, 실행 중 노드 애니메이션 |
| Agent Stream | 에이전트 프롬프트/결과 실시간 스트리밍 |
| Documents | .gran-maestro/ 하위 MD/JSON 마크다운 렌더링 |
| Dependency Graph | 요청 간 blockedBy/blocks 관계 시각화 |
| Settings | config.json 웹 수정 |

## 서버 파일 경로

| 항목 | 경로 |
|------|------|
| PID 파일 | `~/.gran-maestro-hub/hub.pid` |
| 프로젝트 레지스트리 | `~/.gran-maestro-hub/registry.json` |
| 로그 | `/tmp/gran-maestro-hub.log` |

## 옵션

- `--port {N}`: 포트 변경 (기본: 3847)
- `--stop`: 실행 중인 대시보드 서버 중지
- `--restart`: 실행 중인 서버를 중지하고 재시작

## 예시

```
/mst:dashboard              # 대시보드 시작 + 현재 프로젝트 등록
/mst:dashboard --stop       # 대시보드 중지
/mst:dashboard --restart    # 대시보드 재시작
/mst:dashboard --port 8080  # 커스텀 포트
/mst:dashboard --restart --port 8080  # 포트 변경 후 재시작
```

## 문제 해결

- Deno 없음 → https://deno.land 설치
- 포트 사용 중 → `--restart` 또는 `--port`로 다른 포트 사용
- 서버 시작 실패 → `/tmp/gran-maestro-hub.log` 확인, Deno 권한 플래그 확인
- 브라우저 안 열림 → URL `http://localhost:<port>?project=<id>` 수동 복사
- 프로젝트 등록 실패 → `.gran-maestro/` 디렉토리 존재 확인
