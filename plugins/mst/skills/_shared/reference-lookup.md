### Reference Lookup Protocol (MANDATORY)

외부 의존성(라이브러리/API/프레임워크/버전/프로토콜) 판단은 아래 공통 프로토콜을 따른다.

0. **자동 트리거 게이트**: `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get reference.auto_search)`로 `reference.auto_search`를 확인한다. `true`일 때만 자동 WebSearch를 허용한다. 설정 미존재 시 기본값은 `cache_ttl_days=2`, `cutoff_threshold_months=0.5`, `max_searches_per_step=5`, `llm_auto_trigger=true`, `auto_fact_check=true`.
1. **키워드 감지**: 현재 단계 입력에서 외부 의존성 키워드를 감지한다. `reference.llm_auto_trigger == true`이면 PM이 최신 정보가 필요하다고 판단할 때도 WebSearch를 트리거한다. `false`이면 키워드 매칭 기반 동작만 유지한다.
2. **3단계 신선도 체크**: (a) `.gran-maestro/references/` 캐시를 `reference search --keyword "{keyword}" --json`으로 확인, (b) `searched_at + cache_ttl_days` 기준 `fresh/stale` 판정, (c) 현재 시각 대비 `cutoff_threshold_months` 초과 시 `expired` 판정.
3. **WebSearch 트리거**: 캐시 없음 또는 `stale/expired`일 때만 검색한다. `reference.auto_search == true`일 때만 실행하고 Step당 `max_searches_per_step`을 넘지 않는다. `reference.auto_fact_check == true`이면 핵심 claim을 1회성 교차 WebSearch로 경량 검증한다.
4. **REF 저장 (MANDATORY — WebSearch 실행 시 Bash 호출 필수)**: WebSearch를 1건이라도 실행했으면 결과마다 `Bash`로 `mst.py reference add`를 호출한다. 표/텍스트 결론 요약만으로는 저장 완료가 아니며 `content.md`는 raw 발췌(원문 근거) 중심으로 남긴다.
   - 저장 명령: `python3 {PLUGIN_ROOT}/scripts/mst.py reference add --topic "{topic}" --url "{url}" --summary "{summary}" --content "{raw 발췌 본문}"`
   - 작성 원칙: 인용/표/코드 스니펫 + 출처 URL/날짜를 함께 기록한다 (`summary`는 한 줄 인덱스 유지).
   - 예시 A (인용): `> 인용: "{원문 핵심 문장}" (출처: {URL}, 날짜: {YYYY-MM-DD})`
   - 예시 B (표): `| 열 | 값 |` 형태의 raw markdown table과 출처 URL을 보존한다.
   - 예시 C (코드 스니펫): fenced code block(```text)으로 raw 코드와 문서 URL/버전을 남긴다.
   - 신규 REF 품질 체크리스트 (저장 전 점검): Findings: 결론 1~3줄. Quotes: 짧은 원문 인용+URL. Data: 표/버전/날짜/수치. Context: 현재 plan 판단에 필요한 이유.
   - PM lazy-Read 트리거 (`content.md Read` 필수): summary만으로 부족하거나 표/코드/원문 뉘앙스가 결론에 영향을 주면 반드시 `content.md`를 Read한다.
   - 여러 결과는 병렬 `reference add`로 저장해도 된다. 각 호출은 project+ref namespace lock에서 고유 ID를 먼저 예약하고 완전한 `reference.json`/`content.md` pair만 성공으로 공개한다.
   - exit 0과 반환된 REF ID를 받은 뒤 `reference get {REF-ID} --json`으로 read-back이 성공해야 저장 완료로 간주한다.
   - crash 또는 publish 실패가 있으면 예약 ID는 재사용하지 않으므로 번호 gap은 정상이다. `reference add` 재시도는 새 ID를 만드는 비-idempotent 작업이므로 실패 결과의 `outcome=confirmed_failure|unknown_outcome`을 먼저 확인한다.
   - `REFERENCE_CORRUPT`, `REFERENCE_SCHEMA_INVALID`, `REFERENCE_INCOMPLETE`, `REFERENCE_PATH_UNSAFE`, `REFERENCE_OUTCOME_UNKNOWN`은 선행 ID 부족이 아니라 저장소 상태 진단이다. `reference doctor --json`으로 확인하고 손상 artifact를 자동 덮어쓰거나 삭제하지 않는다.
5. **프롬프트 주입**: 이후 단계 프롬프트에 `[REFERENCE_CONTEXT]`를 주입한다. 형식: `current_date`, `model_cutoff`, `references: REF-001 (fresh|stale|expired) {topic} | {url}`. 참조가 없으면 `references: none`으로 명시한다.
