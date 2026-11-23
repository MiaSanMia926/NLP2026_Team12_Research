"""Freeze local weights, tokenizer files, runtime versions and prompt identity."""

import argparse
import json
from pathlib import Path

from evaluation.scheduler import digest
from .backend import checkpoint_identity, file_hash
from . import methods
from .runner import runtime_versions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("choose a fresh output file")
        config = json.loads(args.template.read_text())
        if args.checkpoint:
            config["checkpoint"] = str(args.checkpoint.resolve())
        if config["backend"] != "openai_compatible":
            config["model_revision"], config["tokenizer_id"] = checkpoint_identity(config["checkpoint"])
        if any(not isinstance(config[key], str) or not config[key].strip()
               for key in ("experiment_id", "model", "model_revision", "tokenizer_id")):
            raise ValueError("set real experiment ID, model, revision and tokenizer ID")
        config.update(prompt_template_hash=methods.PROMPT_HASH, runtime=runtime_versions(config),
                      method_code_hash=file_hash(methods.__file__))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(config, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
        print(json.dumps({"config_hash": digest(config), "model": config["model"],
                          "model_revision": config["model_revision"], "tokenizer_id": config["tokenizer_id"]}))
    except (OSError, KeyError, ValueError, ImportError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
