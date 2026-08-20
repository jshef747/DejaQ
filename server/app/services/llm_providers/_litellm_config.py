"""Side-effect import: neutralises LiteLLM's own defaults before any code
in this package makes a call. Imported once by `llm_providers/__init__.py`
so every consumer picks the neutralised config up for free.
"""

import litellm

litellm.telemetry = False  # no sender found in 1.97.0; belt and braces
litellm.suppress_debug_info = True  # keep LiteLLM's banners out of DejaQ's logs

# LiteLLM's acompletion retries 3x by default even though litellm.num_retries
# reads as None. Unset, a rate-limited request triples provider spend and
# latency and corrupts DejaQ's own latency_ms measurement. Every call site
# must spread this into its kwargs.
DEFAULT_CALL_KWARGS = {"num_retries": 0}
