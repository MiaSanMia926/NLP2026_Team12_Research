"""Create versioned run manifests; this does not call models or choose thresholds."""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
import sys
from pathlib import Path
try:
    from .validation import load_records
except ImportError:
    from validation import load_records

CORE_METHODS=["B0","B1","B2","B3","B4","B5","B7"]
REPETITIONS=["no_replica","same_source_replica"]
METADATA=["complete","missing","incorrect"]
LENGTHS=["natural_length","fixed_token_budget"]


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode("utf-8")).hexdigest()


def make_manifest(questions,config,methods=None,include_oracle=False):
    required=("experiment_id","model","model_revision","prompt_template_hash","tokenizer_id","generation","seed","position_seed")
    if any(k not in config for k in required):
        raise ValueError("model configuration requires: "+", ".join(required))
    for k in ("experiment_id","model","model_revision","prompt_template_hash","tokenizer_id"):
        if not isinstance(config[k],str) or not config[k].strip():
            raise ValueError(f"nonempty {k} required")
    for k in ("seed","position_seed"):
        if type(config[k]) is not int or config[k]<0:
            raise ValueError(f"nonnegative integer {k} required")
    if not isinstance(config["generation"],dict):
        raise ValueError("generation must be a parameter object")
    budget=config.get("fixed_token_budget")
    if budget is not None and (type(budget) is not int or budget<1):
        raise ValueError("fixed_token_budget must be a positive integer")
    methods=list(methods if methods is not None else CORE_METHODS+(["B6"] if include_oracle else []))
    if len(set(methods))!=len(methods) or not methods or set(methods)-set(CORE_METHODS+["B6"]):
        raise ValueError("choose unique B0-B7 method IDs")
    if "B6" in methods and not include_oracle:
        raise ValueError("B6 requires explicit --include-oracle")
    registry_keys=[(q["dataset_id"],q["dataset_version"],q["base_question_id"]) for q in questions]
    if len(set(registry_keys))!=len(registry_keys):
        raise ValueError("duplicate base questions")
    rows=[]
    for q in sorted(questions,key=lambda q:(q["dataset_id"],q["dataset_version"],q["base_question_id"])):
        for replica,meta,method,length in itertools.product(REPETITIONS,METADATA,methods,LENGTHS):
            error=q.get("incorrect_metadata_error_type") if meta=="incorrect" else "none"
            blocked=[]
            if meta=="incorrect" and error not in {"split_same_source","merge_independent_sources"}:
                blocked.append("missing_metadata_error_recipe")
            if length=="fixed_token_budget" and budget is None:
                blocked.append("missing_token_budget")
            identity={k:q[k] for k in ("base_question_id","family_id","dataset_id","dataset_version","dataset_hash","split_hash","split","task_type")}
            identity.update(experiment_id=config["experiment_id"],model=config["model"],model_revision=config["model_revision"],
                            method=method,metadata_state=meta,metadata_error_type=error,length_policy=length,
                            seed=config["seed"],position_seed=config["position_seed"],config_hash=digest(dict(config,method=method)))
            pair_id=digest(identity)
            spec=dict(identity,replica_condition=replica)
            rows.append(dict(spec,run_id=digest(spec),pair_id=pair_id,
                             condition_id="__".join([replica,meta,error or "UNSET"]),
                             prompt_template_hash=config["prompt_template_hash"],tokenizer_id=config["tokenizer_id"],
                             generation=config["generation"],fixed_token_budget=budget if length=="fixed_token_budget" else None,
                             oracle=method=="B6",input_permission="oracle_lineage_only" if method=="B6" else "public_input_only",
                             neutral_fill_required=length=="fixed_token_budget",
                             status="blocked" if blocked else "planned",blocked_reasons=blocked))
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions",required=True)
    parser.add_argument("--config",required=True)
    parser.add_argument("--output",required=True)
    parser.add_argument("--methods",nargs="+")
    parser.add_argument("--include-oracle",action="store_true")
    args=parser.parse_args()
    try:
        questions=load_records(args.questions,"question")
        config=json.loads(Path(args.config).read_text(encoding="utf-8"))
        rows=make_manifest(questions,config,args.methods,args.include_oracle)
    except (OSError,ValueError,KeyError) as exc:
        print(str(exc),file=sys.stderr)
        return 2
    output=Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text("".join(json.dumps(r,ensure_ascii=False,allow_nan=False)+"\n" for r in rows),encoding="utf-8")
    print(json.dumps({"runs":len(rows),"blocked":sum(r["status"]=="blocked" for r in rows),"output":str(output)}))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
