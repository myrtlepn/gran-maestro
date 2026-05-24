# pass-a-result.md 작성 스키마

`reviews/RV-NNN/pass-a-result.md`는 Pass A 실패(`pass_a_failed`) 결과를 approve가 재외주 선별에 사용하기 위해 파싱하는 파일입니다.

## 필수 필드 (4종)

아래 4개 필드는 **반드시 모두 포함**해야 합니다.

| 필드 | 타입 | 설명 | 예시 |
|------|------|------|------|
| `pass_a_result` | string | Pass A 결과. 이 스키마 문서 기준으로는 실패 기록이므로 `"fail"` 고정. | `pass_a_result: fail` |
| `failed_ac_ids` | string[] | FAIL 판정된 AC ID 목록. 비어 있지 않아야 함. | `failed_ac_ids: [AC-001, AC-003]` |
| `failure_class` | string | 실패 원인 분류: `ac_unclear` \| `interpretation` \| `implementation` | `failure_class: implementation` |
| `evidence` | array | 실패 근거 목록. 각 항목은 `{ ac_id, type, ref, summary }` 구조를 권장. | 아래 예시 참고 |

## 작성 예시

```yaml
pass_a_result: fail
failed_ac_ids:
  - AC-001
  - AC-003
failure_class: implementation
evidence:
  - ac_id: AC-001
    type: log
    ref: "logs/test-run.txt"
    summary: "테스트 명령이 exit code 1로 실패"
  - ac_id: AC-003
    type: manual
    ref: "PM 수동 검증 기록"
    summary: "Then 조건과 실제 UI 동작 불일치"
```

## AC 등급별 동작

- MUST AC가 1개 이상 FAIL이면 `pass_a_result: fail`로 기록하고 이 파일을 생성한다. approve는 이 파일을 기준으로 재외주 대상을 선별한다.
- SHOULD AC만 FAIL이고 MUST AC는 모두 PASS이면 `pass_a_failed` 분기로 처리하지 않는다. 이 경우 이 파일 대신 review 결과/경고로 기록한다.
- 모든 AC가 PASS이면 이 실패 기록 파일은 생성 대상이 아니다.
