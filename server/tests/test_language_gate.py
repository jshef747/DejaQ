"""Unit tests for the script-based language gate (services/language_gate.py).

See test_language_gate_pipeline.py for the end-to-end regression - this file
only covers the classifier itself.
"""
from app.services.language_gate import dominant_script, scripts_conflict


def test_english_is_latin():
    assert dominant_script("What is the capital of France?") == "latin"


def test_hebrew_is_hebrew():
    assert dominant_script("מה בירת צרפת?") == "hebrew"


def test_japanese_is_cjk():
    assert dominant_script("東京の首都は何ですか") == "cjk"


def test_short_numeric_answer_has_no_dominant_script():
    # No letters at all - too little signal to classify either way.
    assert dominant_script("100°C") is None


def test_single_stray_word_is_not_enough_to_flip_the_majority():
    # One Hebrew word inside an otherwise-English sentence should not read
    # as confidently Hebrew - the majority threshold protects this.
    assert dominant_script("The word for hello is שלום in Hebrew.") == "latin"


def test_conflict_between_hebrew_question_and_english_answer():
    assert scripts_conflict("מה בירת צרפת?", "The capital of France is Paris.") is True


def test_no_conflict_when_both_sides_are_english():
    assert scripts_conflict(
        "What is the capital of France?", "The capital of France is Paris."
    ) is False


def test_no_conflict_when_both_sides_are_hebrew():
    assert scripts_conflict("מה בירת צרפת?", "בירת צרפת היא פריז.") is False


def test_no_conflict_when_the_answer_has_no_classifiable_script():
    # A numeric-only cached answer carries no language signal - the gate must
    # not block on "not enough evidence," only on a genuine disagreement.
    assert scripts_conflict("מה זה שורש הריבועי של 81?", "9") is False


def test_no_conflict_when_the_query_has_no_classifiable_script():
    assert scripts_conflict("2+2?", "The answer is four.") is False
