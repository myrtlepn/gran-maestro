### User Input Boundary (MANDATORY)

사용자 입력이 필요한 지점에서는 host별 질문 도구를 직접 판단하지 말고 `question prepare`를 먼저 호출한다. 이 규칙은 기존 `AskUserQuestion` 직접 호출 지시보다 우선한다.

1. 질문 payload를 JSON 파일로 작성한다. 구조는 `templates/question-payload.schema.json`을 따른다.
2. 아래 CLI를 호출한다.
   ```bash
   python3 {PLUGIN_ROOT}/scripts/mst.py question prepare \
     --skill {CURRENT_SKILL} \
     --step "{CURRENT_STEP}" \
     --resume-skill {CURRENT_SKILL} \
     --resume-args "{RESUME_ARGS}" \
     --payload-file {QUESTION_PAYLOAD_JSON} \
     --json
   ```
3. 반환값에 따라 분기한다.
   - `mode=claude_tool`: 반환된 `payload`로 `AskUserQuestion`을 호출한다.
   - `mode=pending_artifact`: 반환된 `user_message`를 사용자에게 보여주고 종료한다. 이 상태는 정상적인 사용자 입력 대기이며 임의 중단이 아니다.
   - `mode=auto_decision`: `AUTO_MODE=true` 경로로 질문 없이 계속하거나 blocker를 기록한다.
4. Codex/headless host에서는 `AskUserQuestion`을 직접 호출하지 않는다. pending question은 `.gran-maestro/questions/Q-*.json`에 저장되고 `/mst:resume --answer Q-...`로 재개한다.
5. workflow 중 임의 확인 질문이나 self-pause는 계속 금지한다. 정상 질문은 `question prepare`가 기록한 `awaiting_user_input` 상태와 payload hash가 일치할 때만 허용된다.
