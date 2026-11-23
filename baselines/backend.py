"""Local Hugging Face or OpenAI-compatible model calls."""

import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else _hash(stream)


def _hash(stream):
    result = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        result.update(chunk)
    return result.hexdigest()


def checkpoint_identity(path):
    from evaluation.scheduler import digest

    files = sorted(p for p in Path(path).iterdir()
                   if p.is_file() and p.suffix in {".safetensors", ".json", ".txt", ".jinja", ".model", ".bin"})
    hashes = {p.name: file_hash(p) for p in files}
    if not any(p.suffix in {".safetensors", ".bin"} for p in files):
        raise ValueError("no local checkpoint weights")
    tokenizer = {name: value for name, value in hashes.items()
                 if name.startswith(("tokenizer", "special_tokens", "added_tokens", "chat_template",
                                     "vocab", "merges", "spiece", "sentencepiece"))}
    if not tokenizer:
        raise ValueError("no local tokenizer files")
    return digest(hashes), "sha256:" + digest(tokenizer)


def send_json(url, payload, timeout, key=None):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    request = Request(url, json.dumps(payload).encode(), headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read(4096).decode(errors='replace')}") from exc


class ChatBackend:
    def __init__(self, config):
        self.config = config
        self.backend = config["backend"]
        self.tokenizer = None
        if self.backend in {"transformers", "mlx_vlm"}:
            from transformers import AutoTokenizer
            checkpoint = Path(config["checkpoint"])
            if checkpoint_identity(checkpoint) != (config["model_revision"], config["tokenizer_id"]):
                raise ValueError("checkpoint or tokenizer fingerprint does not match config")
            self.tokenizer = AutoTokenizer.from_pretrained(checkpoint, local_files_only=True, trust_remote_code=False)
            if self.backend == "mlx_vlm":
                from mlx_vlm import load
                self.model, self.processor = load(str(checkpoint), trust_remote_code=False)
            else:
                import torch
                from transformers import AutoConfig, AutoModelForCausalLM, AutoModelForSeq2SeqLM

                config_type = AutoConfig.from_pretrained(checkpoint, local_files_only=True, trust_remote_code=False)
                self.seq2seq = config_type.is_encoder_decoder
                loader = AutoModelForSeq2SeqLM if self.seq2seq else AutoModelForCausalLM
                self.device = config.get("device", "cpu")
                self.torch = torch
                self.model = loader.from_pretrained(checkpoint, local_files_only=True, trust_remote_code=False)
                self.model.to(self.device).eval()
        elif self.backend != "openai_compatible":
            raise ValueError(f"unsupported backend: {self.backend}")

    def render(self, prompt):
        if self.tokenizer.chat_template:
            return self.tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}], tokenize=False, add_generation_prompt=True
            ), False
        return prompt, True

    def count(self, prompt):
        if self.tokenizer is None:
            raise ValueError("exact preflight requires a local tokenizer/backend")
        text, add_special_tokens = self.render(prompt)
        return len(self.tokenizer.encode(text, add_special_tokens=add_special_tokens))

    def generate(self, prompt, params, seed):
        if self.backend == "openai_compatible":
            config = self.config
            key = os.getenv(config["api_key_env"]) if config.get("api_key_env") else None
            if config.get("api_key_env") and not key:
                raise RuntimeError(f"missing environment variable {config['api_key_env']}")
            raw = send_json(config["base_url"].rstrip("/") + "/chat/completions", {
                **params, "model": config["model"], "messages": [{"role": "user", "content": prompt}]
            }, config.get("timeout", 120), key)
            usage = raw.get("usage") or {}
            return raw["choices"][0]["message"]["content"], usage.get("prompt_tokens"), usage.get("completion_tokens"), raw

        text, special = self.render(prompt)
        if self.backend == "mlx_vlm":
            import mlx.core as mx
            from mlx_vlm import generate

            mx.random.seed(seed)
            result = generate(self.model, self.processor, text, image=None, verbose=False,
                              max_tokens=params["max_tokens"], temperature=params["temperature"])
            return result.text, result.prompt_tokens, result.generation_tokens, None

        torch = self.torch
        torch.manual_seed(seed)
        inputs = self.tokenizer(text, add_special_tokens=special, return_tensors="pt").to(self.device)
        count = inputs.input_ids.shape[-1]
        kwargs = {"max_new_tokens": params["max_tokens"], "do_sample": params["temperature"] > 0}
        if kwargs["do_sample"]:
            kwargs["temperature"] = params["temperature"]
        with torch.inference_mode():
            output = self.model.generate(**inputs, **kwargs)[0]
        if not self.seq2seq:
            output = output[count:]
        else:
            output = output[1:]
        return self.tokenizer.decode(output, skip_special_tokens=True), count, len(output), None
