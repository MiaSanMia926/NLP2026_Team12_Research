"""Build traceable, sliced evaluation tables and paired comparisons in one command."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

from .bootstrap import paired_bootstrap
from .manifest import audit_manifest
from .metrics import GROUP_FIELDS, grouped_summaries, load_jsonl, risk_curve, summarize

COMPARISON_FIELDS = tuple(k for k in GROUP_FIELDS if k not in {"method", "config_hash"})
REPLICA_FIELDS = tuple(k for k in GROUP_FIELDS if k not in {"condition_id", "replica_condition"})
DEFAULT_METRICS = ("coverage", "selective_risk", "em_all_rows", "aurc")
REPLICA_METRICS = ("replica.decision_change_rate", "replica.normalized_answer_change_rate")


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def flatten(value, prefix=""):
    result = {}
    for key, item in value.items():
        key = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            result.update(flatten(item, key))
        else:
            result[key] = item
    return result


def write_csv(path, rows, columns=None):
    columns = columns or list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items()})


def group_rows(rows, fields):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row.get(k) for k in fields)].append(row)
    return [(dict(zip(fields, key)), group) for key, group in sorted(groups.items(), key=lambda x: repr(x[0]))]


def compare(rows, method_a, method_b, replicates, seed, replica=False):
    fields = tuple(k for k in COMPARISON_FIELDS if not replica or k not in {"condition_id", "replica_condition"})
    selected = [r for r in rows if r["method"] in {method_a, method_b}]
    results = []
    for context, group in group_rows(selected, fields):
        if replica:
            group = [r for r in group if r["replica_condition"] in {"no_replica", "same_source_replica"}]
            if not group:
                continue
        ids = {m: {r["base_question_id"] for r in group if r["method"] == m} for m in (method_a, method_b)}
        diagnostic = {"slice": context, "method_a": method_a, "method_b": method_b,
                      "difference_direction": "A minus B", "panel": "replica" if replica else "condition",
                      "missing_from_a": sorted(ids[method_b] - ids[method_a]),
                      "missing_from_b": sorted(ids[method_a] - ids[method_b]),
                      "failed_counts_by_method": {m: sum(r["method"] == m and r["status"] != "ok" for r in group) for m in (method_a, method_b)},
                      "failed_run_ids": sorted(r["run_id"] for r in group if r["status"] != "ok")}
        if diagnostic["missing_from_a"] or diagnostic["missing_from_b"]:
            results.append(dict(diagnostic, status="not_comparable", reason="unpaired base questions", statistics=[]))
            continue
        statistics = []
        try:
            if replica:
                for method in (method_a, method_b):
                    for _, panel in group_rows([r for r in group if r["method"] == method], ("base_question_id",)):
                        if {r["replica_condition"] for r in panel} != {"no_replica", "same_source_replica"}:
                            raise ValueError("incomplete replica panel")
            for metric in REPLICA_METRICS if replica else DEFAULT_METRICS:
                stat = paired_bootstrap(group, method_a, method_b, metric, replicates, seed)
                stat["status"] = "ok" if stat["observed_difference"] is not None else "undefined"
                statistics.append(stat)
        except ValueError as exc:
            results.append(dict(diagnostic, status="not_comparable", reason=str(exc), statistics=[]))
        else:
            results.append(dict(diagnostic, status="ok", statistics=statistics))
    if not selected:
        results.append({"slice": {}, "method_a": method_a, "method_b": method_b,
                        "panel": "replica" if replica else "condition",
                        "status": "not_comparable", "reason": "neither method present", "statistics": []})
    return results


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_report(input_path, output, manifest=None, pairs=None, replicates=2000, seed=20261019, label="software-selfcheck", figures=False, figure_style="journal"):
    if replicates < 1 or seed < 0:
        raise ValueError("positive replicates and nonnegative seed required")
    if label not in {"software-selfcheck", "pilot", "frozen-test"}:
        raise ValueError("invalid report label")
    if label == "frozen-test" and manifest is None:
        raise ValueError("frozen-test requires a manifest; freeze approval remains a team responsibility")
    rows = load_jsonl(input_path)
    audit = audit_manifest(rows, manifest)
    if label == "frozen-test" and any(r["split"] != "test" for r in rows):
        raise ValueError("frozen-test cannot include train/dev")
    pairs = pairs if pairs is not None else [("B7", "B5")]
    if not pairs or any(a == b or not a or not b for a, b in pairs):
        raise ValueError("comparisons require different nonempty method names")
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory must be new or empty; choose another path to preserve prior reports")
    # Finish calculations before creating an output bundle.
    summary = grouped_summaries(rows)
    summary.update(label=label, manifest_audit=audit)
    comparisons = []
    for a, b in pairs:
        comparisons.extend(compare(rows, a, b, replicates, seed))
        comparisons.extend(compare(rows, a, b, replicates, seed, replica=True))
    curves, curve_audit = [], []
    plot_data = []
    for context, group in group_rows(rows, GROUP_FIELDS):
        for mode in ("candidate", "answered"):
            curve = risk_curve(group, mode)
            curve_audit.append(dict(context, curve_mode=mode, available=curve["available"], reason=curve["reason"], max_coverage=curve["max_coverage"]))
            curves.extend(dict(context, curve_mode=mode, **p) for p in curve["points"])
            if mode == "candidate":
                plot_data.append((context, curve))
    replicas = [{"slice": context, "metrics": summarize(group)["replica"]}
                for context, group in group_rows([r for r in rows if r["replica_condition"] in {"no_replica", "same_source_replica"}], REPLICA_FIELDS)]
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "summary.json", summary)
    write_csv(output / "summary.csv", [dict(g["slice"], **flatten(g["metrics"])) for g in summary["groups"]])
    write_json(output / "comparisons.json", comparisons)
    write_csv(output / "comparisons.csv", [{**c["slice"], **{k: v for k, v in c.items() if k not in {"slice", "statistics", "status"}},
                                          "comparison_status": c["status"], **flatten(s)}
                                         for c in comparisons for s in (c["statistics"] or [{}])])
    write_json(output / "replica.json", replicas)
    write_json(output / "curve_audit.json", curve_audit)
    write_csv(output / "risk_coverage.csv", curves, list(GROUP_FIELDS)+["curve_mode", "coverage", "risk", "accepted", "score_threshold"])
    write_json(output / "manifest_audit.json", audit)
    write_csv(output / "manifest_coverage.csv", [{**g["slice"], **{k: v for k, v in g.items() if k != "slice"}}
                                               for g in audit["groups"]],
              list(GROUP_FIELDS) + ["planned_n", "provided_n", "ok_n", "failed_n", "missing_n", "extra_n",
                                    "trace_mismatch_n", "blocked_n", "completion_rate"])
    write_json(output / "failures.json", [{k: r[k] for k in ("run_id", "raw_log_id", "base_question_id", "method", "status")} for r in rows if r["status"] != "ok"])
    figure_status = "not_requested"
    if figures:
        figure_status = render_figures(output, plot_data, label, rows, figure_style)
    provenance = {"label": label, "input": str(input_path.resolve()), "input_sha256": sha256(input_path),
                  "manifest": str(manifest.resolve()) if manifest else None,
                  "manifest_sha256": sha256(manifest) if manifest else None,
                  "replicates": replicates, "bootstrap_seed": seed, "comparisons": pairs,
                  "python": sys.version, "figure_status": figure_status, "figure_style": figure_style,
                  "code_sha256": {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
                  "schema_sha256": {p.name: sha256(p) for p in sorted((Path(__file__).parent.parent / "schemas").glob("*.json"))},
                  "note": "Labels are supplied by the caller and are not evidence of team approval or actual model execution."}
    write_json(output / "provenance.json", provenance)
    notes = [f"# Evaluation bundle: {label}", "", "软件样例不得作为研究结果。pilot 为探索结果；frozen-test 标签不替代团队冻结审核。", "",
             f"- 输入记录：{len(rows)}；切片：{len(summary['groups'])}。",
             f"- Manifest：{audit['status']}。未核对时，planned_n 仅表示输入记录数。",
             "- 计划分母见 manifest_coverage.csv；整组漏跑也会显示。complete 仅表示记录齐全且来源匹配；失败次数单列，不表示全部运行成功。",
             f"- 比较不可用：{sum(c['status'] != 'ok' for c in comparisons)}；详情见 comparisons.json。",
             f"- 图片状态：{figure_status}。曲线坐标始终保存为 CSV。", "",
             "主表：summary.csv；差值/CI：comparisons.csv；配对缺失和失败排除：comparisons.json；复本诊断：replica.json；曲线不可用原因：curve_audit.json；来源哈希：provenance.json。",
             "", "差值方向为 A−B；风险/AURC 负值表示 A 更低。所有 CI 基于配对成功子集，须同时查看失败排除。空值不填零，不自动作显著性声明。",
             "独立支持保留使用人工可靠 gold；事实外检和受控任务分开。费用字段由运行方汇总全部尝试，空值表示未提供。"]
    (output / "README.md").write_text("\n".join(notes)+"\n", encoding="utf-8")
    write_json(output / "bundle_hashes.json", {p.name: sha256(p) for p in sorted(output.rglob("*")) if p.is_file()})
    return {"output": str(output), "records": len(rows), "manifest_status": audit["status"], "figure_status": figure_status}


def render_figures(output, curves, label, rows=None, figure_style="journal"):
    try:
        from .publication import render_report_figures
        return render_report_figures(output, curves, label, rows, style=figure_style)
    except ImportError:
        return "unavailable_matplotlib"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--compare", action="append", metavar="A:B", help="repeat for ablations; default B7:B5")
    parser.add_argument("--replicates", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261019)
    parser.add_argument("--label", choices=["software-selfcheck", "pilot", "frozen-test"], default="software-selfcheck")
    parser.add_argument("--figures", action="store_true")
    parser.add_argument("--figure-style", choices=["journal", "minimal", "warm", "monochrome"], default="journal")
    args = parser.parse_args()
    try:
        pairs = None
        if args.compare:
            pairs = []
            for pair in args.compare:
                if pair.count(":") != 1:
                    raise ValueError("--compare requires A:B")
                pairs.append(tuple(pair.split(":")))
        result = build_report(args.input, args.output_dir, args.manifest, pairs, args.replicates, args.seed, args.label, args.figures, args.figure_style)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["manifest_status"] == "incomplete" or (args.figures and result["figure_status"] == "unavailable_matplotlib") else 0


if __name__ == "__main__":
    raise SystemExit(main())
