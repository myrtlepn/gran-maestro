---
name: gemini
description: "사용자가 $mst:gemini 또는 /mst:gemini을 명시적으로 호출하거나 MST/Gran Maestro/Maestro의 gemini 기능 사용을 명시적으로 요청한 경우에만 실행합니다. 일반 요청에는 자동 활성화하지 않습니다."
user-invocable: true
argument-hint: "{프롬프트} [--prompt-file {경로}] [--dir {경로}] [--files {패턴}] [--trace {REQ/TASK/label}]"
---

# maestro:gemini

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

`/mst:gemini` is a **Deprecated compatibility wrapper**. 새 workflow, spec, docs, agent routing은 `/mst:agy`와 `agy-dev`를 canonical로 사용합니다.

## Compatibility Contract

- command_identity: `mst:gemini`은 legacy 입력 식별을 위해 유지합니다.
- 내부 실행은 AGY-compatible provider path로 위임합니다.
- trace/parser/statusline은 historical `gemini-*` artifact를 읽을 수 있어야 하지만, 신규 trace는 `agy-*`를 선호합니다.
- active 구현 지시는 `/mst:agy`를 사용해야 합니다.

## 실행 안내

동일 인자를 `/mst:agy`로 전달합니다.

```bash
/mst:agy {프롬프트 또는 --prompt-file/--dir/--files/--trace 인자}
```

## 예시

```bash
/mst:agy "전체 코드베이스 문서 생성해줘"
/mst:agy --prompt-file {prompt_path} --files src/**/*.ts --trace REQ-001/01/phase1-analysis
```
