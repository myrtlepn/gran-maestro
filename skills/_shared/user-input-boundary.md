### User Input Boundary (MANDATORY)

사용자 입력이 실제로 필요한 지점에서는 host별 질문 도구를 직접 호출하기 전에 `question prepare`를 사용한다. 이미 대화에서 결정된 내용을 재확인하기 위한 질문은 만들지 않는다.

1. 질문 payload를 `templates/question-payload.schema.json`에 맞는 JSON 파일로 작성한다.
2. 현재 호출이 **Codex root agent의 Plan mode**이고 이 호출에 `request_user_input` 도구가 실제로 노출되어 있을 때만 `CODEX_NATIVE=true`로 둔다. Default mode, subagent, headless, 또는 도구 부재에서는 반드시 `false`다. 추정으로 `true`를 설정하지 않는다.
3. 아래 CLI를 호출한다. 기존 canonical `MST_SESSION_ID`와 `MST_CONTEXT_JSON`은 그대로 보존한다.
   ```bash
   python3 {PLUGIN_ROOT}/scripts/mst.py question prepare \
     --skill {CURRENT_SKILL} \
     --step "{CURRENT_STEP}" \
     --resume-skill {CURRENT_SKILL} \
     --resume-args "{RESUME_ARGS}" \
     --payload-file {QUESTION_PAYLOAD_JSON} \
     --codex-native "${CODEX_NATIVE:-false}" \
     --json
   ```
4. 반환값에 따라 분기한다.
   - `mode=claude_tool`: 반환된 `payload`로 `AskUserQuestion`을 호출한다.
   - `mode=codex_tool`: 반환된 `payload`로 `request_user_input`을 호출한다. 도구 응답을 `question answer`로 저장하고 `question consume`으로 저장된 continuation을 queue에 넣은 뒤 기존 resume 흐름을 계속한다.
   - `mode=pending_artifact`: 반환된 `user_message`를 사용자에게 그대로 보여주고 종료한다. 이 상태는 정상적인 사용자 입력 대기다. 사용자는 안내된 `/mst:resume --answer Q-... --value "..."`로 답하고 재개한다.
   - `mode=auto_decision`: `AUTO_MODE=true` 경로로 질문 없이 계속하거나 blocker를 기록한다.
5. Native payload 제약에 맞지 않는 질문은 내용을 자르지 않고 `pending_artifact`로 전환한다. workflow 중 임의 확인 질문이나 self-pause는 계속 금지한다.
