"""MetAgent demo UI (Track UI1).

Gradio wrapper over the already-shipped naive orchestrator (Track O1).
Strictly a viewer: reads cached runs from disk, optionally triggers live
pipeline + LLM runs through the existing entry points. Never calls the
LLM directly.
"""
