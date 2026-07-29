"""Process-local transient state for manual formation pipeline continuations."""


PIPELINE_EXECUTION_STATE: dict[tuple[int, str], dict] = {}
