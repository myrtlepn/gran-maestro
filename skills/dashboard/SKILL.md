---
name: dashboard
description: "로컬 대시보드 서버를 시작하거나 엽니다. 사용자가 '대시보드', '대시보드 열어', '모니터링'을 말하거나 /mst:dashboard를 호출할 때 사용. 서버 재시작은 --restart 플래그 사용. CLI 터미널 상태 확인에는 /mst:list 또는 /mst:inspect를 사용."
user-invocable: true
argument-hint: "[--port {포트}] [--stop] [--restart]"
---

# maestro:dashboard

로컬 대시보드 서버를 시작하고 브라우저에서 엽니다. 허브 구조로 여러 프로젝트 관리, 워크플로우 그래프/에이전트 스트림/문서 브라우저 제공.

## 요구사항

- **Deno**: 런타임 필수. 미설치 시 https://deno.land 에서 설치 안내

## 실행 프로토콜

> **경로 규칙 (MANDATORY)**: 이 스킬의 모든 `.gran-maestro/` 경로는 **절대경로**로 사용합니다.
> 스킬 실행 시작 시 `PROJECT_ROOT`를 취득하고, 이후 모든 경로에 `{PROJECT_ROOT}/` 접두사를 붙입니다.
> ```bash
> PROJECT_ROOT=$(pwd)
> ```

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
