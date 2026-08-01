#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECTION_ROOT = REPO_ROOT / "plugins" / "mst"

COPY_PATHS = [
    ".codex-plugin",
    "agents",
    "dashboard",
    "dist",
    "scripts",
    "skills",
    "src",
    "templates",
    "README.md",
    "README.en.md",
    "LICENSE",
    "package.json",
    "package-lock.json",
    "state-schema.json",
]

EXTENSION_PATHS = [
    "dist",
    "icons",
    "manifest.json",
    "package.json",
    "package-lock.json",
]

HOOK_PATHS = [
    Path("enforce-tree.json"),
    Path("stop-agile-gate-reasons.json"),
    Path("lib/pre_tool_use_fast.py"),
    Path("lib/pre_tool_use_fast_shards"),
]

CODEX_AGILE_NOTE = """### Codex Projection Invocation Contract

This generated Codex projection uses Codex-native explicit skill mentions for agile-plan child delegation.

- Invoke agile-plan as `$mst:agile-plan ...`; do not emit the Claude-style `Skill(...)` call.
- Do not inline agile-plan work from the agile skill when Step 1 or Step 3.4 requires delegation.
- If the host cannot perform an explicit skill invocation, stop and print the `$mst:agile-plan ...` fallback command as the next action.

"""

CODEX_AGILE_PLAN_NOTE = """### Codex Projection Invocation Contract

In Codex, explicit `$mst:agile-plan` invocation is the command identity for this skill and is equivalent to the Claude-facing `/mst:agile-plan` command. Once `$mst:agile-plan` or `/mst:agile-plan` is present in the raw request, keep that identity fixed through Exit.

"""


def replace_required(text: str, old: str, new: str, *, rel_path: Path) -> str:
    if old not in text:
        raise RuntimeError(f"Projection rewrite marker not found in {rel_path}: {old!r}")
    return text.replace(old, new)


def rewrite_agile_skill_for_codex(text: str, rel_path: Path) -> str:
    purpose = (
        "**목적**: 프로젝트 목표를 받아 JTBD+프로젝트 DoD 기반 objective 흐름을 "
        "`agile-plan`으로 초기화하고, 프로젝트 건강 우선 스프린트 루프를 진행합니다."
    )
    text = replace_required(
        text,
        f"{purpose}\n\n핵심 우회 금지 규칙은 아래 Gate/체크리스트 섹션을 따른다.",
        f"{purpose}\n\n{CODEX_AGILE_NOTE}핵심 우회 금지 규칙은 아래 Gate/체크리스트 섹션을 따른다.",
        rel_path=rel_path,
    )
    text = replace_required(
        text,
        'Skill(skill: "mst:agile-plan", args: "{PROJECT_GOAL_OR_DOC} {DOC_FLAG_IF_ANY} --return-to agile/1 {AUTO_FLAG_IF_TRUE}")',
        "$mst:agile-plan {PROJECT_GOAL_OR_DOC} {DOC_FLAG_IF_ANY} --return-to agile/1 {AUTO_FLAG_IF_TRUE}",
        rel_path=rel_path,
    )
    text = replace_required(
        text,
        'Skill(skill: "mst:agile-plan", args: "--resume {AGI_ID} --return-to agile/1 {AUTO_FLAG_IF_TRUE}")',
        "$mst:agile-plan --resume {AGI_ID} --return-to agile/1 {AUTO_FLAG_IF_TRUE}",
        rel_path=rel_path,
    )
    text = replace_required(
        text,
        '확인 증거: Step 1에서 `Skill(skill: "mst:agile-plan", ...)` 호출 로그와 반환 마커가 존재.',
        "확인 증거: Step 1에서 `$mst:agile-plan ...` 명시 호출 로그와 반환 마커가 존재.",
        rel_path=rel_path,
    )
    return text


def rewrite_agile_plan_skill_for_codex(text: str, rel_path: Path) -> str:
    purpose = (
        "**목적**: `/mst:agile-plan`으로 JTBD + 프로젝트 DoD 중심의 objective.md를 생성한다. "
        "이 스킬은 플래닝 전용이며 Story 생성/실행은 담당하지 않는다."
    )
    text = replace_required(
        text,
        f"{purpose}\n\n## ⚠️ 실행 제약 (CRITICAL — 항상 준수)",
        (
            "**목적**: `$mst:agile-plan`(Codex) 또는 `/mst:agile-plan`(Claude)으로 "
            "JTBD + 프로젝트 DoD 중심의 objective.md를 생성한다. 이 스킬은 플래닝 전용이며 "
            "Story 생성/실행은 담당하지 않는다."
            f"\n\n{CODEX_AGILE_PLAN_NOTE}## ⚠️ 실행 제약 (CRITICAL — 항상 준수)"
        ),
        rel_path=rel_path,
    )
    text = replace_required(
        text,
        "`/mst:agile-plan --resume AGI-NNN --doc spec.md --return-to agile/1 --auto`: resume wins, doc ignored for mode, return-to is exit routing, auto only changes interaction policy.",
        "`$mst:agile-plan --resume AGI-NNN --doc spec.md --return-to agile/1 --auto`(Codex) / `/mst:agile-plan --resume AGI-NNN --doc spec.md --return-to agile/1 --auto`(Claude): resume wins, doc ignored for mode, return-to is exit routing, auto only changes interaction policy.",
        rel_path=rel_path,
    )
    text = replace_required(
        text,
        "`/mst:agile-plan --doc spec.md` with no canonical identity mutation request: doc mode wins over Q&A.",
        "`$mst:agile-plan --doc spec.md`(Codex) / `/mst:agile-plan --doc spec.md`(Claude) with no canonical identity mutation request: doc mode wins over Q&A.",
        rel_path=rel_path,
    )
    text = replace_required(
        text,
        "원시 입력의 command identity가 `/mst:agile-plan`으로 확정된 경우, 이 정체성을 Exit까지 고정한다.",
        "원시 입력의 command identity가 `$mst:agile-plan`(Codex) 또는 `/mst:agile-plan`(Claude)로 확정된 경우, 이 정체성을 Exit까지 고정한다.",
        rel_path=rel_path,
    )
    text = replace_required(
        text,
        "`/mst:agile-plan` 입력 본문에 `현재 구현을 변경`, `수정`, `구현 변경`, `개선`, `리팩터링`, `계획`, `구현`, `방향` 같은 구현 변경 또는 계획 수립 표현이 있어도 `/mst:plan`, `/mst:request`, Claude Code 내장 plan mode로 재분류하지 않는다.",
        "`$mst:agile-plan`/`/mst:agile-plan` 입력 본문에 `현재 구현을 변경`, `수정`, `구현 변경`, `개선`, `리팩터링`, `계획`, `구현`, `방향` 같은 구현 변경 또는 계획 수립 표현이 있어도 `$mst:plan`/`/mst:plan`, `$mst:request`/`/mst:request`, 내장 plan mode로 재분류하지 않는다.",
        rel_path=rel_path,
    )
    text = replace_required(
        text,
        "원시 입력의 command identity가 `/mst:agile-plan`으로 확정된 경우, 이 정체성을 Exit까지 유지한다.",
        "원시 입력의 command identity가 `$mst:agile-plan`(Codex) 또는 `/mst:agile-plan`(Claude)로 확정된 경우, 이 정체성을 Exit까지 유지한다.",
        rel_path=rel_path,
    )
    text = replace_required(
        text,
        "이 guard는 `/mst:agile-plan` command identity가 확정된 요청에만 적용한다. 일반 `/mst:plan` 및 `/mst:request` 요청의 command identity, 사용자 대면 라우팅, 산출물 절차는 변경하지 않는다.",
        "이 guard는 `$mst:agile-plan`/`/mst:agile-plan` command identity가 확정된 요청에만 적용한다. 일반 `$mst:plan`/`/mst:plan` 및 `$mst:request`/`/mst:request` 요청의 command identity, 사용자 대면 라우팅, 산출물 절차는 변경하지 않는다.",
        rel_path=rel_path,
    )
    text = replace_required(
        text,
        "재현 fixture `/mst:agile-plan 그럼 현재 구현을 변경하는 방향으로 수정해줘`는 agile-plan 절차의 objective/agile planning 입력으로 먼저 처리한다.",
        "재현 fixture `$mst:agile-plan 그럼 현재 구현을 변경하는 방향으로 수정해줘`(Codex) 또는 `/mst:agile-plan 그럼 현재 구현을 변경하는 방향으로 수정해줘`(Claude)는 agile-plan 절차의 objective/agile planning 입력으로 먼저 처리한다.",
        rel_path=rel_path,
    )
    text = replace_required(
        text,
        "> 목적: `/mst:agile-plan` 호출 자체는 objective 정의 의도 신호이지만, args 본문이 메타/질문이거나 0.5.2에서 \"다른 의도\"로 응답한 경우, 요청 동작을 먼저 수행한 뒤 objective 후보를 선제시한다.",
        "> 목적: `$mst:agile-plan`/`/mst:agile-plan` 호출 자체는 objective 정의 의도 신호이지만, args 본문이 메타/질문이거나 0.5.2에서 \"다른 의도\"로 응답한 경우, 요청 동작을 먼저 수행한 뒤 objective 후보를 선제시한다.",
        rel_path=rel_path,
    )
    return text


CODEX_SKILL_REWRITES = {
    Path("skills/agile/SKILL.md"): rewrite_agile_skill_for_codex,
    Path("skills/agile-plan/SKILL.md"): rewrite_agile_plan_skill_for_codex,
}


def copy_path(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        ignore = shutil.ignore_patterns("node_modules", ".omc", "__pycache__", ".pytest_cache")
        if source.name == "scripts":
            ignore = shutil.ignore_patterns(
                "node_modules",
                ".omc",
                "__pycache__",
                ".pytest_cache",
                "tests",
                "test_*.py",
            )
        shutil.copytree(source, target, symlinks=False, ignore=ignore)
    else:
        shutil.copy2(source, target)


def reset_projection(projection_root: Path) -> None:
    if projection_root.exists() or projection_root.is_symlink():
        if projection_root.is_symlink() or projection_root.is_file():
            projection_root.unlink()
        else:
            shutil.rmtree(projection_root)
    projection_root.mkdir(parents=True)


def apply_codex_projection_rewrites(projection_root: Path) -> None:
    for rel_path, rewrite in CODEX_SKILL_REWRITES.items():
        path = projection_root / rel_path
        text = path.read_text(encoding="utf-8")
        rewritten = rewrite(text, rel_path)
        path.write_text(rewritten, encoding="utf-8")


def generate_projection(projection_root: Path) -> None:
    reset_projection(projection_root)

    for rel in COPY_PATHS:
        copy_path(REPO_ROOT / rel, projection_root / rel)

    extension_root = projection_root / "extension"
    extension_root.mkdir()
    for rel in EXTENSION_PATHS:
        source = REPO_ROOT / "extension" / rel
        if source.exists():
            copy_path(source, extension_root / rel)

    hooks_root = projection_root / "hooks"
    hooks_root.mkdir()
    for rel in HOOK_PATHS:
        copy_path(REPO_ROOT / "hooks" / rel, hooks_root / rel)

    apply_codex_projection_rewrites(projection_root)


def projection_drift(expected_root: Path, actual_root: Path) -> list[str]:
    def files(root: Path) -> dict[str, bytes]:
        if not root.is_dir():
            return {}
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    expected = files(expected_root)
    actual = files(actual_root)
    paths = sorted(set(expected) | set(actual))
    return [path for path in paths if expected.get(path) != actual.get(path)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync the generated Codex plugin projection")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify projection drift without modifying plugins/mst",
    )
    args = parser.parse_args(argv)

    if args.check:
        with tempfile.TemporaryDirectory(prefix="mst-codex-projection-check-") as temp_dir:
            expected_root = Path(temp_dir) / "mst"
            generate_projection(expected_root)
            drift = projection_drift(expected_root, PROJECTION_ROOT)
        if drift:
            print("Codex plugin projection drift detected:")
            for path in drift:
                print(f"- {path}")
            return 1
        print(f"Codex plugin projection check passed: {PROJECTION_ROOT}")
        return 0

    generate_projection(PROJECTION_ROOT)

    print(f"Synced Codex plugin projection: {PROJECTION_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
