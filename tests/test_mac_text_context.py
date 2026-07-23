import unittest

import ApplicationServices as AX

from mac_text_context import (
    ContextStatus,
    MacTextContext,
    is_sentence_start,
    utf16_length,
    utf16_offset_to_index,
)


class FakeTextContext(MacTextContext):
    def __init__(self, text, selection=None, subrole=None):
        self.element = object()
        self.text = text
        self.selection = selection or (utf16_length(text), 0)
        self.subrole = subrole
        self.settable = True
        self.fail_selected_text = False
        self.ignore_selected_text = False

    def _focused_element(self):
        return AX.kAXErrorSuccess, self.element

    def _copy_attribute(self, element, attribute):
        if attribute == AX.kAXRoleAttribute:
            return AX.kAXErrorSuccess, AX.kAXTextAreaRole
        if attribute == AX.kAXSubroleAttribute:
            if self.subrole is None:
                return AX.kAXErrorNoValue, None
            return AX.kAXErrorSuccess, self.subrole
        if attribute == AX.kAXValueAttribute:
            return AX.kAXErrorSuccess, self.text
        if attribute == AX.kAXSelectedTextRangeAttribute:
            value = AX.AXValueCreate(AX.kAXValueCFRangeType, self.selection)
            return AX.kAXErrorSuccess, value
        return AX.kAXErrorAttributeUnsupported, None

    def _is_settable(self, element, attribute):
        return AX.kAXErrorSuccess, self.settable

    def _set_attribute(self, element, attribute, value):
        if attribute == AX.kAXSelectedTextRangeAttribute:
            success, selection = AX.AXValueGetValue(
                value, AX.kAXValueCFRangeType, None
            )
            if not success:
                return AX.kAXErrorIllegalArgument
            self.selection = tuple(selection)
            return AX.kAXErrorSuccess

        if attribute == AX.kAXSelectedTextAttribute:
            if self.fail_selected_text:
                return AX.kAXErrorCannotComplete
            if self.ignore_selected_text:
                return AX.kAXErrorSuccess
            location, length = self.selection
            start = utf16_offset_to_index(self.text, location)
            end = utf16_offset_to_index(self.text, location + length)
            if start is None or end is None:
                return AX.kAXErrorIllegalArgument
            self.text = self.text[:start] + value + self.text[end:]
            self.selection = (location + utf16_length(value), 0)
            return AX.kAXErrorSuccess

        return AX.kAXErrorAttributeUnsupported


class TextContextTests(unittest.TestCase):
    def test_utf16_offsets_handle_emoji(self):
        self.assertEqual(utf16_length("😀dont"), 6)
        self.assertEqual(utf16_offset_to_index("😀dont", 2), 1)
        self.assertIsNone(utf16_offset_to_index("😀dont", 1))

    def test_sentence_start_uses_hard_boundaries(self):
        for prefix in ("", "   ", "Hello.  ", "Hello\n", "Hello\r\n"):
            with self.subTest(prefix=prefix):
                self.assertTrue(is_sentence_start(prefix))
        self.assertFalse(is_sentence_start("Hello "))
        self.assertFalse(is_sentence_start("a visually wrapped line "))

    def test_inspection_validates_exact_source_at_caret(self):
        context = FakeTextContext("Hello dont")
        inspection = context.inspect_before_caret("dont")
        self.assertEqual(inspection.status, ContextStatus.AVAILABLE)
        self.assertFalse(inspection.sentence_start)

        mismatch = context.inspect_before_caret("wont")
        self.assertEqual(mismatch.status, ContextStatus.MISMATCH)

    def test_secure_field_and_selection_are_unsafe(self):
        secure = FakeTextContext(
            "secret", subrole=AX.kAXSecureTextFieldSubrole
        )
        self.assertEqual(secure.snapshot().status, ContextStatus.UNSAFE)

        selected = FakeTextContext("hello", selection=(0, 5))
        self.assertEqual(selected.snapshot().status, ContextStatus.UNSAFE)

    def test_replacement_uses_utf16_range_before_caret(self):
        context = FakeTextContext("😀dont")
        inspection = context.inspect_before_caret("dont")
        result = context.replace(inspection, "dont", "don't ")

        self.assertTrue(result.applied)
        self.assertEqual(context.text, "😀don't ")
        self.assertEqual(
            context.selection,
            (utf16_length("😀don't "), 0),
        )

    def test_failed_write_restores_original_caret(self):
        context = FakeTextContext("dont")
        inspection = context.inspect_before_caret("dont")
        original_selection = context.selection
        context.fail_selected_text = True

        result = context.replace(inspection, "dont", "don't ")

        self.assertEqual(result.status, ContextStatus.FAILED)
        self.assertEqual(context.text, "dont")
        self.assertEqual(context.selection, original_selection)

    def test_no_op_accessibility_write_is_not_treated_as_success(self):
        context = FakeTextContext("dont")
        inspection = context.inspect_before_caret("dont")
        original_selection = context.selection
        context.ignore_selected_text = True

        result = context.replace(inspection, "dont", "don't ")

        self.assertEqual(result.status, ContextStatus.FAILED)
        self.assertEqual(context.text, "dont")
        self.assertEqual(context.selection, original_selection)


if __name__ == "__main__":
    unittest.main()
