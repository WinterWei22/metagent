"""ConcordMet LLM-agent layer (W8 pivot).

Modules:
  system_prompts    — ReAct system + user prompt builders (loads
                      prompts/concord/concord_react_prompt.md).
  tool_dispatcher   — 9 OpenAI function-tool specs (5 PA wrappers +
                      4 reconciliation/lookup) + dispatch() entry point.
                      D1 skeleton; D2 wires the PA wrapper bodies.
  react_runner      — ConcordReactRunner: ReAct loop with grammar-v2
                      JSON output, two-layer retry, closed-loop verifier
                      via concord.agent.verifier_adapter. D1 skeleton;
                      D3 wires the loop body; D4 wires the verifier.

Architectural rule: this package does NOT modify `verifier/`,
`tools/agent_tools/`, or `evaluation/sub6/`. B1 paths import-only.
"""

__all__: list[str] = []
