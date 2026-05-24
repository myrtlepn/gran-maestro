"""_notifier.py — Gran Maestro 내부 알림 모듈 (직접 실행 금지)"""

import json
import urllib.request
import urllib.error

SSE_SERVER_URL = "http://127.0.0.1:3847"
NOTIFY_ENDPOINT = f"{SSE_SERVER_URL}/notify"


def notify(event_type: str, data: dict) -> bool:
    """SSE 서버에 이벤트를 POST. 서버 미실행 시 조용히 실패."""
    payload = json.dumps({"type": event_type, "data": data}).encode()
    req = urllib.request.Request(
        NOTIFY_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


if __name__ == "__main__":
    raise SystemExit("_notifier.py는 직접 실행할 수 없습니다. mst.py를 통해 사용하세요.")
