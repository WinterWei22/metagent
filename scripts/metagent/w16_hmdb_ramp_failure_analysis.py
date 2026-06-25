"""
W16 failure case diagnosis: hmdb_ramp pathway prediction (43.43% primary semantic accuracy).

Steps:
1. Load scorecard CSV, filter to hmdb_ramp
2. Classify FAIL cases (primary_semantic_match==False) into A/B/C/D
3. For 5-8 B-class FAILs: read JSON trace and extract narrative + tool calls
4. For 5 A-class FAILs: check if GT pathway name appears in narrative
5. Check C-class (empty primary_name) for termination_reason/error
6. Compute average tool call counts and unique tool types for PASS vs FAIL
"""

import json
import os
import re
import pandas as pd
from pathlib import Path

BASE = Path("/home/weiwentao/workspace/llm_agent_metabolomics/metagent_v2")
CSV_PATH = BASE / "reports/reports_v3/2026-06-25_v4bench_secondpass_final.md/2026-06-19_full344_pathway_scorecard_rows.csv"
TRACE_DIR = BASE / "data/metagent/v4_bench_eval_sub6hmdb_secondpass_20260624/path_x_full"


# ─────────────────────────────────────────────────────────────────────────────
# 1. Load and filter to hmdb_ramp
# ─────────────────────────────────────────────────────────────────────────────
df = pd.read_csv(CSV_PATH)
hmdb = df[df["stratum"] == "hmdb_ramp"].copy()
print(f"=== 1. hmdb_ramp rows: {len(hmdb)} ===")
print(f"primary_semantic_match: {hmdb['primary_semantic_match'].value_counts().to_dict()}")
pass_rate = hmdb["primary_semantic_match"].mean()
print(f"primary_semantic_match accuracy: {pass_rate:.2%}  ({hmdb['primary_semantic_match'].sum()}/{len(hmdb)})")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Classify FAIL cases
# ─────────────────────────────────────────────────────────────────────────────
fail = hmdb[hmdb["primary_semantic_match"] == False].copy()
pass_ = hmdb[hmdb["primary_semantic_match"] == True].copy()
print(f"\n=== 2. FAIL cases: {len(fail)}, PASS cases: {len(pass_)} ===")

def classify_fail(row):
    pred = str(row["primary_name"]).strip() if pd.notna(row["primary_name"]) else ""
    gt = str(row["gt_name"]).strip() if pd.notna(row["gt_name"]) else ""

    # C: empty prediction
    if not pred or pred.lower() in ("nan", "", "none"):
        return "C"

    pred_tok = set(re.findall(r"[a-z0-9]+", pred.lower()))
    gt_tok = set(re.findall(r"[a-z0-9]+", gt.lower()))

    # Remove very common short tokens
    stop = {"and", "of", "the", "in", "to", "by", "via", "with", "or", "a", "an", "de", "i"}
    pred_tok -= stop
    gt_tok -= stop

    if not pred_tok or not gt_tok:
        return "D"

    overlap = len(pred_tok & gt_tok)
    union = len(pred_tok | gt_tok)
    jaccard = overlap / union if union else 0

    # A: approximate (significant keyword overlap, or one contains the other)
    pred_l = pred.lower()
    gt_l = gt.lower()
    if jaccard >= 0.3 or pred_l in gt_l or gt_l in pred_l:
        return "A"

    # B: complete mismatch
    return "B"

fail["fail_class"] = fail.apply(classify_fail, axis=1)
class_counts = fail["fail_class"].value_counts()
print("\nFAIL classification:")
for cls, cnt in class_counts.items():
    print(f"  {cls}: {cnt}")


# ─────────────────────────────────────────────────────────────────────────────
# 3. B-class FAILs: read JSON trace
# ─────────────────────────────────────────────────────────────────────────────
b_cases = fail[fail["fail_class"] == "B"].head(8)
print(f"\n=== 3. B-class FAIL cases (complete mismatch), showing up to 8 ===")

for _, row in b_cases.iterrows():
    task_id = row["task_id"]
    gt = row["gt_name"]
    pred = row["primary_name"]
    json_path = TRACE_DIR / f"{task_id}.json"

    print(f"\n--- Task: {task_id}")
    print(f"    GT:   {gt}")
    print(f"    Pred: {pred}")

    if not json_path.exists():
        print(f"    [JSON NOT FOUND: {json_path}]")
        continue

    with open(json_path) as f:
        trace = json.load(f)

    frr = trace.get("final_react_result", {})
    narrative = frr.get("final_narrative_text", "") or ""
    pathway_pred = frr.get("pathway_prediction", {})
    tool_calls = frr.get("tool_calls_trace", [])
    termination_reason = frr.get("termination_reason", "")
    error = frr.get("error", "")

    print(f"    termination_reason: {termination_reason}")
    print(f"    error: {error}")
    print(f"    pathway_prediction primary: {pathway_pred.get('primary', {}).get('pathway_name', 'N/A')}")

    tool_names = [tc.get("name", "?") for tc in tool_calls]
    tool_summary = {}
    for t in tool_names:
        tool_summary[t] = tool_summary.get(t, 0) + 1
    print(f"    tool_calls ({len(tool_calls)} total): {tool_summary}")

    narrative_preview = narrative[:2000]
    # Check if GT appears in narrative
    gt_in_narrative = gt.lower() in narrative.lower()
    print(f"    GT name in narrative: {gt_in_narrative}")
    print(f"    Narrative (first 1000 chars):\n      {narrative_preview[:1000]!r}")


# ─────────────────────────────────────────────────────────────────────────────
# 4. A-class FAILs: check if GT appears in narrative
# ─────────────────────────────────────────────────────────────────────────────
a_cases = fail[fail["fail_class"] == "A"].head(5)
print(f"\n=== 4. A-class FAIL cases (approximate mismatch), checking GT in narrative ===")

for _, row in a_cases.iterrows():
    task_id = row["task_id"]
    gt = row["gt_name"]
    pred = row["primary_name"]
    json_path = TRACE_DIR / f"{task_id}.json"

    print(f"\n--- Task: {task_id}")
    print(f"    GT:   {gt}")
    print(f"    Pred: {pred}")

    if not json_path.exists():
        print(f"    [JSON NOT FOUND]")
        continue

    with open(json_path) as f:
        trace = json.load(f)

    frr = trace.get("final_react_result", {})
    narrative = frr.get("final_narrative_text", "") or ""

    gt_in_narrative = gt.lower() in narrative.lower()
    print(f"    GT name in narrative: {gt_in_narrative}")
    if gt_in_narrative:
        idx = narrative.lower().find(gt.lower())
        context = narrative[max(0, idx-100):idx+len(gt)+100]
        print(f"    Context: ...{context!r}...")
    else:
        # Try partial match with main words
        gt_words = [w for w in gt.split() if len(w) > 3]
        for w in gt_words:
            if w.lower() in narrative.lower():
                print(f"    Partial match found for word '{w}'")
                break
        else:
            print(f"    No keyword match found for GT: '{gt}'")


# ─────────────────────────────────────────────────────────────────────────────
# 5. C-class: empty primary_name
# ─────────────────────────────────────────────────────────────────────────────
c_cases = fail[fail["fail_class"] == "C"]
print(f"\n=== 5. C-class cases (empty primary_name): {len(c_cases)} ===")

for _, row in c_cases.iterrows():
    task_id = row["task_id"]
    gt = row["gt_name"]
    json_path = TRACE_DIR / f"{task_id}.json"

    print(f"\n--- Task: {task_id} | GT: {gt}")
    print(f"    primary_id: {row['primary_id']}  primary_name: {row['primary_name']}")

    if not json_path.exists():
        print(f"    [JSON NOT FOUND]")
        continue

    with open(json_path) as f:
        trace = json.load(f)

    frr = trace.get("final_react_result", {})
    print(f"    termination_reason: {frr.get('termination_reason', 'N/A')}")
    print(f"    error: {frr.get('error', 'N/A')}")
    print(f"    task_outcome: {frr.get('task_outcome', 'N/A')}")
    pred = frr.get("pathway_prediction") or {}
    print(f"    pathway_prediction.primary: {pred.get('primary', {})}")
    print(f"    pathway_prediction.abstain: {pred.get('abstain', 'N/A')}")
    print(f"    abstain_reason: {str(pred.get('abstain_reason', ''))[:200]}")


# ─────────────────────────────────────────────────────────────────────────────
# 6. Tool call stats: PASS vs FAIL
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 6. Tool call statistics: PASS vs FAIL ===")

def load_tool_stats(task_id):
    json_path = TRACE_DIR / f"{task_id}.json"
    if not json_path.exists():
        return None
    with open(json_path) as f:
        trace = json.load(f)
    frr = trace.get("final_react_result", {})
    tool_calls = frr.get("tool_calls_trace", []) or []
    n_tools = len(tool_calls)
    tool_names = [tc.get("name", "?") for tc in tool_calls]
    n_distinct = len(set(tool_names))
    return {"n_calls": n_tools, "n_distinct": n_distinct, "tools": tool_names}

pass_stats = []
fail_stats = []

for _, row in hmdb.iterrows():
    stats = load_tool_stats(row["task_id"])
    if stats is None:
        continue
    if row["primary_semantic_match"]:
        pass_stats.append(stats)
    else:
        fail_stats.append(stats)

def summarize_stats(stats_list, label):
    if not stats_list:
        print(f"  {label}: no data")
        return
    n_calls = [s["n_calls"] for s in stats_list]
    n_distinct = [s["n_distinct"] for s in stats_list]
    all_tools = []
    for s in stats_list:
        all_tools.extend(s["tools"])
    tool_freq = {}
    for t in all_tools:
        tool_freq[t] = tool_freq.get(t, 0) + 1
    print(f"\n  {label} (n={len(stats_list)} tasks):")
    print(f"    avg tool calls: {sum(n_calls)/len(n_calls):.2f}  (min={min(n_calls)}, max={max(n_calls)})")
    print(f"    avg distinct tools: {sum(n_distinct)/len(n_distinct):.2f}")
    # Top tools by frequency
    top_tools = sorted(tool_freq.items(), key=lambda x: -x[1])[:10]
    print(f"    Top tool types (calls across all tasks):")
    for t, cnt in top_tools:
        print(f"      {t}: {cnt}")

summarize_stats(pass_stats, "PASS")
summarize_stats(fail_stats, "FAIL")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Summary table of FAIL cases
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 7. Full FAIL case listing (gt_name vs primary_name) ===")
fail_display = fail[["task_id", "gt_name", "primary_name", "fail_class", "abstain"]].copy()
pd.set_option("display.max_colwidth", 50)
pd.set_option("display.width", 200)
print(fail_display.to_string(index=False))

# Class B detail: all B cases
print("\n=== All B-class cases ===")
b_all = fail[fail["fail_class"] == "B"][["task_id", "gt_name", "primary_name"]]
for _, row in b_all.iterrows():
    print(f"  {row['task_id']}")
    print(f"    GT:   {row['gt_name']}")
    print(f"    Pred: {row['primary_name']}")
