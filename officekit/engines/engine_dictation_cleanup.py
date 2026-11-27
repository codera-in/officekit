"""Conservative, deterministic cleanup for locally transcribed dictation."""

import re
from difflib import SequenceMatcher
from typing import Dict, List, Mapping, Optional, Sequence, Tuple


MAX_TRANSCRIPT_CHARACTERS = 262_144
MAX_DICTIONARY_ENTRIES = 256
MAX_DICTIONARY_TERM_CHARACTERS = 64
CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
DICTIONARY_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
SPOKEN_PUNCTUATION = (
    ("new paragraph", "\n\n"),
    ("new line", "\n"),
    ("question mark", "?"),
    ("exclamation point", "!"),
    ("exclamation mark", "!"),
    ("full stop", "."),
    ("period", "."),
    ("comma", ","),
    ("colon", ":"),
    ("semicolon", ";"),
)


def _validate_dictionary(dictionary: Optional[Mapping[str, str]]) -> Dict[str, str]:
    if dictionary is None:
        return {}
    if not isinstance(dictionary, Mapping) or len(dictionary) > MAX_DICTIONARY_ENTRIES:
        raise ValueError("Dictionary must contain at most 256 word replacements.")

    replacements: Dict[str, str] = {}
    normalized_sources = set()
    for source, replacement in dictionary.items():
        if not isinstance(source, str) or not isinstance(replacement, str):
            raise ValueError("Dictionary entries must be text pairs.")
        if not source.strip() or not replacement.strip():
            raise ValueError("Dictionary entries cannot be empty.")
        if len(source) > MAX_DICTIONARY_TERM_CHARACTERS or len(replacement) > MAX_DICTIONARY_TERM_CHARACTERS:
            raise ValueError("Dictionary entries cannot exceed 64 characters.")
        if DICTIONARY_CONTROL_CHARACTERS.search(source) or DICTIONARY_CONTROL_CHARACTERS.search(replacement):
            raise ValueError("Dictionary entries cannot contain control characters.")
        normalized_source = source.casefold()
        if normalized_source in normalized_sources:
            raise ValueError("Dictionary source terms must be unique without regard to case.")
        normalized_sources.add(normalized_source)
        replacements[source] = replacement
    return replacements


MAX_WORD_LIST_ENTRIES = 256
MAX_SNAP_TRANSCRIPT_CHARACTERS = 20_000
MAX_SNAP_SPAN_TOKENS = 4
MIN_SNAP_LETTERS = 4
SNAP_SIMILARITY = 0.84
SNAP_TOKEN = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?")
_PHONETIC_STEPS = (("ph", "f"), ("ck", "k"), ("c", "k"), ("q", "k"), ("z", "s"), ("y", "i"), ("w", "v"))


def _validate_words(words: Optional[Sequence[str]]) -> List[str]:
    if words is None:
        return []
    if isinstance(words, (str, bytes)) or len(words) > MAX_WORD_LIST_ENTRIES:
        raise ValueError("Word list must contain at most 256 words.")
    accepted: List[str] = []
    seen = set()
    for word in words:
        if not isinstance(word, str) or not word.strip():
            raise ValueError("Word list entries must be text.")
        if len(word) > MAX_DICTIONARY_TERM_CHARACTERS or DICTIONARY_CONTROL_CHARACTERS.search(word):
            raise ValueError("Word list entries are invalid.")
        if word.strip().casefold() not in seen:
            seen.add(word.strip().casefold())
            accepted.append(word.strip())
    return accepted


def _sound_key(text: str) -> str:
    """Rough spelling-to-sound key: letters and digits only, similar letters merged, doubles dropped."""
    key = re.sub(r"[^a-z0-9]", "", text.casefold())
    for old, new in _PHONETIC_STEPS:
        key = key.replace(old, new)
    return re.sub(r"(.)\1+", r"\1", key)


def snap_to_word_list(text: str, words: Sequence[str]) -> Tuple[str, List[Dict[str, str]]]:
    """Replace short runs of words that sound like a listed word with the listed spelling.

    Conservative: a run needs at least 4 sound letters, the same first sound and a close sound
    key. A single word that already equals a listed word is only re-cased. Returns the text and
    the changes made, so the history can show each one.
    """
    if not words or len(text) > MAX_SNAP_TRANSCRIPT_CHARACTERS:
        return text, []
    by_fold = {word.casefold(): word for word in words}
    targets = [(word, _sound_key(word)) for word in words if len(_sound_key(word)) >= MIN_SNAP_LETTERS]
    tokens = list(SNAP_TOKEN.finditer(text))
    pieces: List[str] = []
    changes: List[Dict[str, str]] = []
    cursor = 0
    index = 0
    while index < len(tokens):
        replacement = None
        used = 1
        best_score = SNAP_SIMILARITY
        for span in range(1, min(MAX_SNAP_SPAN_TOKENS, len(tokens) - index) + 1):
            first, last = tokens[index], tokens[index + span - 1]
            if span > 1 and text[tokens[index + span - 2].end():last.start()].strip(" ") != "":
                break
            original = text[first.start():last.end()]
            listed = by_fold.get(original.casefold())
            if listed is not None:
                if span == 1:
                    replacement, used = listed, 1
                break
            joined = _sound_key(original)
            if len(joined) < MIN_SNAP_LETTERS:
                continue
            for word, key in targets:
                # A word that is only the start of a longer listed term ("whisper" vs "whisper.cpp") is not a match.
                if joined[0] != key[0] or abs(len(joined) - len(key)) > max(1, max(len(joined), len(key)) // 5):
                    continue
                score = SequenceMatcher(None, joined, key).ratio()
                if score >= best_score:
                    replacement, used, best_score = word, span, score
        if replacement is None:
            index += 1
            continue
        first, last = tokens[index], tokens[index + used - 1]
        original = text[first.start():last.end()]
        if original != replacement:
            pieces.append(text[cursor:first.start()] + replacement)
            changes.append({"from": original, "to": replacement})
            cursor = last.end()
        index += used
    pieces.append(text[cursor:])
    return "".join(pieces), changes


MODES = ("rules", "smart")
MAX_CONTEXT_LABEL_CHARACTERS = 128
MAX_CONTEXT_TEXT_CHARACTERS = 1_000
CONTEXT_LABEL_FIELDS = ("app_name", "bundle_id", "field_role")
LABEL_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
TEXT_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def validate_context(context: Optional[Mapping[str, Optional[str]]]) -> Dict[str, str]:
    """Validate the optional focus context. It is data for cleanup, never output."""
    if context is None:
        return {}
    if not isinstance(context, Mapping):
        raise ValueError("Context must be an object.")
    validated: Dict[str, str] = {}
    for key, value in context.items():
        if value is None:
            continue
        if key not in CONTEXT_LABEL_FIELDS and key != "field_text":
            raise ValueError("Context contains an unsupported field.")
        if not isinstance(value, str):
            raise ValueError("Context values must be text.")
        if key == "field_text":
            if len(value) > MAX_CONTEXT_TEXT_CHARACTERS or TEXT_CONTROL_CHARACTERS.search(value):
                raise ValueError("Context text is invalid.")
        elif len(value) > MAX_CONTEXT_LABEL_CHARACTERS or LABEL_CONTROL_CHARACTERS.search(value):
            raise ValueError("Context label is invalid.")
        validated[key] = value
    return validated


_NUMBER_WORDS = (
    "zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    "fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
    "eighty|ninety|hundred"
)
_NUMBER = rf"(?:\d+(?::\d{{2}})?|{_NUMBER_WORDS})"
_CORRECTION_MARKER = r"(?P<marker>no wait|wait no|no|sorry|i mean|make that|rather)"
NUMBER_CORRECTION = re.compile(
    rf"(?<![\w:]){_NUMBER}(?:[ \t]*,)?[ \t]+{_CORRECTION_MARKER}[ \t]*,?[ \t]+(?P<new>{_NUMBER})(?![\w:])",
    re.IGNORECASE,
)
SCRATCH_MARKER = r"(?:scratch that|strike that)"
SCRATCH_PREVIOUS_SENTENCE = re.compile(
    rf"(?:^|(?<=[.!?\n]))[ \t]*[^.!?\n]+[.!?]+[ \t]*{SCRATCH_MARKER}[.!?,]*[ \t]*",
    re.IGNORECASE,
)
# "scratch that" is also an ordinary verb ("she will scratch that sofa"), so the marker only
# counts after a clause boundary or when it ends the clause or starts a new thought.
_SENTENCE_START = r"(?:^|(?<=[.!?\n]))[ \t]*"
SCRATCH_AFTER_BOUNDARY = re.compile(
    rf"{_SENTENCE_START}(?:[^.!?\n]*?(?:[,;]|\b(?:and|so|okay|oh)\b)[ \t]*)?\b{SCRATCH_MARKER}\b[,.!?]*[ \t]*",
    re.IGNORECASE,
)
SCRATCH_ENDING_THE_CLAUSE = re.compile(
    rf"{_SENTENCE_START}[^.!?\n]*?\b{SCRATCH_MARKER}\b"
    # Follow words must start a new thought and never be a noun the verb could take as its
    # object ("scratch that email", "scratch that call"), so only pronouns and imperatives
    # that are not also common nouns are listed.
    r"(?=[,.!?]|[ \t]*$|[ \t]+(?:let|let's|lets|i|we|please|actually|instead|just|send|tell|ask|schedule)\b)"
    r"[,.!?]*[ \t]*",
    re.IGNORECASE,
)
FILLERS = re.compile(r"(?<![\w'’-])(?:um+|uh+|uhm+|erm)(?![\w'’-])[ \t]*,?[ \t]*", re.IGNORECASE)
REPEATED_FUNCTION_WORD = re.compile(
    r"\b(i|the|a|an|to|and|it|we|you|of|in|my|is)(?:[ \t]+\1\b)+",
    re.IGNORECASE,
)
# Words that are also common in German, Dutch or Spanish ("in", "was", "will", "me") are left
# out so a sentence in those languages is not mistaken for English.
ENGLISH_HINT_WORDS = frozenset(
    "the and is are to of it that for you with this have not but we at my let can "
    "be if they there what when just about our your would should i us".split()
)
MIN_ENGLISH_HINT_WORDS = 2


def _looks_english(text: str) -> bool:
    """Judge from the text only when no language was given.

    Needs mostly ASCII letters and at least two distinct common English words, so a
    German or Spanish sentence containing "um" or "er" is not treated as English.
    """
    letters = [character for character in text if character.isalpha()]
    if not letters or sum(1 for character in letters if character.isascii()) / len(letters) < 0.95:
        return False
    hits = {word for word in re.findall(r"[a-z']+", text.lower()) if word in ENGLISH_HINT_WORDS}
    return len(hits) >= MIN_ENGLISH_HINT_WORDS


def _apply_number_correction(match: "re.Match[str]") -> str:
    """"one, no one" is a pronoun, not a correction to the number one."""
    if match.group("marker").lower() == "no" and match.group("new").lower() == "one":
        return match.group(0)
    return match.group("new")


def smart_rules(text: str, language: Optional[str] = None) -> str:
    """Conservative removals and simplifications; never adds words.

    Applies only to English, because fillers such as "um" and "er" are real words
    in other languages. An explicit non-English language skips every rule, and an
    absent language is judged from the text itself.
    """
    if language is not None:
        if language.casefold().split("-")[0] != "en":
            return text
    elif not _looks_english(text):
        return text
    smart = SCRATCH_PREVIOUS_SENTENCE.sub("", text)
    smart = SCRATCH_AFTER_BOUNDARY.sub("", smart)
    smart = SCRATCH_ENDING_THE_CLAUSE.sub("", smart)
    smart = NUMBER_CORRECTION.sub(_apply_number_correction, smart)
    smart = FILLERS.sub("", smart)
    smart = REPEATED_FUNCTION_WORD.sub(lambda match: match.group(1), smart)
    return smart


def _space_punctuation(match: "re.Match[str]") -> str:
    """Put one space after punctuation, except inside numbers like 4:15, 3.5 or 1,000."""
    text = match.string
    start, end = match.span()
    inside_number = (
        end - start == 1
        and start > 0
        and end < len(text)
        and text[start - 1].isdigit()
        and text[end].isdigit()
    )
    return match.group(1) if inside_number else match.group(1) + " "


class DictationCleanupEngine:
    """Apply predictable punctuation and explicit user word fixes.

    The default ``rules`` mode never removes or rewrites words the speaker said.
    The opt-in ``smart`` mode adds the conservative English removals above.
    """

    @staticmethod
    def clean(
        transcript: str,
        dictionary: Optional[Mapping[str, str]] = None,
        mode: str = "rules",
        language: Optional[str] = None,
        words: Optional[Sequence[str]] = None,
    ) -> str:
        return DictationCleanupEngine.clean_with_steps(transcript, dictionary, mode, language, words)[0]

    @staticmethod
    def clean_with_steps(
        transcript: str,
        dictionary: Optional[Mapping[str, str]] = None,
        mode: str = "rules",
        language: Optional[str] = None,
        words: Optional[Sequence[str]] = None,
    ) -> Tuple[str, Dict[str, object]]:
        """Clean the transcript and report what each stage did, for the history steps view."""
        if not isinstance(transcript, str):
            raise ValueError("Transcript must be text.")
        if len(transcript) > MAX_TRANSCRIPT_CHARACTERS:
            raise ValueError(f"Transcript must not exceed {MAX_TRANSCRIPT_CHARACTERS} characters.")
        if CONTROL_CHARACTERS.search(transcript):
            raise ValueError("Transcript cannot contain control characters.")
        if not transcript.strip():
            raise ValueError("Transcript text cannot be empty.")
        if mode not in MODES:
            raise ValueError("Cleanup mode is not supported.")

        cleaned = transcript.strip()
        if mode == "smart":
            cleaned = smart_rules(cleaned, language).strip() or cleaned
        steps: Dict[str, object] = {"after_smart": cleaned if mode == "smart" else None}
        replacements = _validate_dictionary(dictionary)
        word_list = _validate_words(words)
        dictionary_changes: List[Dict[str, str]] = []

        def record_replacement(match: "re.Match[str]", target: str) -> str:
            if match.group(0) != target:
                dictionary_changes.append({"from": match.group(0), "to": target})
            return target

        # The plain word list runs first so an explicit replacement always has the last word.
        cleaned, snapped = snap_to_word_list(cleaned, word_list)
        dictionary_changes.extend(snapped)
        for source in sorted(replacements, key=lambda value: (-len(value), value.casefold())):
            pattern = re.compile(r"(?<!\w)" + re.escape(source) + r"(?!\w)", re.IGNORECASE)
            cleaned = pattern.sub(lambda match, target=replacements[source]: record_replacement(match, target), cleaned)
        steps["dictionary_changes"] = dictionary_changes[:50]

        for spoken, symbol in SPOKEN_PUNCTUATION:
            pattern = re.compile(r"(?<!\w)" + re.escape(spoken) + r"(?!\w)", re.IGNORECASE)
            cleaned = pattern.sub(lambda _match, value=symbol: value, cleaned)

        cleaned = re.sub(r"[ \t]*([,.;:!?])[ \t]*", _space_punctuation, cleaned)
        cleaned = re.sub(r"[ \t]*\n[ \t]*", "\n", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in cleaned.split("\n"))
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        cleaned = re.sub(
            r"(^|[.!?][ \t]+|\n+)([a-z])",
            lambda match: match.group(1) + match.group(2).upper(),
            cleaned,
        )
        if cleaned and cleaned[-1] not in ".!?…\"'”’)]}":
            cleaned += "."
        return cleaned, steps
