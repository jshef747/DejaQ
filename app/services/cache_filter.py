import logging
import re

logger = logging.getLogger("dejaq.services.cache_filter")

# Patterns that indicate non-cacheable conversational filler
FILLER_PATTERNS = re.compile(
    r"^(ok|okay|yes|no|sure|thanks|thank you|got it|cool|nice|great|"
    r"hmm|hm|ah|oh|wow|lol|haha|yep|nope|alright|right|fine|good|bye|hi|hello|hey)\.?!?$",
    re.IGNORECASE,
)

MIN_WORD_COUNT = 3


def should_cache(enriched_query: str, normalized_query: str) -> tuple[bool, str]:
    """Decide whether a response should be cached.

    Returns (should_cache, reason) tuple for logging/UI.
    """
    # Rule 1: Too short after normalization
    word_count = len(normalized_query.split())
    if word_count < MIN_WORD_COUNT:
        reason = f"query too short ({word_count} words)"
        logger.info("Skip cache: %s — query: '%s'", reason, normalized_query)
        return False, reason

    # Rule 2: Conversational filler
    stripped = enriched_query.strip().rstrip("?.,!")
    if FILLER_PATTERNS.match(stripped):
        reason = "conversational filler"
        logger.info("Skip cache: %s — query: '%s'", reason, enriched_query)
        return False, reason

    # Rule 3: Too vague even after enrichment (very short enriched query)
    enriched_words = len(enriched_query.split())
    if enriched_words < MIN_WORD_COUNT:
        reason = f"enriched query too vague ({enriched_words} words)"
        logger.info("Skip cache: %s — enriched: '%s'", reason, enriched_query)
        return False, reason

    logger.debug("Cache filter: PASS for '%s'", normalized_query[:60])
    return True, "passed"
