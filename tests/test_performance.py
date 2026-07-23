import logging
import time
import unittest

from autocorrect import (
    CorrectionCoordinator,
    FallbackResult,
    V26MacEngine,
)
from mac_text_context import (
    ContextInspection,
    ContextStatus,
    ReplacementResult,
)


class FakeSuppressor:
    def __init__(self):
        self.suppressed = 0

    def suppress_current(self):
        self.suppressed += 1


class FakeFallback:
    def __init__(self):
        self.calls = 0

    def apply(self, engine, source, replacement, trigger):
        self.calls += 1
        return FallbackResult(applied=True)


class FakeContext:
    def __init__(self, replacement_status=ContextStatus.AVAILABLE):
        self.inspect_calls = 0
        self.replace_calls = 0
        self.replacement_status = replacement_status

    def inspect_before_caret(self, source):
        self.inspect_calls += 1
        return ContextInspection(
            ContextStatus.AVAILABLE,
            snapshot=object(),
            sentence_start=False,
        )

    def replace(self, inspection, source, replacement):
        self.replace_calls += 1
        return ReplacementResult(self.replacement_status)


class PerformanceTests(unittest.TestCase):
    # These broad ceilings catch accidental sleeps or blocking I/O without
    # depending on a specific Mac model.
    def test_ordinary_character_path_has_no_large_regression(self):
        engine = V26MacEngine({})
        started = time.perf_counter()
        for _ in range(50_000):
            engine.handle_char("a")
            engine.handle_backspace()
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 1.0)

    def test_trigger_proposal_path_has_no_large_regression(self):
        engine = V26MacEngine({"dont": "don't"})
        for char in "dont":
            engine.handle_char(char)

        started = time.perf_counter()
        for _ in range(50_000):
            candidate = engine.prepare_trigger(" ")
            engine.finalize_candidate(candidate, False)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 1.0)

    def test_ax_success_pipeline_has_no_large_regression(self):
        context = FakeContext()
        fallback = FakeFallback()
        coordinator = CorrectionCoordinator(
            V26MacEngine({"dont": "don't"}),
            context,
            fallback,
            FakeSuppressor(),
            logging.getLogger("perf.null"),
        )
        coordinator.log.disabled = True

        started = time.perf_counter()
        for _ in range(2_000):
            coordinator.engine.reset()
            for char in "dont":
                coordinator.engine.handle_char(char)
            coordinator.apply_trigger(" ")
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 1.0)
        self.assertEqual(context.replace_calls, 2_000)
        self.assertEqual(fallback.calls, 0)

    def test_ax_no_op_fallback_pipeline_has_no_large_regression(self):
        context = FakeContext(ContextStatus.UNAVAILABLE)
        fallback = FakeFallback()
        suppressor = FakeSuppressor()
        coordinator = CorrectionCoordinator(
            V26MacEngine({"dont": "don't"}),
            context,
            fallback,
            suppressor,
            logging.getLogger("perf.fallback.null"),
        )
        coordinator.log.disabled = True

        started = time.perf_counter()
        for _ in range(2_000):
            coordinator.engine.reset()
            for char in "dont":
                coordinator.engine.handle_char(char)
            coordinator.apply_trigger(" ")
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 1.0)
        self.assertEqual(fallback.calls, 2_000)
        self.assertEqual(suppressor.suppressed, 2_000)


if __name__ == "__main__":
    unittest.main()
