"""Safe access to the text surrounding the macOS insertion point."""

from __future__ import annotations

import time
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
    text_origin: int = 0
    bounded: bool = False
    pid: Optional[int] = None


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
    return sum(2 if ord(char) > 0xFFFF else 1 for char in value)


def utf16_offset_to_index(value: str, offset: int) -> Optional[int]:
    """Translate an AX/NSString UTF-16 offset to a Python string index."""
    if offset < 0:
        return None

    units = 0
    for index, char in enumerate(value):
        if units == offset:
            return index
        units += 2 if ord(char) > 0xFFFF else 1
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

    _CONTEXT_WINDOW_UNITS = 512
    _UNSUPPORTED_CACHE_SECONDS = 300.0
    _CAPABILITY_CACHE_LIMIT = 128

    def __init__(self):
        self._system_element = AX.AXUIElementCreateSystemWide()
        self._direct_write_unsupported = {}
        self._direct_write_supported = {}

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

    def _copy_parameterized(
        self, element: Any, attribute: str, parameter: Any
    ) -> tuple[int, Any]:
        return AX.AXUIElementCopyParameterizedAttributeValue(
            element, attribute, parameter, None
        )

    def _focused_element(self) -> tuple[int, Any]:
        system = getattr(self, "_system_element", None)
        if system is None:
            system = AX.AXUIElementCreateSystemWide()
            self._system_element = system
        return self._copy_attribute(system, AX.kAXFocusedUIElementAttribute)

    def _element_pid(self, element: Any) -> Optional[int]:
        try:
            error, pid = AX.AXUIElementGetPid(element, None)
        except (TypeError, ValueError):
            return None
        return int(pid) if error == AX.kAXErrorSuccess else None

    def _write_cache_key(self, snapshot: TextSnapshot):
        try:
            element_key = hash(snapshot.element)
        except TypeError:
            element_key = id(snapshot.element)
        return snapshot.pid, element_key

    def _cache_capability(self, cache: dict, key, value):
        cache.pop(key, None)
        cache[key] = value
        while len(cache) > self._CAPABILITY_CACHE_LIMIT:
            cache.pop(next(iter(cache)))

    def _copy_text_range(
        self, element: Any, location: int, length: int
    ) -> tuple[int, Any]:
        range_value = AX.AXValueCreate(
            AX.kAXValueCFRangeType, (location, length)
        )
        if range_value is None:
            return AX.kAXErrorIllegalArgument, None
        try:
            return self._copy_parameterized(
                element,
                AX.kAXStringForRangeParameterizedAttribute,
                range_value,
            )
        except (TypeError, ValueError):
            return AX.kAXErrorParameterizedAttributeUnsupported, None

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

    def snapshot(self, source: Optional[str] = None) -> ContextInspection:
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

        range_error, range_value = self._copy_attribute(
            element, AX.kAXSelectedTextRangeAttribute
        )
        if range_error != AX.kAXErrorSuccess:
            return ContextInspection(
                ContextStatus.UNAVAILABLE,
                reason="focused element does not expose a selection",
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

        text_origin = 0
        bounded = False
        text = None
        if source:
            window_units = max(
                self._CONTEXT_WINDOW_UNITS, utf16_length(source) + 32
            )
            text_origin = max(0, location - window_units)
            text_error, window_text = self._copy_text_range(
                element, text_origin, location - text_origin
            )
            if text_error == AX.kAXErrorSuccess and isinstance(window_text, str):
                relative_caret = location - text_origin
                caret_index = utf16_offset_to_index(
                    window_text, relative_caret
                )
                source_start = (
                    caret_index - len(source)
                    if caret_index is not None
                    else -1
                )
                prefix = (
                    window_text[:source_start]
                    if source_start >= 0
                    else ""
                )
                needs_earlier_text = (
                    text_origin > 0
                    and source_start >= 0
                    and not prefix.rstrip(" \t")
                )
                if not needs_earlier_text:
                    text = window_text
                    bounded = True

        if text is None:
            value_error, full_text = self._copy_attribute(
                element, AX.kAXValueAttribute
            )
            if value_error != AX.kAXErrorSuccess or not isinstance(full_text, str):
                return ContextInspection(
                    ContextStatus.UNAVAILABLE,
                    reason="focused element does not expose text",
                )
            text = full_text
            text_origin = 0

        return ContextInspection(
            ContextStatus.AVAILABLE,
            snapshot=TextSnapshot(
                element=element,
                text=text,
                selection_location=location,
                selection_length=length,
                role=str(role) if role is not None else None,
                subrole=str(subrole) if subrole is not None else None,
                text_origin=text_origin,
                bounded=bounded,
                pid=self._element_pid(element),
            ),
        )

    def inspect_before_caret(self, source: str) -> ContextInspection:
        inspection = self.snapshot(source)
        if inspection.status is not ContextStatus.AVAILABLE:
            return inspection

        snapshot = inspection.snapshot
        assert snapshot is not None
        caret_index = utf16_offset_to_index(
            snapshot.text,
            snapshot.selection_location - snapshot.text_origin,
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

    def _copy_snapshot_text(
        self,
        snapshot: TextSnapshot,
        end_location: Optional[int] = None,
    ) -> tuple[int, Any]:
        if snapshot.bounded:
            end = (
                snapshot.selection_location
                if end_location is None
                else end_location
            )
            return self._copy_text_range(
                snapshot.element,
                snapshot.text_origin,
                end - snapshot.text_origin,
            )
        return self._copy_attribute(snapshot.element, AX.kAXValueAttribute)

    def replace(
        self, inspection: ContextInspection, source: str, replacement: str
    ) -> ReplacementResult:
        if (
            inspection.status is not ContextStatus.AVAILABLE
            or inspection.snapshot is None
        ):
            return ReplacementResult(inspection.status, inspection.reason)

        snapshot = inspection.snapshot
        cache_key = self._write_cache_key(snapshot)

        focus_error, current_element = self._focused_element()
        if (
            focus_error != AX.kAXErrorSuccess
            or current_element != snapshot.element
        ):
            return ReplacementResult(
                ContextStatus.MISMATCH,
                "focused element changed while preparing the correction",
            )

        range_error, range_value = self._copy_attribute(
            current_element, AX.kAXSelectedTextRangeAttribute
        )
        current_selection = (
            self._range_from_ax(range_value)
            if range_error == AX.kAXErrorSuccess
            else None
        )
        if current_selection != (
            snapshot.selection_location,
            snapshot.selection_length,
        ):
            return ReplacementResult(
                ContextStatus.MISMATCH,
                "selection changed while preparing the correction",
            )

        text_error, current_text = self._copy_snapshot_text(snapshot)
        if (
            text_error != AX.kAXErrorSuccess
            or current_text != snapshot.text
        ):
            return ReplacementResult(
                ContextStatus.MISMATCH,
                "focused text changed while preparing the correction",
            )

        unsupported = getattr(self, "_direct_write_unsupported", {})
        now = time.monotonic()
        for expired_key, expiry in tuple(unsupported.items()):
            if expiry <= now:
                unsupported.pop(expired_key, None)
        unsupported_until = unsupported.get(cache_key, 0.0)
        if unsupported_until > now:
            return ReplacementResult(
                ContextStatus.UNAVAILABLE,
                "direct accessibility write is cached as unsupported",
            )
        if unsupported_until:
            unsupported.pop(cache_key, None)

        current = snapshot
        supported = getattr(self, "_direct_write_supported", {})
        if cache_key not in supported:
            for attribute in (
                AX.kAXSelectedTextRangeAttribute,
                AX.kAXSelectedTextAttribute,
            ):
                error, settable = self._is_settable(
                    current.element, attribute
                )
                if error != AX.kAXErrorSuccess or not settable:
                    return ReplacementResult(
                        ContextStatus.UNAVAILABLE,
                        f"{attribute} is not settable",
                    )
            if not hasattr(self, "_direct_write_supported"):
                self._direct_write_supported = {}
            self._cache_capability(
                self._direct_write_supported, cache_key, None
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

        verify_error = AX.kAXErrorNoValue
        verify_text = None
        expected_text = None
        current_caret_index = utf16_offset_to_index(
            current.text,
            current.selection_location - current.text_origin,
        )
        current_start_index = utf16_offset_to_index(
            current.text, source_start - current.text_origin
        )
        if current_caret_index is not None and current_start_index is not None:
            expected_text = (
                current.text[:current_start_index]
                + replacement
                + (
                    ""
                    if current.bounded
                    else current.text[current_caret_index:]
                )
            )

        expected_selection = (
            source_start + utf16_length(replacement),
            0,
        )
        for delay in (0.0, 0.003, 0.007):
            if delay:
                time.sleep(delay)
            verify_error, verify_text = self._copy_snapshot_text(
                current,
                end_location=expected_selection[0],
            )
            if verify_error != AX.kAXErrorSuccess:
                break
            if isinstance(verify_text, str) and verify_text == expected_text:
                break

        if verify_error != AX.kAXErrorSuccess or not isinstance(verify_text, str):
            unchanged_error, unchanged_text = self._copy_snapshot_text(current)
            if (
                unchanged_error == AX.kAXErrorSuccess
                and unchanged_text == current.text
            ):
                restore_error = self._set_attribute(
                    current.element,
                    AX.kAXSelectedTextRangeAttribute,
                    original_range,
                )
                if restore_error == AX.kAXErrorSuccess:
                    if not hasattr(self, "_direct_write_unsupported"):
                        self._direct_write_unsupported = {}
                    self._cache_capability(
                        self._direct_write_unsupported,
                        cache_key,
                        time.monotonic()
                        + self._UNSUPPORTED_CACHE_SECONDS,
                    )
                    return ReplacementResult(
                        ContextStatus.UNAVAILABLE,
                        "accessibility write changed no text; use fallback",
                    )
            return ReplacementResult(
                ContextStatus.FAILED,
                "could not verify accessibility replacement text",
            )

        if current_caret_index is None or current_start_index is None:
            return ReplacementResult(
                ContextStatus.FAILED,
                "could not validate accessibility replacement offsets",
            )
        if verify_text != expected_text:
            unchanged_error, unchanged_text = self._copy_snapshot_text(current)
            if (
                unchanged_error == AX.kAXErrorSuccess
                and unchanged_text == current.text
            ):
                restore_error = self._set_attribute(
                    current.element,
                    AX.kAXSelectedTextRangeAttribute,
                    original_range,
                )
                if restore_error == AX.kAXErrorSuccess:
                    if not hasattr(self, "_direct_write_unsupported"):
                        self._direct_write_unsupported = {}
                    self._cache_capability(
                        self._direct_write_unsupported,
                        cache_key,
                        time.monotonic()
                        + self._UNSUPPORTED_CACHE_SECONDS,
                    )
                    return ReplacementResult(
                        ContextStatus.UNAVAILABLE,
                        "accessibility write changed no text; use fallback",
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
