from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def _run_lightweight_command(argv: list[str]) -> bool:
    """Run dependency-light commands without importing the full CLI module."""
    if len(argv) < 2:
        return False

    command = argv[1]
    if command == "export-sanitized-codebase":
        from .production_path import export_sanitized_codebase

        parser = argparse.ArgumentParser(
            prog=f"{Path(argv[0]).name} export-sanitized-codebase",
            description="Build a ChatGPT-safe source bundle without loading data-science dependencies.",
        )
        parser.add_argument("--output-dir", default="runtime/chatgpt_production_review")
        parser.add_argument("--zip-output", default="runtime/sanitized_codebase_bundle.zip")
        parser.add_argument("--manifest-output", default="runtime/sanitized_codebase_manifest.json")
        parser.add_argument("--prompt-output", default="runtime/chatgpt_production_review_prompt.md")
        parser.add_argument("--audit-output", default="runtime/chatgpt_production_review_audit.md")
        args = parser.parse_args(argv[2:])
        result = export_sanitized_codebase(
            Path.cwd(),
            output_dir=Path(args.output_dir),
            zip_output=Path(args.zip_output),
            manifest_output=Path(args.manifest_output),
            prompt_output=Path(args.prompt_output),
            audit_output=Path(args.audit_output),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return True

    if command == "production-readiness-gate":
        from .production_path import build_production_readiness_gate

        parser = argparse.ArgumentParser(
            prog=f"{Path(argv[0]).name} production-readiness-gate",
            description="Build the cloud production path gate while keeping customer-facing Auto ETR blocked.",
        )
        parser.add_argument("--cloud-dir", default="runtime/cloud_pilot")
        parser.add_argument("--sanitized-manifest", default="runtime/sanitized_codebase_manifest.json")
        parser.add_argument("--pilot-gate-file", default="runtime/pilot_completion_gate.json")
        parser.add_argument("--green-gate-file", default="runtime/green_gate_tracker.md")
        parser.add_argument("--production-gate-file", default="runtime/production_readiness_gate.md")
        parser.add_argument("--owner-approval-file", default="runtime/cloud_pilot/owner_approval_status.json")
        parser.add_argument("--output", default="runtime/production_path_readiness_gate.md")
        parser.add_argument("--json-output", default="runtime/production_path_readiness_gate.json")
        args = parser.parse_args(argv[2:])
        result = build_production_readiness_gate(
            Path.cwd(),
            cloud_dir=Path(args.cloud_dir),
            sanitized_manifest=Path(args.sanitized_manifest),
            pilot_gate_file=Path(args.pilot_gate_file),
            green_gate_file=Path(args.green_gate_file),
            production_gate_file=Path(args.production_gate_file),
            owner_approval_file=Path(args.owner_approval_file),
            output_markdown=Path(args.output),
            output_json=Path(args.json_output),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return True

    return False


if __name__ == "__main__":
    if not _run_lightweight_command(sys.argv):
        from .cli import main

        main()
