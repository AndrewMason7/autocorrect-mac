import atexit
import fcntl
import json
import logging
import os
import queue
import signal
import sys
from dataclasses import dataclass
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path

from Foundation import NSMaxRange, NSString
from Quartz import (
    CGEventGetIntegerValueField,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventSourceUnixProcessID,
    kCGKeyboardEventKeycode,
)
from pynput import keyboard
from AppKit import (
    NSActivityLatencyCritical,
    NSActivityUserInitiated,
    NSApplication,
    NSApplicationActivationPolicyProhibited,
    NSEvent,
    NSEventModifierFlagCommand,
    NSEventModifierFlagControl,
    NSEventModifierFlagOption,
    NSProcessInfo,
    NSWorkspace,
    NSWorkspaceWillPowerOffNotification,
)

try:
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyProhibited)
except Exception:
    pass

from mac_text_context import (
    ContextStatus,
    MacTextContext,
    is_sentence_start,
)

# Global reference to keep lock file handle alive
_lock_file_handle = None

def enforce_singleton():
    global _lock_file_handle
    # Primary lock path in user home, fallback to /tmp if home is read-only (e.g. Recovery Mode)
    lock_paths = [
        os.path.expanduser("~/.autocorrect.lock"),
        "/tmp/.autocorrect.lock"
    ]
    
    last_err = None
    for lock_path in lock_paths:
        try:
            # Ensure directories exist
            os.makedirs(os.path.dirname(lock_path), exist_ok=True)
            _lock_file_handle = open(lock_path, "w")
            # Try to acquire exclusive, non-blocking lock
            fcntl.flock(_lock_file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return  # Lock acquired successfully
        except BlockingIOError:
            # Another process holds the lock - exit immediately
            sys.stderr.write("Another instance of autocorrect is already running. Exiting.\n")
            sys.exit(0)
        except Exception as e:
            # Write/permission error - try the fallback path
            last_err = e
            continue
            
    # Fallback in case both directories are write-restricted
    sys.stderr.write(f"Warning: Could not create lock file due to: {last_err}. Proceeding with caution.\n")

def _cleanup_lock():
    global _lock_file_handle
    if _lock_file_handle:
        try:
            fcntl.flock(_lock_file_handle, fcntl.LOCK_UN)
            _lock_file_handle.close()
            _lock_file_handle = None
        except Exception:
            pass

atexit.register(_cleanup_lock)

# Keep file I/O off the latency-sensitive event-tap thread.
log_sinks = [
    RotatingFileHandler(
        os.path.expanduser("~/autocorrect.log"),
        maxBytes=5 * 1024 * 1024,  # 5 MB limit per log file
        backupCount=3,             # Keep up to 3 old rotated log files
        encoding="utf-8"
    )
]
if sys.stdout and sys.stdout.isatty():
    log_sinks.append(logging.StreamHandler(sys.stdout))

log_queue = queue.SimpleQueue()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[QueueHandler(log_queue)],
)
log_listener = QueueListener(
    log_queue, *log_sinks, respect_handler_level=True
)
log_listener.start()
atexit.register(log_listener.stop)
logger = logging.getLogger("V26MacEngine")

# Applications where autocorrect is disabled (by localized name or bundle identifier)
IGNORED_APPS = frozenset({
    "terminal",
    "com.apple.terminal",
    "ghostty",
    "com.mitchellh.ghostty",
})

def is_app_ignored() -> bool:
    try:
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app:
            name = app.localizedName()
            bundle_id = app.bundleIdentifier()
            if (name and name.lower() in IGNORED_APPS) or (bundle_id and bundle_id.lower() in IGNORED_APPS):
                return True
    except Exception as e:
        logger.error("Error checking frontmost app: %s", e)
    return False

_BASE_DIR = Path(__file__).resolve().parent
GRAMMAR_PATH = _BASE_DIR / "grammar.json"
SHORTCUTS_PATH = _BASE_DIR / "shortcuts.json"


def _load_rules_file(path: Path) -> dict[str, str]:
    """Load a JSON mapping of trigger words to replacement strings."""
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}, got {type(data).__name__}")
    return {str(k): str(v) for k, v in data.items()}


def load_corrections(
    grammar_path: Path = GRAMMAR_PATH,
    shortcuts_path: Path = SHORTCUTS_PATH,
) -> dict[str, str]:
    """Load and merge grammar and shortcut rules, with shortcuts taking precedence."""
    return {**_load_rules_file(grammar_path), **_load_rules_file(shortcuts_path)}


CORRECTIONS = load_corrections()

_TRIGGERS = frozenset((" ", ".", "!", "?", ",", "\n", "\t"))


@dataclass(frozen=True)
class CorrectionCandidate:
    source: str
    word: str
    replacement_template: str | None
    consumed_words: int
    local_sentence_start: bool


@dataclass(frozen=True)
class CorrectionProposal:
    source: str
    replacement: str
    word: str
    consumed_words: int
    sentence_start: bool


@dataclass(frozen=True)
class FallbackResult:
    applied: bool
    uncertain: bool = False


class V26MacEngine:
    def __init__(self, corrections: dict[str, str]):
        self.corrections = corrections
        self.buffer = ""
        self.prev_words = []
        self.history = ""
        self.synthesized_queue = []
        self.context_confident = False

    def _capitalize_first_alpha(self, s: str) -> str:
        for i, c in enumerate(s):
            if c.isalnum():
                if c.isalpha():
                    if c.islower():
                        return s[:i] + c.upper() + s[i+1:]
                    return s
                else:
                    return s
        return s

    def handle_char(self, char: str):
        if char in _TRIGGERS:
            raise ValueError("trigger characters must use prepare/commit_trigger")
        self.history += char
        if len(self.history) > 1000:
            self.history = self.history[-500:]
        self.buffer += char

    def handle_backspace(self):
        if self.history:
            self.history = self.history[:-1]

        if self.buffer:
            self.buffer = self.buffer[:-1]
        else:
            self.prev_words.clear()

    def reset(self):
        self.buffer = ""
        self.prev_words.clear()
        self.history = ""
        self.synthesized_queue.clear()
        self.context_confident = False

    def _preserve_case(self, original: str, replacement: str) -> str:
        if not original or not replacement:
            return replacement
        if original.isupper():
            return replacement.upper()
        if original[0].isupper():
            return replacement[0].upper() + replacement[1:]
        return replacement

    def _get_key_char(self, key) -> str:
        if hasattr(key, 'char') and key.char:
            if key.char == "\r":
                return "\n"
            return key.char
        if key == keyboard.Key.space:
            return ' '
        if key == keyboard.Key.enter:
            return '\n'
        if key == keyboard.Key.tab:
            return '\t'
        if key == keyboard.Key.backspace:
            return 'backspace'
        return None

    def _local_sentence_start(self, source: str) -> bool:
        if not self.context_confident or not self.history.endswith(source):
            return False
        return is_sentence_start(
            self.history[:-len(source)] if source else self.history
        )

    def prepare_trigger(self, trigger: str) -> CorrectionCandidate | None:
        word = self.buffer.lower()
        if not word:
            return None

        replacement = None
        source = self.buffer
        consumed_words = 1

        if trigger == ' ':
            if len(self.prev_words) >= 2:
                phrase3 = f"{self.prev_words[-2][0]} {self.prev_words[-1][0]} {word}"
                if phrase3 in self.corrections:
                    replacement = self.corrections[phrase3]
                    source = (
                        f"{self.prev_words[-2][1]} "
                        f"{self.prev_words[-1][1]} {self.buffer}"
                    )
                    consumed_words = 3

            if replacement is None and self.prev_words:
                phrase2 = f"{self.prev_words[-1][0]} {word}"
                if phrase2 in self.corrections:
                    replacement = self.corrections[phrase2]
                    source = f"{self.prev_words[-1][1]} {self.buffer}"
                    consumed_words = 2

        if replacement is None and word in self.corrections:
            replacement = self.corrections[word]

        return CorrectionCandidate(
            source=source,
            word=word,
            replacement_template=replacement,
            consumed_words=consumed_words,
            local_sentence_start=self._local_sentence_start(source),
        )

    def finalize_candidate(
        self, candidate: CorrectionCandidate, sentence_start: bool
    ) -> CorrectionProposal | None:
        replacement = candidate.replacement_template

        if replacement is None and sentence_start:
            if not any(c in candidate.word for c in ('@', ':', '/', '\\')):
                capitalized = self._capitalize_first_alpha(self.buffer)
                if capitalized != self.buffer:
                    replacement = capitalized

        if replacement is None:
            return None

        replacement = self._preserve_case(self.buffer, replacement)
        if sentence_start and replacement and replacement[0].islower():
            replacement = replacement[0].upper() + replacement[1:]

        if replacement == candidate.source:
            return None

        return CorrectionProposal(
            source=candidate.source,
            replacement=replacement,
            word=candidate.word,
            consumed_words=candidate.consumed_words,
            sentence_start=sentence_start,
        )

    def candidate_may_correct(self, candidate: CorrectionCandidate) -> bool:
        if candidate.replacement_template is not None:
            return True
        if any(c in candidate.word for c in ("@", ":", "/", "\\")):
            return False
        if self._capitalize_first_alpha(self.buffer) == self.buffer:
            return False
        return not self.context_confident or candidate.local_sentence_start

    def local_source_matches(self, candidate: CorrectionCandidate) -> bool:
        return self.history.endswith(candidate.source)

    def commit_trigger(
        self,
        trigger: str,
        candidate: CorrectionCandidate | None,
        proposal: CorrectionProposal | None,
        applied: bool,
        stale: bool = False,
    ):
        raw_buffer = self.buffer
        if stale:
            self.reset()
            if trigger in (".", "!", "?", "\n"):
                self.history = trigger
                self.context_confident = True
            return

        if applied and proposal is not None:
            if self.history.endswith(proposal.source):
                self.history = (
                    self.history[:-len(proposal.source)]
                    + proposal.replacement
                    + trigger
                )
            else:
                self.history = proposal.replacement + trigger
        else:
            self.history += trigger

        if trigger == " " and raw_buffer:
            if applied and proposal is not None:
                if proposal.consumed_words > 1:
                    self.prev_words.clear()
                else:
                    self.prev_words.append((proposal.word, proposal.replacement))
            else:
                self.prev_words.append((raw_buffer.lower(), raw_buffer))
            if len(self.prev_words) > 2:
                self.prev_words = self.prev_words[-2:]
        else:
            self.prev_words.clear()

        self.buffer = ""
        if raw_buffer or trigger in (".", "!", "?", "\n"):
            self.context_confident = True
        if len(self.history) > 1000:
            self.history = self.history[-500:]

    def expect_synthetic(self, events: list[str]):
        self.synthesized_queue.extend(events)

    def consume_synthetic(self, event: str | None) -> bool:
        if (
            event is not None
            and self.synthesized_queue
            and self.synthesized_queue[0] == event
        ):
            self.synthesized_queue.pop(0)
            return True
        return False


def composed_character_count(value: str) -> int:
    string = NSString.stringWithString_(value)
    location = 0
    count = 0
    while location < string.length():
        character_range = string.rangeOfComposedCharacterSequenceAtIndex_(location)
        location = NSMaxRange(character_range)
        count += 1
    return count


class KeystrokeFallback:
    def __init__(self, controller):
        self.controller = controller

    def apply(
        self,
        engine: V26MacEngine,
        source: str,
        replacement: str,
        trigger: str,
    ) -> FallbackResult:
        delete_count = composed_character_count(source)
        expected = ["backspace"] * delete_count + list(replacement + trigger)
        engine.expect_synthetic(expected)
        mutated = False
        try:
            for _ in range(delete_count):
                mutated = True
                self.controller.tap(keyboard.Key.backspace)
            self.controller.type(replacement + trigger)
            return FallbackResult(applied=True)
        except Exception:
            engine.synthesized_queue.clear()
            logger.exception("Keystroke fallback failed while applying correction")
            return FallbackResult(applied=False, uncertain=mutated)


class TriggerSuppressor:
    def __init__(self, on_external_injected=None):
        self.suppress_current_key_down = False
        self.suppressed_key_codes = set()
        self.on_external_injected = on_external_injected

    def begin_key_down(self):
        self.suppress_current_key_down = False

    def suppress_current(self):
        self.suppress_current_key_down = True

    def intercept(self, event_type, event):
        source_pid = CGEventGetIntegerValueField(
            event, kCGEventSourceUnixProcessID
        )
        if source_pid:
            if (
                source_pid != os.getpid()
                and self.on_external_injected is not None
            ):
                self.on_external_injected()
            return event

        key_code = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        if event_type == kCGEventKeyDown and key_code in self.suppressed_key_codes:
            return None
        if event_type == kCGEventKeyDown and self.suppress_current_key_down:
            self.suppress_current_key_down = False
            self.suppressed_key_codes.add(key_code)
            return None
        if event_type == kCGEventKeyUp and key_code in self.suppressed_key_codes:
            self.suppressed_key_codes.remove(key_code)
            return None
        return event


class CorrectionCoordinator:
    """Coordinates a trigger without starting a global keyboard listener."""

    def __init__(
        self,
        engine: V26MacEngine,
        text_context: MacTextContext,
        fallback: KeystrokeFallback,
        suppressor: TriggerSuppressor,
        log=logger,
    ):
        self.engine = engine
        self.text_context = text_context
        self.fallback = fallback
        self.suppressor = suppressor
        self.log = log

    def apply_trigger(self, trigger: str):
        candidate = self.engine.prepare_trigger(trigger)
        if candidate is None:
            self.engine.commit_trigger(trigger, None, None, applied=False)
            return

        if not self.engine.candidate_may_correct(candidate):
            self.engine.commit_trigger(
                trigger, candidate, None, applied=False
            )
            return

        inspection = self.text_context.inspect_before_caret(candidate.source)
        if inspection.status is ContextStatus.AVAILABLE:
            sentence_start = bool(inspection.sentence_start)
        elif inspection.status is ContextStatus.UNAVAILABLE:
            sentence_start = candidate.local_sentence_start
        else:
            self.log.info(
                "[SKIPPED] Context is unsafe or stale: %s", inspection.reason
            )
            self.engine.commit_trigger(
                trigger, candidate, None, applied=False, stale=True
            )
            return

        proposal = self.engine.finalize_candidate(candidate, sentence_start)
        if proposal is None:
            self.engine.commit_trigger(
                trigger, candidate, None, applied=False
            )
            return

        applied = False
        stale = False
        suppress_original_trigger = False
        if inspection.status is ContextStatus.AVAILABLE:
            result = self.text_context.replace(
                inspection,
                proposal.source,
                proposal.replacement,
            )
            applied = result.applied
            if (
                not applied
                and result.status is ContextStatus.UNAVAILABLE
                and self.engine.local_source_matches(candidate)
            ):
                fallback_result = self.fallback.apply(
                    self.engine,
                    proposal.source,
                    proposal.replacement,
                    trigger,
                )
                applied = fallback_result.applied
                stale = fallback_result.uncertain
                suppress_original_trigger = applied
            elif not applied:
                stale = True
                self.log.info(
                    "[SKIPPED] Accessibility replacement: %s", result.reason
                )
        elif self.engine.local_source_matches(candidate):
            fallback_result = self.fallback.apply(
                self.engine,
                proposal.source,
                proposal.replacement,
                trigger,
            )
            applied = fallback_result.applied
            stale = fallback_result.uncertain
            suppress_original_trigger = applied
        else:
            stale = True

        if suppress_original_trigger:
            self.suppressor.suppress_current()
        if applied:
            self.log.info(
                "[SUCCESS] '%s' -> '%s' (Trigger: '%s')",
                proposal.source,
                proposal.replacement,
                trigger.replace("\n", "\\n").replace("\t", "\\t"),
            )
        self.engine.commit_trigger(
            trigger, candidate, proposal, applied=applied, stale=stale
        )


def run_mac_engine():
    # Enforce process singleton status to prevent concurrent instance loops
    enforce_singleton()

    corrections = load_corrections()
    engine = V26MacEngine(corrections)
    text_context = MacTextContext()
    fallback = KeystrokeFallback(keyboard.Controller())
    suppressor = TriggerSuppressor(on_external_injected=engine.reset)
    coordinator = CorrectionCoordinator(
        engine, text_context, fallback, suppressor
    )
    logger.info("Loaded %d autocorrect rules for macOS.", len(corrections))

    # Allow macOS to terminate the process cleanly without showing a force quit modal on shutdown/logout
    try:
        NSProcessInfo.processInfo().enableSuddenTermination()
    except Exception as e:
        logger.debug("Failed to enable sudden termination: %s", e)

    # Assert latency-critical status to completely bypass macOS App Nap and process throttling
    try:
        activity = NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
            NSActivityUserInitiated | NSActivityLatencyCritical,
            "Real-time keystroke autocorrection"
        )
        engine.activity_assertion = activity
        logger.info("Successfully asserted latency-critical status (App Nap disabled).")
    except Exception as e:
        logger.error("Failed to assert latency-critical status: %s", e)

    def on_press(key, injected=False):
        try:
            char_rep = engine._get_key_char(key)
            if injected:
                engine.consume_synthetic(char_rep)
                return

            if is_app_ignored():
                engine.reset()
                return

            suppressor.begin_key_down()
            if engine.synthesized_queue:
                engine.synthesized_queue.clear()

            # Check current modifier flags dynamically from the OS to ignore shortcuts
            try:
                flags = NSEvent.modifierFlags()
                if flags & (NSEventModifierFlagCommand | NSEventModifierFlagOption | NSEventModifierFlagControl):
                    engine.reset()
                    return
            except Exception as e:
                logger.error("Error checking modifier flags: %s", e)

            if char_rep is not None:
                if len(char_rep) == 1 and ord(char_rep) < 32:
                    if char_rep not in ("\n", "\t"):
                        engine.reset()
                        return
                if char_rep == "backspace":
                    engine.handle_backspace()
                elif char_rep in _TRIGGERS:
                    coordinator.apply_trigger(char_rep)
                else:
                    engine.handle_char(char_rep)
            elif key == keyboard.Key.backspace:
                engine.handle_backspace()
            elif key in (keyboard.Key.esc, keyboard.Key.up, keyboard.Key.down, keyboard.Key.left, keyboard.Key.right,
                         keyboard.Key.page_up, keyboard.Key.page_down, keyboard.Key.home, keyboard.Key.end, keyboard.Key.delete):
                engine.reset()
        except Exception as err:
            logger.error("Error handling key press: %s", err)

    def on_release(key, injected=False):
        pass

    listener = keyboard.Listener(
        on_press=on_press,
        on_release=on_release,
        darwin_intercept=suppressor.intercept,
    )
    listener.daemon = True

    def handle_shutdown(signum, frame):
        logger.info("Received signal %s, shutting down autocorrect engine gracefully...", signum)
        try:
            listener.stop()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    try:
        def on_power_off(notification):
            logger.info("System powering off / logging out, stopping autocorrect...")
            try:
                listener.stop()
            except Exception:
                pass
            os._exit(0)

        NSWorkspace.sharedWorkspace().notificationCenter().addObserverForName_object_queue_usingBlock_(
            NSWorkspaceWillPowerOffNotification,
            None,
            None,
            on_power_off,
        )
    except Exception as e:
        logger.debug("Could not register power off notification: %s", e)

    listener.start()
    try:
        while listener.is_alive():
            listener.join(timeout=1.0)
    except (KeyboardInterrupt, SystemExit):
        try:
            listener.stop()
        except Exception:
            pass
        logger.info("Autocorrect engine stopped.")
        sys.exit(0)

if __name__ == "__main__":
    run_mac_engine()
