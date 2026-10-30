"""
PACKAGE: app.generation - writing the answer.  (Phase 7)

    llm.py       client for the local Ollama model (GPU if available, else CPU)
    prompts.py   fixed SYSTEM rules (+ canary) and the fenced <source> user message
    answer.py    the pipeline: input guard -> secure search -> context guard -> LLM
                 -> output guard -> cited answer

Flow:
    user + question -> answer_question() -> Answer(text, citations, sources)
"""
