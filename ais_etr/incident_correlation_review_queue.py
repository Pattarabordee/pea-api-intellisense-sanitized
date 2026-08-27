from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any, Iterable

CANDIDATE_SCHEMA = "incident-correlation-review-candidate.v1"
LABEL_SCHEMA = "incident-correlation-review-label.v1"
MANIFEST_SCHEMA = "incident-correlation-review-queue-manifest.v1"

PAIR_RE = re.compile(r"^pair_[a-z0-9]{8,64}$")
REPORT_RE = re.compile(r"^report_[a-z0-9]{8,64}$")
ENGINE_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")

CANDIDATE_KEYS = {
    "schema_version",
    "pair_ref",
    "report_ref_a",
    "report_ref_b",
    "engine_version",
    "evidence",
}
EVIDENCE_KEYS = {
    "temporal_delta_minutes",
    "channel_relation",
    "admin_relation",
    "feeder_relation",
    "transformer_relation",
    "upstream_relation",
    "topology_freshness_relation",
    "topology_authoritative_relation",
    "planned_outage_relation",
}
LABEL_KEYS = {
    "schema_version",
    "pair_ref",
    "review_case_ref",
    "label",
    "risk_tier",
    "split",
}

ENUMS = {
    "channel_relation": {"SAME_CHANNEL", "DIFFERENT_CHANNEL", "UNKNOWN"},
    "admin_relation": {
        "SAME_VILLAGE",
        "DIFFERENT_VILLAGE_SAME_SUBDISTRICT",
        "SAME_SUBDISTRICT",
        "SAME_DISTRICT",
        "SAME_PROVINCE",
        "DIFFERENT_PROVINCE",
        "UNKNOWN",
    },
    "feeder_relation": {"SAME_FEEDER", "DIFFERENT_FEEDER", "ONE_OR_BOTH_UNKNOWN"},
    "transformer_relation": {
        "SAME_TRANSFORMER",
        "DIFFERENT_TRANSFORMER",
        "ONE_OR_BOTH_UNKNOWN",
    },
    "upstream_relation": {"SHARED_UPSTREAM", "DIFFERENT_OR_UNKNOWN"},
    "topology_freshness_relation": {"BOTH_FRESH", "BOTH_NOT_FRESH", "MIXED_OR_UNKNOWN"},
    "topology_authoritative_relation": {"BOTH_AUTHORITATIVE", "NOT_BOTH_AUTHORITATIVE"},
    "planned_outage_relation": {
        "BOTH_UNPLANNED_OR_NOT_CHECKED",
        "ONE_OR_BOTH_MATCHED",
        "UNCERTAIN",
    },
}
LABELS = {"SAME_INCIDENT", "DIFFERENT_INCIDENT", "INSUFFICIENT_EVIDENCE"}
RISK_TIERS = {"NORMAL", "HIGH", "CRITICAL"}
SPLITS = {"CALIBRATION", "EVALUATION", "UNSPECIFIED"}


class ReviewQueueError(ValueError):
    pass


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReviewQueueError(f"{path.name}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ReviewQueueError(f"{path.name}:{line_no}: each JSONL row must be an object")
        rows.append(value)
    return rows


def _validate_exact_keys(value: dict[str, Any], expected: set[str], where: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ReviewQueueError(f"{where}: schema key mismatch; missing={missing}, extra={extra}")


def validate_candidate(row: dict[str, Any], index: int) -> dict[str, Any]:
    where = f"candidate[{index}]"
    _validate_exact_keys(row, CANDIDATE_KEYS, where)
    if row["schema_version"] != CANDIDATE_SCHEMA:
        raise ReviewQueueError(f"{where}: schema_version must be {CANDIDATE_SCHEMA}")
    if not isinstance(row["pair_ref"], str) or not PAIR_RE.fullmatch(row["pair_ref"]):
        raise ReviewQueueError(f"{where}: invalid pair_ref")
    for key in ("report_ref_a", "report_ref_b"):
        if not isinstance(row[key], str) or not REPORT_RE.fullmatch(row[key]):
            raise ReviewQueueError(f"{where}: invalid {key}")
    if row["report_ref_a"] == row["report_ref_b"]:
        raise ReviewQueueError(f"{where}: report refs must identify two distinct reports")
    if not isinstance(row["engine_version"], str) or not ENGINE_RE.fullmatch(row["engine_version"]):
        raise ReviewQueueError(f"{where}: invalid engine_version")
    evidence = row["evidence"]
    if not isinstance(evidence, dict):
        raise ReviewQueueError(f"{where}.evidence: must be an object")
    _validate_exact_keys(evidence, EVIDENCE_KEYS, f"{where}.evidence")
    delta = evidence["temporal_delta_minutes"]
    if isinstance(delta, bool) or not isinstance(delta, (int, float)) or delta < 0 or delta > 525600:
        raise ReviewQueueError(f"{where}.evidence.temporal_delta_minutes: invalid range")
    normalized_evidence = dict(evidence)
    normalized_evidence["temporal_delta_minutes"] = round(float(delta), 2)
    for key, allowed in ENUMS.items():
        if evidence[key] not in allowed:
            raise ReviewQueueError(f"{where}.evidence.{key}: invalid value {evidence[key]!r}")
    return {
        "schema_version": CANDIDATE_SCHEMA,
        "pair_ref": row["pair_ref"],
        "report_ref_a": row["report_ref_a"],
        "report_ref_b": row["report_ref_b"],
        "engine_version": row["engine_version"],
        "evidence": normalized_evidence,
    }


def load_candidates(path: Path) -> list[dict[str, Any]]:
    rows = [validate_candidate(row, i) for i, row in enumerate(_read_jsonl(path), start=1)]
    if not rows:
        raise ReviewQueueError("candidate file is empty")
    pair_refs = [row["pair_ref"] for row in rows]
    if len(pair_refs) != len(set(pair_refs)):
        raise ReviewQueueError("duplicate pair_ref in candidate file")
    pair_reports: set[tuple[str, str]] = set()
    for row in rows:
        pair = tuple(sorted((row["report_ref_a"], row["report_ref_b"])))
        if pair in pair_reports:
            raise ReviewQueueError("duplicate report pair in candidate file")
        pair_reports.add(pair)
    engines = {row["engine_version"] for row in rows}
    if len(engines) != 1:
        raise ReviewQueueError(f"mixed engine versions are not allowed in one review queue: {sorted(engines)}")
    return rows


class _UnionFind:
    def __init__(self, values: Iterable[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a == b:
            return
        if a < b:
            self.parent[b] = a
        else:
            self.parent[a] = b


def assign_cases(rows: list[dict[str, Any]]) -> dict[str, str]:
    report_refs = sorted({row[key] for row in rows for key in ("report_ref_a", "report_ref_b")})
    uf = _UnionFind(report_refs)
    for row in rows:
        uf.union(row["report_ref_a"], row["report_ref_b"])
    components: dict[str, list[str]] = {}
    for ref in report_refs:
        components.setdefault(uf.find(ref), []).append(ref)
    component_case: dict[str, str] = {}
    for root, members in components.items():
        digest = hashlib.sha256("|".join(sorted(members)).encode("utf-8")).hexdigest()[:24]
        component_case[root] = "case_" + digest
    return {row["pair_ref"]: component_case[uf.find(row["report_ref_a"])] for row in rows}


def split_for_case(case_ref: str, seed: str, calibration_fraction: float) -> str:
    digest = hashlib.sha256(f"{seed}|{case_ref}".encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") / float(1 << 64)
    return "CALIBRATION" if bucket < calibration_fraction else "EVALUATION"


def build_review_rows(
    rows: list[dict[str, Any]], *, split_seed: str, calibration_fraction: float
) -> list[dict[str, Any]]:
    if not (0 < calibration_fraction < 1):
        raise ReviewQueueError("calibration_fraction must be between 0 and 1")
    if not split_seed or len(split_seed) > 120:
        raise ReviewQueueError("split_seed must be non-empty and <= 120 characters")
    pair_cases = assign_cases(rows)
    case_splits = {
        case_ref: split_for_case(case_ref, split_seed, calibration_fraction)
        for case_ref in sorted(set(pair_cases.values()))
    }
    output = []
    for row in sorted(rows, key=lambda item: item["pair_ref"]):
        case_ref = pair_cases[row["pair_ref"]]
        output.append(
            {
                "pair_ref": row["pair_ref"],
                "review_case_ref": case_ref,
                "split": case_splits[case_ref],
                "engine_version": row["engine_version"],
                "evidence": row["evidence"],
            }
        )
    return output


def _render_html(rows: list[dict[str, Any]], queue_ref: str) -> str:
    embedded = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    title = "PEA Intellisense — Incident Correlation Human Review Queue"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:1180px;margin:0 auto;padding:24px;background:#f7f7f8;color:#1f2328}}
h1{{font-size:24px;margin:0 0 8px}} .muted{{color:#59636e}} .banner{{padding:14px 16px;background:#fff;border:1px solid #d8dee4;border-radius:10px;margin:16px 0}}
.banner strong{{display:block;margin-bottom:5px}} .toolbar{{position:sticky;top:0;background:#f7f7f8;padding:10px 0;z-index:3;display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
button{{padding:8px 12px;border:1px solid #aab2bd;border-radius:8px;background:white;cursor:pointer}} button.primary{{font-weight:700}}
.card{{background:white;border:1px solid #d8dee4;border-radius:10px;padding:16px;margin:12px 0}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px 16px}}
.k{{font-size:12px;color:#59636e}} .v{{font-weight:600;overflow-wrap:anywhere}} fieldset{{border:0;padding:0;margin:14px 0 0}} legend{{font-weight:700;margin-bottom:6px}}
label.choice{{display:inline-block;margin:4px 10px 4px 0}} .complete{{border-left:5px solid #2da44e}} .incomplete{{border-left:5px solid #bf8700}}
code{{font-size:12px}} .status{{font-weight:700}} .warning{{color:#9a6700}} .tiny{{font-size:12px}}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<div class="muted">Queue: <code>{html.escape(queue_ref)}</code></div>
<div class="banner"><strong>Blind-review guardrail</strong>
This page contains no numeric confidence score, confidence level, relationship decision, ticket ID, raw message, customer identity, raw location, or raw electrical asset ID. Review the evidence relations only. Labels do not confirm an outage or root cause.</div>
<div class="toolbar">
<button class="primary" onclick="exportLabels()">Export complete labels JSONL</button>
<button onclick="exportAudit()">Export review audit JSON</button>
<button onclick="clearState()">Clear local review state</button>
<span class="status" id="status"></span>
</div>
<div id="cards"></div>
<script>
const QUEUE_REF={json.dumps(queue_ref)};
const ROWS={embedded};
const STORAGE_KEY='pea_incident_correlation_review_'+QUEUE_REF;
let state={{}};
try{{state=JSON.parse(localStorage.getItem(STORAGE_KEY)||'{{}}')}}catch(e){{state={{}}}}
const labelOptions=['SAME_INCIDENT','DIFFERENT_INCIDENT','INSUFFICIENT_EVIDENCE'];
const riskOptions=['NORMAL','HIGH','CRITICAL'];
function esc(s){{return String(s).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));}}
function save(){{localStorage.setItem(STORAGE_KEY,JSON.stringify(state));renderStatus();}}
function setChoice(pair,key,value){{state[pair]=state[pair]||{{}};state[pair][key]=value;save();document.getElementById('card_'+pair).className='card '+(isComplete(pair)?'complete':'incomplete');}}
function isComplete(pair){{const x=state[pair]||{{}};return labelOptions.includes(x.label)&&riskOptions.includes(x.risk_tier);}}
function renderStatus(){{const done=ROWS.filter(r=>isComplete(r.pair_ref)).length;document.getElementById('status').textContent=`Reviewed ${{done}} / ${{ROWS.length}}`;}}
function relation(label,value){{return `<div><div class="k">${{esc(label)}}</div><div class="v">${{esc(value)}}</div></div>`;}}
function render(){{
 const root=document.getElementById('cards'); root.innerHTML='';
 ROWS.forEach((r,i)=>{{const e=r.evidence;const d=document.createElement('div');d.id='card_'+r.pair_ref;d.className='card '+(isComplete(r.pair_ref)?'complete':'incomplete');
 const current=state[r.pair_ref]||{{}};
 d.innerHTML=`<div class="grid">${{relation('Pair',r.pair_ref)}}${{relation('Case',r.review_case_ref)}}${{relation('Fixed split',r.split)}}${{relation('Engine',r.engine_version)}}${{relation('Time delta (minutes)',e.temporal_delta_minutes)}}${{relation('Channel relation',e.channel_relation)}}${{relation('Admin relation',e.admin_relation)}}${{relation('Feeder relation',e.feeder_relation)}}${{relation('Transformer relation',e.transformer_relation)}}${{relation('Upstream relation',e.upstream_relation)}}${{relation('Topology freshness',e.topology_freshness_relation)}}${{relation('Topology authority',e.topology_authoritative_relation)}}${{relation('Planned-outage relation',e.planned_outage_relation)}}</div>
 <fieldset><legend>Reviewer label</legend>${{labelOptions.map(x=>`<label class="choice"><input type="radio" name="label_${{i}}" ${{current.label===x?'checked':''}} onchange="setChoice('${{r.pair_ref}}','label','${{x}}')"> ${{x}}</label>`).join('')}}</fieldset>
 <fieldset><legend>False-merge risk tier</legend>${{riskOptions.map(x=>`<label class="choice"><input type="radio" name="risk_${{i}}" ${{current.risk_tier===x?'checked':''}} onchange="setChoice('${{r.pair_ref}}','risk_tier','${{x}}')"> ${{x}}</label>`).join('')}}</fieldset>`;
 root.appendChild(d);}}); renderStatus();
}}
function labels(){{return ROWS.map(r=>({{schema_version:'incident-correlation-review-label.v1',pair_ref:r.pair_ref,review_case_ref:r.review_case_ref,label:(state[r.pair_ref]||{{}}).label,risk_tier:(state[r.pair_ref]||{{}}).risk_tier,split:r.split}}));}}
function downloadText(name,text,type){{const blob=new Blob([text],{{type:type||'text/plain;charset=utf-8'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}}
function exportLabels(){{const incomplete=ROWS.filter(r=>!isComplete(r.pair_ref));if(incomplete.length){{alert(`Complete all reviews first. Remaining: ${{incomplete.length}}`);return;}} const text=labels().map(x=>JSON.stringify(x)).join('\\n')+'\\n';downloadText('incident_correlation_review_labels.jsonl',text,'application/x-ndjson;charset=utf-8');}}
function exportAudit(){{const done=ROWS.filter(r=>isComplete(r.pair_ref)).length;const audit={{schema_version:'incident-correlation-review-audit.v1',queue_ref:QUEUE_REF,total_pairs:ROWS.length,reviewed_pairs:done,complete:done===ROWS.length,score_fields_exposed:false,customer_data_exposed:false}};downloadText('incident_correlation_review_audit.json',JSON.stringify(audit,null,2)+'\\n','application/json;charset=utf-8');}}
function clearState(){{if(confirm('Clear all local review choices for this queue?')){{state={{}};localStorage.removeItem(STORAGE_KEY);render();}}}}
render();
</script>
</body>
</html>
"""


def build_queue(
    candidate_path: Path,
    output_dir: Path,
    *,
    split_seed: str = "incident-correlation-review-v1",
    calibration_fraction: float = 0.70,
) -> dict[str, Any]:
    candidates = load_candidates(candidate_path)
    rows = build_review_rows(
        candidates, split_seed=split_seed, calibration_fraction=calibration_fraction
    )
    canonical = _json_dumps(
        {
            "rows": rows,
            "split_seed": split_seed,
            "calibration_fraction": calibration_fraction,
        }
    ).encode("utf-8")
    queue_ref = "queue_" + _sha256_bytes(canonical)[:24]
    input_bytes = candidate_path.read_bytes()
    case_refs = sorted({row["review_case_ref"] for row in rows})
    split_counts = {name: sum(row["split"] == name for row in rows) for name in ("CALIBRATION", "EVALUATION")}
    case_split_counts = {
        name: len({row["review_case_ref"] for row in rows if row["split"] == name})
        for name in ("CALIBRATION", "EVALUATION")
    }
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "queue_ref": queue_ref,
        "engine_version": candidates[0]["engine_version"],
        "candidate_input_sha256": _sha256_bytes(input_bytes),
        "candidate_count": len(rows),
        "review_case_count": len(case_refs),
        "split_seed": split_seed,
        "calibration_fraction": calibration_fraction,
        "pair_split_counts": split_counts,
        "case_split_counts": case_split_counts,
        "blind_review": True,
        "score_fields_exposed": False,
        "confidence_level_exposed": False,
        "customer_data_exposed": False,
        "raw_asset_ids_exposed": False,
        "threshold_promotion_authorized": False,
        "pair_assignments": [
            {
                "pair_ref": row["pair_ref"],
                "review_case_ref": row["review_case_ref"],
                "split": row["split"],
            }
            for row in rows
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / "incident_correlation_review_queue.html"
    manifest_path = output_dir / "incident_correlation_review_queue_manifest.json"
    html_path.write_text(_render_html(rows, queue_ref), encoding="utf-8", newline="\n")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest


def validate_label(row: dict[str, Any], index: int) -> dict[str, Any]:
    where = f"label[{index}]"
    _validate_exact_keys(row, LABEL_KEYS, where)
    if row["schema_version"] != LABEL_SCHEMA:
        raise ReviewQueueError(f"{where}: schema_version must be {LABEL_SCHEMA}")
    if not isinstance(row["pair_ref"], str) or not PAIR_RE.fullmatch(row["pair_ref"]):
        raise ReviewQueueError(f"{where}: invalid pair_ref")
    if not isinstance(row["review_case_ref"], str) or not re.fullmatch(r"case_[a-f0-9]{24}", row["review_case_ref"]):
        raise ReviewQueueError(f"{where}: invalid review_case_ref")
    if row["label"] not in LABELS:
        raise ReviewQueueError(f"{where}: invalid label")
    if row["risk_tier"] not in RISK_TIERS:
        raise ReviewQueueError(f"{where}: invalid risk_tier")
    if row["split"] not in SPLITS:
        raise ReviewQueueError(f"{where}: invalid split")
    return dict(row)


def validate_labels_file(labels_path: Path, manifest_path: Path | None = None, *, allow_partial: bool = False) -> dict[str, Any]:
    labels = [validate_label(row, i) for i, row in enumerate(_read_jsonl(labels_path), start=1)]
    if not labels:
        raise ReviewQueueError("label file is empty")
    pair_refs = [row["pair_ref"] for row in labels]
    if len(pair_refs) != len(set(pair_refs)):
        raise ReviewQueueError("duplicate pair_ref in label file")
    case_splits: dict[str, set[str]] = {}
    for row in labels:
        case_splits.setdefault(row["review_case_ref"], set()).add(row["split"])
    leakage = {case: splits for case, splits in case_splits.items() if len(splits) > 1}
    if leakage:
        raise ReviewQueueError(f"case-level split leakage detected: {leakage}")
    manifest = None
    if manifest_path is not None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != MANIFEST_SCHEMA:
            raise ReviewQueueError("invalid review queue manifest schema")
        expected = {item["pair_ref"]: item for item in manifest.get("pair_assignments", [])}
        actual = set(pair_refs)
        unknown = sorted(actual - set(expected))
        if unknown:
            raise ReviewQueueError(f"labels contain pair_ref values not present in manifest: {unknown}")
        missing = sorted(set(expected) - actual)
        if missing and not allow_partial:
            raise ReviewQueueError(f"labels are incomplete for queue; missing {len(missing)} pairs")
        for row in labels:
            item = expected[row["pair_ref"]]
            if row["review_case_ref"] != item["review_case_ref"] or row["split"] != item["split"]:
                raise ReviewQueueError(f"manifest assignment mismatch for {row['pair_ref']}")
    return {
        "schema_version": "incident-correlation-review-label-validation.v1",
        "valid": True,
        "label_count": len(labels),
        "case_count": len(case_splits),
        "same_incident": sum(row["label"] == "SAME_INCIDENT" for row in labels),
        "different_incident": sum(row["label"] == "DIFFERENT_INCIDENT" for row in labels),
        "insufficient_evidence": sum(row["label"] == "INSUFFICIENT_EVIDENCE" for row in labels),
        "manifest_checked": manifest is not None,
        "partial_allowed": allow_partial,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and validate a blind Incident Correlation human-review queue.")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="Build a static blind-review queue from privacy-safe JSONL candidates.")
    build.add_argument("--candidates", required=True, type=Path)
    build.add_argument("--output-dir", required=True, type=Path)
    build.add_argument("--split-seed", default="incident-correlation-review-v1")
    build.add_argument("--calibration-fraction", type=float, default=0.70)
    validate = sub.add_parser("validate-labels", help="Validate an exported review-label JSONL file.")
    validate.add_argument("--labels", required=True, type=Path)
    validate.add_argument("--manifest", type=Path)
    validate.add_argument("--allow-partial", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_queue(
                args.candidates,
                args.output_dir,
                split_seed=args.split_seed,
                calibration_fraction=args.calibration_fraction,
            )
        else:
            result = validate_labels_file(args.labels, args.manifest, allow_partial=args.allow_partial)
    except ReviewQueueError as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
