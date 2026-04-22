"""MS-BART single-inference runner. Designed to be launched by MSBartGenerator
as `conda run -n ms-bart python -m tools.molecule_gen._runner`.

Reads a JSON payload from stdin, writes one JSON line to stdout as the last
line. All heavy imports (torch, transformers, selfies) stay inside this
module so the parent process does not pull them.

Payload (stdin):
  {
    "fingerprint": [42, 249, ...],      # list of bit indices
    "formula": "C8H10N4O2" | null,
    "n_candidates": 20,
    "checkpoint_path": "/path/to/ckpt",
    "temperature": 0.4
  }

Result (last stdout line):
  {
    "candidates": [
      {"smiles": "...", "seq_log_prob": -3.12, "rank": 0},
      ...
    ],
    "n_generated_raw": 20
  }
"""
from __future__ import annotations

import json
import sys


def _fingerprint_to_tokens(bits: list[int]) -> str:
    # MS-BART training data uses 4-digit zero-padded fp tokens. The test.tsv
    # fixture shows tokens in sorted ascending order with no duplicates.
    uniq = sorted({int(b) for b in bits})
    return "".join(f"<fp{b:04d}>" for b in uniq)


def main() -> int:
    payload = json.loads(sys.stdin.read())
    fingerprint: list[int] = payload["fingerprint"]
    n: int = int(payload["n_candidates"])
    checkpoint_path: str = payload["checkpoint_path"]
    temperature: float = float(payload.get("temperature", 0.4))

    if n <= 0:
        print(json.dumps({"candidates": [], "n_generated_raw": 0}))
        return 0

    import torch
    from selfies import decoder as selfies_decoder
    from transformers import (
        BartForConditionalGeneration,
        BartTokenizer,
        GenerationConfig,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = BartTokenizer.from_pretrained(checkpoint_path, local_files_only=True)
    model = BartForConditionalGeneration.from_pretrained(
        checkpoint_path, local_files_only=True
    ).to(device)
    model.eval()

    fp_string = _fingerprint_to_tokens(fingerprint)
    inputs = tokenizer(
        [fp_string],
        return_tensors="pt",
        padding=True,
        padding_side="right",
        add_special_tokens=False,
    )
    inputs = {k: v.to(device) for k, v in inputs.items()}

    gen_config = GenerationConfig(
        max_new_tokens=256,
        do_sample=True,
        temperature=temperature,
        num_return_sequences=n,
        num_beams=n,
        pad_token_id=tokenizer.pad_token_id,
        eos_token_id=tokenizer.eos_token_id,
    )

    with torch.inference_mode():
        out = model.generate(
            **inputs,
            generation_config=gen_config,
            return_dict_in_generate=True,
            output_scores=True,
        )

    sequences = out.sequences.detach().cpu()
    # sequences_scores is the beam-search log-prob of each returned sequence.
    # For pure sampling it may be absent; fall back to the per-sequence rank.
    scores = getattr(out, "sequences_scores", None)
    if scores is not None:
        scores = scores.detach().cpu().tolist()
    else:
        scores = [float(-i) for i in range(len(sequences))]

    candidates = []
    for i, seq in enumerate(sequences):
        text = tokenizer.decode(seq, skip_special_tokens=True).replace(" ", "")
        try:
            smiles = selfies_decoder(text)
        except Exception:
            smiles = ""
        candidates.append(
            {
                "smiles": smiles or "",
                "seq_log_prob": float(scores[i]),
                "rank": int(i),
            }
        )

    print(json.dumps({"candidates": candidates, "n_generated_raw": len(candidates)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
