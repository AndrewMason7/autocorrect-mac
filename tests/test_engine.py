import os
import unittest
from unittest.mock import patch

from Quartz import (
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventSourceUnixProcessID,
)
from pynput import keyboard

from autocorrect import (
    KeystrokeFallback,
    TriggerSuppressor,
    V26MacEngine,
    composed_character_count,
)


class FakeController:
    def __init__(self):
        self.tapped = []
        self.typed = []

    def tap(self, key):
        self.tapped.append(key)

    def type(self, value):
        self.typed.append(value)


def type_text(engine, value):
    for character in value:
        engine.handle_char(character)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = V26MacEngine(
            {
                "dont": "don't",
                "united states": "United States",
                "third eye chakra": "Third Eye Chakra",
            }
        )

    def test_single_word_proposal_preserves_context_and_case(self):
        type_text(self.engine, "Hello")
        self.engine.commit_trigger(
            " ", self.engine.prepare_trigger(" "), None, applied=False
        )
        type_text(self.engine, "dont")

        candidate = self.engine.prepare_trigger(" ")
        proposal = self.engine.finalize_candidate(candidate, False)

        self.assertEqual(candidate.source, "dont")
        self.assertEqual(proposal.replacement, "don't")
        self.assertFalse(proposal.sentence_start)

    def test_newline_makes_following_word_a_sentence_start(self):
        type_text(self.engine, "Hello")
        candidate = self.engine.prepare_trigger("\n")
        self.engine.commit_trigger("\n", candidate, None, applied=False)
        type_text(self.engine, "world")

        candidate = self.engine.prepare_trigger(" ")
        proposal = self.engine.finalize_candidate(
            candidate, candidate.local_sentence_start
        )

        self.assertTrue(candidate.local_sentence_start)
        self.assertEqual(proposal.replacement, "World")

    def test_multiword_candidate_tracks_exact_display_source(self):
        type_text(self.engine, "united")
        first = self.engine.prepare_trigger(" ")
        self.engine.commit_trigger(" ", first, None, applied=False)
        type_text(self.engine, "states")

        candidate = self.engine.prepare_trigger(" ")
        proposal = self.engine.finalize_candidate(candidate, False)

        self.assertEqual(candidate.source, "united states")
        self.assertEqual(candidate.consumed_words, 2)
        self.assertEqual(proposal.replacement, "United States")

    def test_stale_context_clears_phrase_and_buffer_state(self):
        type_text(self.engine, "dont")
        candidate = self.engine.prepare_trigger(" ")

        self.engine.commit_trigger(
            " ", candidate, None, applied=False, stale=True
        )

        self.assertEqual(self.engine.buffer, "")
        self.assertEqual(self.engine.prev_words, [])
        self.assertEqual(self.engine.history, [])
        self.assertFalse(self.engine.context_confident)

    def test_successful_commit_rewrites_only_validated_source(self):
        type_text(self.engine, "dont")
        candidate = self.engine.prepare_trigger(" ")
        proposal = self.engine.finalize_candidate(candidate, False)

        self.engine.commit_trigger(" ", candidate, proposal, applied=True)

        self.assertEqual("".join(self.engine.history), "don't ")
        self.assertEqual(self.engine.prev_words, [("dont", "don't")])

    def test_keystroke_fallback_never_deletes_the_trigger(self):
        type_text(self.engine, "dont")
        candidate = self.engine.prepare_trigger(" ")
        proposal = self.engine.finalize_candidate(candidate, False)
        controller = FakeController()

        result = KeystrokeFallback(controller).apply(
            self.engine,
            proposal.source,
            proposal.replacement,
            " ",
        )

        self.assertTrue(result.applied)
        self.assertEqual(
            controller.tapped,
            [keyboard.Key.backspace] * len("dont"),
        )
        self.assertEqual(controller.typed, ["don't "])

    def test_composed_character_count_matches_backspace_units(self):
        self.assertEqual(composed_character_count("a😀e\u0301"), 3)

    def test_unknown_local_context_does_not_guess_sentence_start(self):
        type_text(self.engine, "word")
        candidate = self.engine.prepare_trigger(" ")

        self.assertFalse(candidate.local_sentence_start)
        self.assertIsNone(
            self.engine.finalize_candidate(
                candidate, candidate.local_sentence_start
            )
        )

    @patch("autocorrect.CGEventGetIntegerValueField")
    def test_trigger_suppression_covers_key_down_and_key_up(self, _get_key_code):
        _get_key_code.side_effect = (
            lambda _event, field: (
                0 if field == kCGEventSourceUnixProcessID else 42
            )
        )
        suppressor = TriggerSuppressor()
        event = object()
        suppressor.begin_key_down()
        suppressor.suppress_current()

        self.assertIsNone(suppressor.intercept(kCGEventKeyDown, event))
        self.assertIsNone(suppressor.intercept(kCGEventKeyDown, event))
        self.assertIsNone(suppressor.intercept(kCGEventKeyUp, event))
        self.assertIs(suppressor.intercept(kCGEventKeyDown, event), event)

    @patch("autocorrect.CGEventGetIntegerValueField")
    def test_synthetic_trigger_is_not_suppressed(self, _get_value):
        _get_value.side_effect = (
            lambda _event, field: (
                os.getpid()
                if field == kCGEventSourceUnixProcessID
                else 42
            )
        )
        suppressor = TriggerSuppressor()
        suppressor.suppressed_key_codes.add(42)
        event = object()

        self.assertIs(suppressor.intercept(kCGEventKeyDown, event), event)


if __name__ == "__main__":
    unittest.main()
