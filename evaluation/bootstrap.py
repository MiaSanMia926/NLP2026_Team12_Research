"""Paired cluster bootstrap; resample base questions, preserving condition pairs."""
from __future__ import annotations
import argparse
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path
try:
    from .metrics import SLICE_FIELDS, load_jsonl, summarize
except ImportError:
    from metrics import SLICE_FIELDS, load_jsonl, summarize


def get_path(value, dotted):
    for name in dotted.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(name)
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def percentile(values, probability):
    ordered = sorted(values)
    pos = (len(ordered)-1) * probability
    low, high = int(pos), min(int(pos)+1, len(ordered)-1)
    return ordered[low]*(1-(pos-low)) + ordered[high]*(pos-low)


def resample_clusters(paired, selected):
    result = []
    for occurrence, qid in enumerate(selected):
        for method_rows in paired[qid].values():
            for row in method_rows:
                copy = dict(row)
                copy["base_question_id"] = f"{row['base_question_id']}__draw_{occurrence}"
                copy["pair_id"] = f"{row['pair_id']}__draw_{occurrence}"
                result.append(copy)
    return result


def paired_bootstrap(rows, method_a="B7", method_b="B5", metric="selective_risk", replicates=2000, seed=20261019):
    if method_a == method_b or replicates < 1:
        raise ValueError("choose different methods and positive replicates")
    rows = [r for r in rows if r["method"] in {method_a, method_b}]
    if not rows:
        raise ValueError("no selected methods")
    for field in SLICE_FIELDS:
        if len({r.get(field) for r in rows}) != 1:
            raise ValueError(f"mixed {field}; filter to one comparable slice first")
    for method in (method_a, method_b):
        if len({r["config_hash"] for r in rows if r["method"] == method}) > 1:
            raise ValueError(f"multiple configurations for {method}")
    paired = {}
    for row in rows:
        paired.setdefault(row["base_question_id"], {}).setdefault(row["method"], []).append(row)
    signature = ("condition_id","metadata_state","metadata_error_type","replica_condition","position_seed")
    excluded = []
    for qid, pair in paired.items():
        if set(pair) != {method_a,method_b}:
            raise ValueError(f"unpaired method for {qid}")
        a = Counter(tuple(r[k] for k in signature) for r in pair[method_a])
        b = Counter(tuple(r[k] for k in signature) for r in pair[method_b])
        if a != b or any(count != 1 for count in a.values()):
            raise ValueError(f"missing or duplicate paired conditions for {qid}")
        if any(r["status"] != "ok" for group in pair.values() for r in group):
            excluded.append(qid)
    paired = {qid:pair for qid,pair in paired.items() if qid not in excluded}
    if not paired:
        raise ValueError("no complete successful paired questions; failures are not refusals")
    qids = sorted(paired)
    def difference(sample):
        values = [get_path(summarize([r for r in sample if r["method"]==m]), metric) for m in (method_a,method_b)]
        return values[0]-values[1] if all(v is not None for v in values) else None
    observed = difference([r for pair in paired.values() for group in pair.values() for r in group])
    rng, draws = random.Random(seed), []
    for _ in range(replicates):
        value = difference(resample_clusters(paired,[rng.choice(qids) for _ in qids]))
        if value is not None:
            draws.append(value)
    return {"method_a":method_a,"method_b":method_b,"metric":metric,"difference_direction":"A minus B",
            "observed_difference":observed,"paired_base_questions":len(qids),
            "excluded_failed_questions":sorted(excluded),"requested_replicates":replicates,
            "defined_replicates":len(draws),"undefined_replicates":replicates-len(draws),
            "ci_95":[percentile(draws,.025),percentile(draws,.975)] if draws else None,
            "confidence_level":.95,"interval_method":"percentile","seed":seed,
            "interval_warning":"more than 5% undefined replicates; interpret with caution" if len(draws)<.95*replicates else None}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("--method-a",default="B7")
    parser.add_argument("--method-b",default="B5")
    parser.add_argument("--metric",default="selective_risk")
    parser.add_argument("--replicates",type=int,default=2000)
    parser.add_argument("--seed",type=int,default=20261019)
    parser.add_argument("--where",action="append",default=[])
    parser.add_argument("--output")
    args=parser.parse_args()
    try:
        rows=load_jsonl(args.input)
        for expression in args.where:
            key,value=expression.split("=",1)
            rows=[r for r in rows if str(r.get(key))==value]
        result=paired_bootstrap(rows,args.method_a,args.method_b,args.metric,args.replicates,args.seed)
    except (ValueError,OSError) as exc:
        print(str(exc),file=sys.stderr)
        return 2
    rendered=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)
    if args.output:
        Path(args.output).parent.mkdir(parents=True,exist_ok=True)
        Path(args.output).write_text(rendered+"\n",encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
