---
name: gemini
description: "Deprecated compatibility wrapper. /mst:gemini 호출은 /mst:agy로 이전해야 하며, 한 릴리스 동안 legacy alias로만 유지됩니다."
user-invocable: true
argument-hint: "{프롬프트} [--prompt-file {경로}] [--dir {경로}] [--files {패턴}] [--trace {REQ/TASK/label}]"
---

# maestro:gemini

`/mst:gemini`는 deprecated compatibility wrapper입니다. 새 workflow, spec, docs, agent routing은 `/mst:agy`와 `agy-dev`를 canonical로 사용합니다.

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
