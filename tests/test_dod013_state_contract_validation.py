from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import test_dod013_state_contract_validator as suite


if __name__ == "__main__":
    raise SystemExit(suite.main())
