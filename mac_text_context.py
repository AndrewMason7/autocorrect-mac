"""Safe access to the text surrounding the macOS insertion point."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

import ApplicationServices as AX


class ContextStatus(Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    MISMATCH = "mismatch"
    UNSAFE = "unsafe"
    FAILED = "failed"


@dataclass(frozen=True)
class TextSnapshot:
    element: Any
    text: str
    selection_location: int
    selection_length: int
    role: Optional[str]
    subrole: Optional[str]


@dataclass(frozen=True)
class ContextInspection:
    status: ContextStatus
    snapshot: Optional[TextSnapshot] = None
    sentence_start: Optional[bool] = None
    reason: str = ""


@dataclass(frozen=True)
class ReplacementResult:
    status: ContextStatus
    reason: str = ""

    @property
    def applied(self) -> bool:
        return self.status is ContextStatus.AVAILABLE


def utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def utf16_offset_to_index(value: str, offset: int) -> Optional[int]:
    """Translate an AX/NSString UTF-16 offset to a Python string index."""
    if offset < 0:
        return None

    units = 0
    for index, char in enumerate(value):
        if units == offset:
            return index
        units += utf16_length(char)
        if units > offset:
            return None
    return len(value) if units == offset else None


def is_sentence_start(text_before_word: str) -> bool:
    """Return whether a word begins a sentence or a hard line."""
    for char in reversed(text_before_word):
        if char in (" ", "\t"):
            continue
        return char in (".", "!", "?", "\n", "\r")
    return True


class MacTextContext:
    """Thin, testable wrapper around the macOS Accessibility text API."""

    def _set_messaging_timeout(self, element: Any, seconds: float):
        try:
            AX.AXUIElementSetMessagingTimeout(element, seconds)
        except (TypeError, ValueError):
            pass

    def _copy_attribute(self, element: Any, attribute: str) -> tuple[int, Any]:
        return AX.AXUIElementCopyAttributeValue(element, attribute, None)

    def _set_attribute(self, element: Any, attribute: str, value: Any) -> int:
        return AX.AXUIElementSetAttributeValue(element, attribute, value)

    def _is_settable(self, element: Any, attribute: str) -> tuple[int, bool]:
        return AX.AXUIElementIsAttributeSettable(element, attribute, None)

    def _focused_element(self) -> tuple[int, Any]:
        system = AX.AXUIElementCreateSystemWide()
        return self._copy_attribute(system, AX.kAXFocusedUIElementAttribute)

    @staticmethod
    def _range_from_ax(value: Any) -> Optional[tuple[int, int]]:
        try:
            success, result = AX.AXValueGetValue(
                value, AX.kAXValueCFRangeType, None
            )
        except (TypeError, ValueError):
            return None
        if not success or not result or len(result) != 2:
            return None
        return int(result[0]), int(result[1])

    def snapshot(self) -> ContextInspection:
        error, element = self._focused_element()
        if error != AX.kAXErrorSuccess or element is None:
            return ContextInspection(
                ContextStatus.UNAVAILABLE, reason="no focused accessibility element"
            )
        self._set_messaging_timeout(element, 0.05)

        role_error, role = self._copy_attribute(element, AX.kAXRoleAttribute)
        if role_error != AX.kAXErrorSuccess:
            role = None

        subrole_error, subrole = self._copy_attribute(
            element, AX.kAXSubroleAttribute
        )
        if subrole_error != AX.kAXErrorSuccess:
            subrole = None
        if subrole == AX.kAXSecureTextFieldSubrole:
            return ContextInspection(
                ContextStatus.UNSAFE, reason="focused element is a secure text field"
            )

        value_error, text = self._copy_attribute(element, AX.kAXValueAttribute)
        range_error, range_value = self._copy_attribute(
            element, AX.kAXSelectedTextRangeAttribute
        )
        if (
            value_error != AX.kAXErrorSuccess
            or range_error != AX.kAXErrorSuccess
            or not isinstance(text, str)
        ):
            return ContextInspection(
                ContextStatus.UNAVAILABLE,
                reason="focused element does not expose text and selection",
            )

        selection = self._range_from_ax(range_value)
        if selection is None:
            return ContextInspection(
                ContextStatus.UNAVAILABLE, reason="invalid accessibility selection"
            )

        location, length = selection
        if length != 0:
            return ContextInspection(
                ContextStatus.UNSAFE, reason="focused element has selected text"
            )

        return ContextInspection(
            ContextStatus.AVAILABLE,
            snapshot=TextSnapshot(
                element=element,
                text=text,
                selection_location=location,
                selection_length=length,
                role=str(role) if role is not None else None,
                subrole=str(subrole) if subrole is not None else None,
            ),
        )

    def inspect_before_caret(self, source: str) -> ContextInspection:
        inspection = self.snapshot()
        if inspection.status is not ContextStatus.AVAILABLE:
            return inspection

        snapshot = inspection.snapshot
        assert snapshot is not None
        caret_index = utf16_offset_to_index(
            snapshot.text, snapshot.selection_location
        )
        if caret_index is None:
            return ContextInspection(
                ContextStatus.UNAVAILABLE,
                reason="caret is not on a UTF-16 character boundary",
            )

        source_start = caret_index - len(source)
        if source_start < 0 or snapshot.text[source_start:caret_index] != source:
            return ContextInspection(
                ContextStatus.MISMATCH,
                reason="text before caret no longer matches the correction source",
            )

        return ContextInspection(
            ContextStatus.AVAILABLE,
            snapshot=snapshot,
            sentence_start=is_sentence_start(snapshot.text[:source_start]),
        )

    def replace(
        self, inspection: ContextInspection, source: str, replacement: str
    ) -> ReplacementResult:
        if (
            inspection.status is not ContextStatus.AVAILABLE
            or inspection.snapshot is None
        ):
            return ReplacementResult(inspection.status, inspection.reason)

        snapshot = inspection.snapshot
        fresh = self.inspect_before_caret(source)
        if fresh.status is not ContextStatus.AVAILABLE or fresh.snapshot is None:
            return ReplacementResult(fresh.status, fresh.reason)

        current = fresh.snapshot
        if (
            current.element != snapshot.element
            or current.text != snapshot.text
            or current.selection_location != snapshot.selection_location
        ):
            return ReplacementResult(
                ContextStatus.MISMATCH,
                "focused text changed while preparing the correction",
            )

        for attribute in (
            AX.kAXSelectedTextRangeAttribute,
            AX.kAXSelectedTextAttribute,
        ):
            error, settable = self._is_settable(current.element, attribute)
            if error != AX.kAXErrorSuccess or not settable:
                return ReplacementResult(
                    ContextStatus.UNAVAILABLE,
                    f"{attribute} is not settable",
                )

        source_units = utf16_length(source)
        source_start = current.selection_location - source_units
        replacement_range = AX.AXValueCreate(
            AX.kAXValueCFRangeType, (source_start, source_units)
        )
        original_range = AX.AXValueCreate(
            AX.kAXValueCFRangeType,
            (current.selection_location, current.selection_length),
        )
        if replacement_range is None or original_range is None:
            return ReplacementResult(
                ContextStatus.FAILED, "could not create accessibility ranges"
            )

        select_error = self._set_attribute(
            current.element, AX.kAXSelectedTextRangeAttribute, replacement_range
        )
        if select_error != AX.kAXErrorSuccess:
            return ReplacementResult(
                ContextStatus.FAILED, "could not select correction source"
            )

        replace_error = self._set_attribute(
            current.element, AX.kAXSelectedTextAttribute, replacement
        )
        if replace_error != AX.kAXErrorSuccess:
            self._set_attribute(
                current.element, AX.kAXSelectedTextRangeAttribute, original_range
            )
            return ReplacementResult(
                ContextStatus.FAILED, "could not replace selected text"
            )

        verify_error, verify_text = self._copy_attribute(
            current.element, AX.kAXValueAttribute
        )
        if verify_error != AX.kAXErrorSuccess or not isinstance(verify_text, str):
            return ReplacementResult(
                ContextStatus.FAILED,
                "could not verify accessibility replacement text",
            )

        current_caret_index = utf16_offset_to_index(
            current.text, current.selection_location
        )
        current_start_index = utf16_offset_to_index(
            current.text, source_start
        )
        if current_caret_index is None or current_start_index is None:
            return ReplacementResult(
                ContextStatus.FAILED,
                "could not validate accessibility replacement offsets",
            )
        expected_text = (
            current.text[:current_start_index]
            + replacement
            + current.text[current_caret_index:]
        )
        if verify_text != expected_text:
            if verify_text == current.text:
                self._set_attribute(
                    current.element,
                    AX.kAXSelectedTextRangeAttribute,
                    original_range,
                )
            return ReplacementResult(
                ContextStatus.FAILED,
                "accessibility replacement did not produce the expected text",
            )

        selection_error, selection_value = self._copy_attribute(
            current.element, AX.kAXSelectedTextRangeAttribute
        )
        verified_selection = (
            self._range_from_ax(selection_value)
            if selection_error == AX.kAXErrorSuccess
            else None
        )
        expected_selection = (
            source_start + utf16_length(replacement),
            0,
        )
        if verified_selection != expected_selection:
            expected_range = AX.AXValueCreate(
                AX.kAXValueCFRangeType, expected_selection
            )
            if expected_range is None or self._set_attribute(
                current.element,
                AX.kAXSelectedTextRangeAttribute,
                expected_range,
            ) != AX.kAXErrorSuccess:
                return ReplacementResult(
                    ContextStatus.FAILED,
                    "replacement caret could not be restored",
                )
            selection_error, selection_value = self._copy_attribute(
                current.element, AX.kAXSelectedTextRangeAttribute
            )
            verified_selection = (
                self._range_from_ax(selection_value)
                if selection_error == AX.kAXErrorSuccess
                else None
            )
            if verified_selection != expected_selection:
                return ReplacementResult(
                    ContextStatus.FAILED,
                    "replacement caret could not be verified",
                )

        return ReplacementResult(ContextStatus.AVAILABLE)
