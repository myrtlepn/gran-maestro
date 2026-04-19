import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST = REPO_ROOT / "scripts" / "mst.py"


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True)
    return workspace


def _write_ndjson(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _sample_rows() -> list[dict]:
    rows = []
    for index, token_count in enumerate([100, 200, 300, 400, 500, 600, 700, 800], start=1):
        rows.append(
            {
                "timestamp": f"2026-04-{index:02d}T00:00:00Z",
                "parse_status": "ok",
                "token_count_estimate": token_count,
                "fallback_reason": None,
            }
        )
    rows.extend(
        [
            {
                "timestamp": "2026-04-09T00:00:00Z",
                "parse_status": "schema_fail",
                "token_count_estimate": None,
                "fallback_reason": "schema_fail",
            },
            {
                "timestamp": "2026-04-10T00:00:00Z",
                "parse_status": "ref_missing",
                "token_count_estimate": None,
                "fallback_reason": "ref_missing",
            },
        ]
    )
    return rows


def _run_metrics(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST), "metrics", *args],
        cwd=str(workspace),
        capture_output=True,
        text=True,
    )


def test_metrics_summary_prompt_builder(tmp_path):
    workspace = _workspace(tmp_path)
    metrics_file = tmp_path / "prompt-builder.ndjson"
    _write_ndjson(metrics_file, _sample_rows())

    result = _run_metrics(
        workspace,
        "summary",
        "--scope",
        "prompt-builder",
        "--input",
        str(metrics_file),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["scope"] == "prompt-builder"
    assert payload["sample_count"] == 10
    assert payload["parse_success_rate"] == 0.8
    assert payload["fallback_count"] == 2
    assert payload["fallback_rate"] == 0.2
    assert payload["fallback_reasons"] == {"schema_fail": 1, "ref_missing": 1}
    assert abs(payload["avg_token_count_estimate"] - 450) <= 1


def test_metrics_summary_baseline_reduction(tmp_path):
    workspace = _workspace(tmp_path)
    metrics_file = tmp_path / "prompt-builder.ndjson"
    _write_ndjson(
        metrics_file,
        [
            {
                "timestamp": "2026-04-01T00:00:00Z",
                "parse_status": "ok",
                "token_count_estimate": 1800,
                "fallback_reason": None,
                "tags": ["baseline"],
            },
            {
                "timestamp": "2026-04-02T00:00:00Z",
                "parse_status": "ok",
                "token_count_estimate": 2200,
                "fallback_reason": None,
                "tags": ["baseline"],
            },
            {
                "timestamp": "2026-04-03T00:00:00Z",
                "parse_status": "ok",
                "token_count_estimate": 1200,
                "fallback_reason": None,
                "tags": [],
            },
            {
                "timestamp": "2026-04-04T00:00:00Z",
                "parse_status": "ok",
                "token_count_estimate": 1400,
                "fallback_reason": None,
                "tags": [],
            },
            {
                "timestamp": "2026-04-05T00:00:00Z",
                "parse_status": "ok",
                "token_count_estimate": 1600,
                "fallback_reason": None,
                "tags": [],
            },
        ],
    )

    result = _run_metrics(
        workspace,
        "summary",
        "--scope",
        "prompt-builder",
        "--input",
        str(metrics_file),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["baseline_samples"] == 2
    assert payload["baseline_avg_token_count_estimate"] == 2000
    assert abs(payload["reduction_rate"] - 0.30) < 0.001


def test_metrics_summary_human_output(tmp_path):
    workspace = _workspace(tmp_path)
    metrics_file = tmp_path / "prompt-builder.ndjson"
    _write_ndjson(metrics_file, _sample_rows())

    result = _run_metrics(
        workspace,
        "summary",
        "--scope",
        "prompt-builder",
        "--input",
        str(metrics_file),
        "--human",
    )

    assert result.returncode == 0, result.stderr
    assert "Samples: 10" in result.stdout
    assert "Parse success: 80.0%" in result.stdout
    assert "Fallback: 20.0%" in result.stdout


def test_metrics_summary_since_filter(tmp_path):
    workspace = _workspace(tmp_path)
    metrics_file = tmp_path / "prompt-builder.ndjson"
    _write_ndjson(
        metrics_file,
        [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "parse_status": "ok",
                "token_count_estimate": 100,
                "fallback_reason": None,
            },
            {
                "timestamp": "2026-04-01T00:00:00Z",
                "parse_status": "ok",
                "token_count_estimate": 300,
                "fallback_reason": None,
            },
            {
                "timestamp": "2026-04-02T00:00:00Z",
                "parse_status": "schema_fail",
                "token_count_estimate": None,
                "fallback_reason": "schema_fail",
            },
        ],
    )

    result = _run_metrics(
        workspace,
        "summary",
        "--scope",
        "prompt-builder",
        "--input",
        str(metrics_file),
        "--since",
        "2026-04-01T00:00:00Z",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["sample_count"] == 2
    assert payload["parse_success_rate"] == 0.5
    assert payload["avg_token_count_estimate"] == 300
    assert payload["fallback_reasons"] == {"schema_fail": 1}


def test_mst_py_metrics_help(tmp_path):
    workspace = _workspace(tmp_path)

    result = subprocess.run(
        [sys.executable, str(MST), "metrics", "--help"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "summary" in result.stdout
