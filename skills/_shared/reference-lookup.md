### Reference Lookup Protocol (MANDATORY)

외부 의존성(라이브러리/API/프레임워크/버전/프로토콜) 관련 판단은 아래 공통 프로토콜을 따른다.

0. **자동 트리거 게이트**:
   - `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get reference.auto_search)`로 `reference.auto_search`를 확인한다.
   - `reference.auto_search == true`일 때만 자동 WebSearch를 허용한다.
   - 설정 미존재 시 기본값: `cache_ttl_days=2`, `cutoff_threshold_months=0.5`, `max_searches_per_step=5`, `llm_auto_trigger=true`, `auto_fact_check=true`.
1. **키워드 감지**:
   - 현재 단계 입력 컨텍스트에서 외부 의존성 키워드(라이브러리/API/프레임워크/버전/프로토콜 계열)를 감지한다.
   - `reference.llm_auto_trigger == true`이면 키워드 매칭과 별도로 PM이 "인터넷에 최신 정보가 있을 법한 내용"이라고 판단할 때 자율적으로 WebSearch를 트리거한다.
   - `reference.llm_auto_trigger == false`이면 기존 키워드 매칭 기반 동작만 유지한다.
2. **3단계 신선도 체크**:
   - (a) `.gran-maestro/references/` 캐시 존재를 `python3 {PLUGIN_ROOT}/scripts/mst.py reference search --keyword "{keyword}" --json`으로 확인한다.
   - (b) TTL 체크: `searched_at + cache_ttl_days` 경과 여부로 `fresh/stale`를 판정한다.
   - (c) cutoff 괴리 체크: 현재 시각 대비 `cutoff_threshold_months` 초과 시 `expired`를 판정한다.
3. **WebSearch 트리거**:
   - 캐시 없음 또는 `stale/expired`일 때만 검색한다.
   - `reference.auto_search == true`일 때만 실행하고, Step당 최대 `max_searches_per_step`을 유지한다.
   - `reference.auto_fact_check == true`이면 검색 결과의 핵심 claim을 1회성 교차 WebSearch로 경량 검증한다.
   - `reference.auto_fact_check == false`이면 기존 동작(검색 결과를 그대로 다음 단계로 전달)을 유지한다.
4. **REF 저장 (MANDATORY — WebSearch 실행 시 Bash 호출 필수)**:
   - WebSearch를 1건이라도 실행했으면, 각 검색 결과마다 반드시 `Bash`로 `mst.py reference add`를 호출해야 한다.
   - 표/텍스트 결론 요약만으로는 저장이 완료되지 않는다. `content.md`는 raw 발췌(원문 근거) 중심으로 남긴다.
   - 저장 명령: `python3 {PLUGIN_ROOT}/scripts/mst.py reference add --topic "{topic}" --url "{url}" --summary "{summary}" --content "{raw 발췌 본문}"`
   - 작성 원칙 요약: 인용/표/코드 스니펫 + 출처 URL/날짜를 함께 기록한다 (`summary`는 한 줄 인덱스 유지).
   - 상세 예시/품질 체크리스트/lazy-Read 트리거는 `skills/plan/SKILL.md`의 Reference Lookup Protocol 4번 항목을 동일 기준으로 따른다.
5. **프롬프트 주입**:
   - 이후 단계 프롬프트 컨텍스트에 `[REFERENCE_CONTEXT]`를 주입한다.
   - 형식:
     ```text
     [REFERENCE_CONTEXT]
     current_date: {YYYY-MM-DD}
     model_cutoff: {cutoff_date_or_unknown}
     references:
     - REF-001 (fresh|stale|expired) {topic} | {url}
     [/REFERENCE_CONTEXT]
     ```
   - 참조가 없으면 `references: none`으로 명시한다.
