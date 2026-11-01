"""Export separate risk-coverage curves; optional matplotlib rendering."""
from __future__ import annotations
import argparse
import csv
import json
import shutil
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
    parser.add_argument("--output",required=True,help="CSV output (no dependencies), or publication PDF/SVG/PNG facets requiring matplotlib")
    parser.add_argument("--mode",choices=["candidate","answered"],default="candidate")
    parser.add_argument("--where",action="append",default=[])
    parser.add_argument("--label",choices=["software-selfcheck","pilot","frozen-test"],default="software-selfcheck")
    parser.add_argument("--style",choices=["journal","minimal","warm","monochrome"],default="journal")
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
    if output.suffix.lower() not in {".csv", ".pdf", ".svg", ".png"}:
        print("output must be CSV, PDF, SVG or PNG", file=sys.stderr)
        return 2
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
            from .publication import render_report_figures
        except ImportError:
            from evaluation.publication import render_report_figures
        figure_dir = output.parent / (output.stem + "_figures")
        figure_dir.mkdir(parents=True, exist_ok=True)
        try:
            report["figure_status"] = render_report_figures(figure_dir, curves, args.label, rows if args.mode == "candidate" else None, style=args.style)
        except ImportError:
            print("CSV saved; figure rendering requires matplotlib", file=sys.stderr)
            return 2
        report["figure_index"] = str(figure_dir / "figure_index.json")
        index = json.loads((figure_dir / "figure_index.json").read_text(encoding="utf-8"))
        if index:
            shutil.copyfile(figure_dir / index[0][output.suffix.lower()[1:]], output)
            report["figure"] = str(output)
            report["figure_note"] = "Requested path previews the first facet page; figure_index lists every condition."
    print(json.dumps(report,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
