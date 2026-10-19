"""Export separate risk-coverage curves; optional matplotlib rendering."""
from __future__ import annotations
import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
try:
    from .metrics import GROUP_FIELDS, load_jsonl, risk_curve
except ImportError:
    from metrics import GROUP_FIELDS, load_jsonl, risk_curve


def coordinates(rows, mode="candidate"):
    return risk_curve(rows, mode)["points"]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("--output",required=True,help="CSV output (no dependencies), or PNG/SVG requiring matplotlib")
    parser.add_argument("--mode",choices=["candidate","answered"],default="candidate")
    parser.add_argument("--where",action="append",default=[])
    args=parser.parse_args()
    try:
        rows=load_jsonl(args.input)
        for expr in args.where:
            key,value=expr.split("=",1)
            rows=[r for r in rows if str(r.get(key))==value]
        if not rows:
            raise ValueError("no rows after filtering")
    except (ValueError,OSError) as exc:
        print(str(exc),file=sys.stderr)
        return 2
    groups=defaultdict(list)
    for row in rows:
        groups[tuple(row[k] for k in GROUP_FIELDS)].append(row)
    curves=[(dict(zip(GROUP_FIELDS,key)),risk_curve(group,args.mode)) for key,group in groups.items()]
    output=Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    csv_path=output if output.suffix.lower()==".csv" else output.with_suffix(".csv")
    columns=list(GROUP_FIELDS)+["curve_mode","coverage","risk","accepted","score_threshold"]
    with csv_path.open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=columns)
        writer.writeheader()
        for context,curve in curves:
            for point in curve["points"]:
                writer.writerow(dict(context,curve_mode=args.mode,**point))
    report={"csv":str(csv_path),"mode":args.mode,"unavailable":[dict(context,reason=curve["reason"]) for context,curve in curves if not curve["available"]]}
    if output.suffix.lower()!=".csv":
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print("CSV saved, but requested figure requires matplotlib; use --output curves.csv or install matplotlib",file=sys.stderr)
            return 2
        fig,ax=plt.subplots(figsize=(8,5),constrained_layout=True)
        for context,curve in curves:
            points=curve["points"][1:]
            if points:
                x=[0.0]+[p["coverage"] for p in points]
                y=[points[0]["risk"]]+[p["risk"] for p in points]
                label=f"{context['method']}/{context['metadata_state']}/{context['replica_condition']}"
                ax.step(x,y,where="pre",label=label)
        ax.set(xlim=(0,1),ylim=(0,1),xlabel="Coverage of successful predictions",ylabel="Risk")
        ax.grid(alpha=.25)
        if any(curve["available"] for _,curve in curves):
            ax.legend(fontsize=7)
        fig.savefig(output,dpi=180)
        plt.close(fig)
        report["figure"]=str(output)
    print(json.dumps(report,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
