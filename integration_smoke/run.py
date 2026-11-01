"""One command: synthetic A -> public-only B -> C evaluation and fault probes."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

from evaluation.metrics import check_manifest
from evaluation.report import build_report
from evaluation.validation import load_records
from .backend import METHODS
from .dataset import build_dataset, read_jsonl, write_jsonl
from .runner import execute, score_outputs


def probes(rows, manifest_path, directory):
    directory.mkdir(parents=True, exist_ok=True)
    results = []
    bad = directory/"probe.jsonl"
    variants = [("duplicate_run", rows+[rows[0]]),
                ("family_split_leak", rows+[dict(rows[0], run_id="probe-leak", pair_id="probe-pair", split="dev" if rows[0]["split"] == "train" else "train")])]
    for name, data in variants:
        write_jsonl(bad, data)
        try:
            load_records(bad)
        except ValueError as exc:
            results.append({"probe": name, "passed": True, "detail": str(exc)})
        else:
            results.append({"probe": name, "passed": False})
    try:
        check_manifest(rows[:-1], manifest_path)
    except ValueError as exc:
        results.append({"probe": "missing_manifest_run", "passed": True, "detail": str(exc)})
    else:
        results.append({"probe": "missing_manifest_run", "passed": False})
    changed = copy.deepcopy(rows)
    changed[0]["position_seed"] += 1
    try:
        check_manifest(changed, manifest_path)
    except ValueError as exc:
        results.append({"probe": "wrong_position_seed", "passed": True, "detail": str(exc)})
    else:
        results.append({"probe": "wrong_position_seed", "passed": False})
    # A missing candidate makes full RC unavailable; it must not silently disappear.
    from evaluation.metrics import risk_curve
    subset = [dict(rows[0], candidate_answer=None, candidate_task_correct=None)]
    curve = risk_curve(subset)
    results.append({"probe": "missing_candidate_curve", "passed": not curve["available"], "detail": curve["reason"]})
    # Explicit failed-run row is schema-valid and remains an execution failure, not abstention.
    failed = dict(rows[0], status="parse_error", answered=None, prediction=None, correct=None, selection_score=None)
    write_jsonl(bad, [failed])
    load_records(bad)
    from evaluation.metrics import summarize
    stats = summarize([failed])
    results.append({"probe": "failed_run_not_refusal", "passed": stats["failed_n"] == 1 and stats["coverage"] is None})
    (directory/"checks.json").write_text(json.dumps(results, indent=2)+"\n", encoding="utf-8")
    bad.unlink()
    if not all(r["passed"] for r in results):
        raise ValueError("fault probes failed")
    return results


def run(output, count=12, replicates=200, figures=True):
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory must be new or empty")
    if replicates < 1:
        raise ValueError("replicates must be positive")
    output.mkdir(parents=True, exist_ok=True)
    data = output/"data"
    created = build_dataset(data, count)
    print(json.dumps({"phase": "dataset", **created}), flush=True)
    journal = output/"logs/attempts.jsonl"
    execution = execute(data/"manifest.jsonl", data/"public_inputs.jsonl", journal)
    before = hashlib.sha256(journal.read_bytes()).hexdigest()
    resumed = execute(data/"manifest.jsonl", data/"public_inputs.jsonl", journal)
    assert before == hashlib.sha256(journal.read_bytes()).hexdigest()
    predictions = output/"scored_predictions.jsonl"
    rows = score_outputs(data/"manifest.jsonl", data/"public_inputs.jsonl", data/"gold.jsonl", journal, predictions)
    check_manifest(rows, data/"manifest.jsonl")
    print(json.dumps({"phase": "executed", **execution, "resume_skipped": resumed["skipped_successful_runs"]}), flush=True)
    pair = [("SMOKE_gate", "SMOKE_vote")]
    full = build_report(predictions, output/"evaluation_all", data/"manifest.jsonl", pairs=pair, replicates=replicates)
    print(json.dumps({"phase": "full_report", **full}), flush=True)
    # Readable representative panel, with an EXACT matching subset manifest.
    demo = [r for r in rows if r["split"] == "dev" and r["metadata_state"] == "complete" and r["length_policy"] == "natural_length" and r["replica_condition"] in {"no_replica", "same_source_replica"}]
    demo_ids = {r["run_id"] for r in demo}
    write_jsonl(output/"demo_predictions.jsonl", demo)
    write_jsonl(output/"demo_manifest.jsonl", [r for r in read_jsonl(data/"manifest.jsonl") if r["run_id"] in demo_ids])
    detailed = build_report(output/"demo_predictions.jsonl", output/"evaluation_demo", output/"demo_manifest.jsonl", pairs=pair, replicates=2000, figures=figures)
    fault_checks = probes(rows, data/"manifest.jsonl", output/"fault_probes")
    # Independent rebuild of C's numerical report checks deterministic re-computation.
    repeated = build_report(output/"demo_predictions.jsonl", output/"evaluation_recomputed", output/"demo_manifest.jsonl", pairs=pair, replicates=2000)
    for name in ("summary.json", "comparisons.json", "replica.json", "risk_coverage.csv"):
        assert (output/"evaluation_demo"/name).read_bytes() == (output/"evaluation_recomputed"/name).read_bytes()
    result = {"purpose": "OFFLINE SOFTWARE INTEGRATION ONLY — NOT LLM RESULTS", **created,
              "execution": execution, "resume": resumed, "all_manifest_status": full["manifest_status"],
              "demo_manifest_status": detailed["manifest_status"], "fault_checks_passed": len(fault_checks),
              "main_bootstrap_replicates": replicates, "demo_bootstrap_replicates": 2000,
              "deterministic_recomputation": True, "api_calls": 0, "methods": METHODS}
    (output/"validation.json").write_text(json.dumps(result, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    summary = json.loads((output/"evaluation_demo/summary.json").read_text(encoding="utf-8"))
    lines = ["# A/B → C 离线联调结果", "", "**软件验证；合成数据 + 规则后端，不是真实大模型或课程实验。**", "",
             f"{created['base_questions']} 个虚构基础题，{created['planned_runs']} 次实际规则后端运行；manifest 核对完整。",
             "", "| 条件 | 诊断方法 | 成功数 | Coverage | Risk | 全题 EM | AURC |", "|---|---|---:|---:|---:|---:|---:|"]
    for g in summary["groups"]:
        s, m = g["slice"], g["metrics"]
        def num(v):
            return "—" if v is None else f"{v:.3f}"
        lines.append(f"| {s['replica_condition']} | {s['method']} | {m['n']} | {num(m['coverage'])} | {num(m['selective_risk'])} | {num(m['em_all_rows'])} | {num(m['aurc'])} |")
    lines += ["", "本表固定 dev、complete metadata、natural length；其他条件见 evaluation_all/summary.csv，不跨条件池化。",
              "", f"自动注入并恢复 {execution['injected_retry_attempts']} 个解析失败尝试；所有原始尝试均保留；重启跳过全部成功任务且日志不变。",
              "六项故障探针、完整清单核对、四种数值输出确定性重算均通过。",
              "", "证据由生成器构造，标签由独立离线 oracle 合并。规则后端接收 public_input，不读取 gold、condition 或 split。",
              "分数是规则支持比例，SMOKE_gate 使用固定规则，未训练逻辑回归；SMOKE 方法不等于 B0–B7。",
              "重复、Verified/Tentative 和显式模板规则为人为设计，不能从这些数值推断真实语言模型收益。",
              "complementary_support 面板含两跳关系，当前规则后端不会做两跳推理；该面板用于检查保留/失效边界。",
              "tokens 使用本后端自定义正则 tokenizer 对完整序列计数，不是任何大模型的计费 token；calls 是规则调用数，实际 API 调用为零。",
              "引用标签为合成证据的自动文本蕴含检查，不是 A/D 人工审核。没有读取或冻结真实 test 集。",
              "", "数据和 gold：data/；完整原始日志：logs/；可信合并输出：scored_predictions.jsonl；全部表：evaluation_all/；可视化与 CI：evaluation_demo/；检查：validation.json。"]
    (output/"RESULTS.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--questions", type=int, default=12)
    parser.add_argument("--replicates", type=int, default=200)
    parser.add_argument("--no-figures", action="store_true")
    args = parser.parse_args()
    try:
        result = run(args.output_dir, args.questions, args.replicates, not args.no_figures)
    except (ValueError, OSError, KeyError, AssertionError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
