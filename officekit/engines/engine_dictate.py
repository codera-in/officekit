"""Bounded, deterministic formatting for user-provided meeting transcripts."""

import html
import re
from typing import Any, Dict, List


MAX_TRANSCRIPT_CHARACTERS = 262_144
ACTION_KEYWORDS = (
    "will",
    "action item",
    "todo",
    "task",
    "follow up",
    "assign",
    "need to",
    "needs to",
    "must",
    "let us",
    "let's",
)
DECISION_KEYWORDS = ("decided", "agreed", "decision", "concluded", "approved", "chosen")
ACTION_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(value) for value in ACTION_KEYWORDS if value != "will")
    + r"|will\b(?!\s+be\s+(?:a|an|the|available|ready|open|closed|finished|completed|done|released|supported|included|expected|required|possible|necessary|useful|important|safe|made|reached|announced|\w+ed)\b)"
    r"(?!\s+remain\b))",
    re.IGNORECASE,
)
DECISION_PATTERN = re.compile(r"\b(?:" + "|".join(re.escape(value) for value in DECISION_KEYWORDS) + r")\b", re.IGNORECASE)
NEGATED_COMMITMENT_PATTERN = re.compile(
    r"\b(?:will\s+(?:not|never)|won't|should\s+(?:not|never)|shouldn't|must\s+(?:not|never)|mustn't|"
    r"(?:do|does|did)\s+not\s+need\s+to|(?:don['’]t|doesn['’]t|didn['’]t)\s+need\s+to|"
    r"(?:let['’]s|let us)\s+not\s+(?!forget\b)|"
    r"no\s+need\s+to|(?:do|does|did)\s+not\s+have\s+to|(?:is|are|was|were)\s+not\s+required\s+to|"
    r"(?:is|are|was|were)\s+not\s+necessary\s+to)\b",
    re.IGNORECASE,
)
TENTATIVE_WILL_PATTERN = re.compile(
    r"\bwill\s+(?:(?:probably|possibly|maybe|perhaps|likely|hopefully)\b|"
    r"(?:try|attempt|aim|hope)(?:\s+to)?\b|"
    r"be\s+(?:trying|attempting|aiming|hoping)\s+to\b)",
    re.IGNORECASE,
)
STATE_ONLY_OBLIGATION_PATTERN = re.compile(
    r"\b(?:must|need to|needs to)\s+be\s+(?:ready|available|prepared|aware|careful)\b",
    re.IGNORECASE,
)
STATE_FOLLOW_ON_ACTION_PATTERN = re.compile(
    r"\b(?:and|then|to)\s+(?:answer|attend|build|call|check|complete|confirm|contact|create|"
    r"decide|deliver|draft|fix|finish|investigate|make|prepare|publish|resolve|review|schedule|"
    r"send|share|submit|test|update|write)\b",
    re.IGNORECASE,
)
DECISION_ADJECTIVE_PREFIX_PATTERN = re.compile(
    r"\b(?:a|an|the|our|your|their|his|her|its|this|that)\s+$",
    re.IGNORECASE,
)
CONDITIONAL_COMMITMENT_PATTERN = re.compile(
    r"^\s*(?:if|only\s+if|unless|assuming(?:\s+that)?|provided(?:\s+that)?|in\s+case)\b",
    re.IGNORECASE,
)
NEGATED_DECISION_PATTERN = re.compile(
    r"\b(?:not|never|no\s+longer|haven't|hasn't|hadn't|didn't|did\s+not|have\s+not|has\s+not|had\s+not)\b"
    r"[^.!?\r\n]{0,80}\b(?:decided|agreed|decision|concluded|approved|chosen)\b|"
    r"\bno\s+(?:formal\s+)?decision\b|"
    r"\b(?:decision|choice|outcome)\s+(?:was|were|has|have|had)\s+not\s+"
    r"(?:been\s+)?(?:made|reached|taken|finalized|finalised|approved|chosen|decided|agreed)\b",
    re.IGNORECASE,
)
UNRESOLVED_DECISION_PATTERN = re.compile(
    r"\bno\s+(?:(?:formal|final|clear|firm|specific)\s+)?decision\b|"
    r"\bno\s+(?:(?:formal|final|clear|firm|specific)\s+)?decision\s+"
    r"(?:has|have|had)\s+been\s+(?:made|reached|taken|finalized|finalised)\b|"
    r"\b(?:need|needs|must|should|have\s+to|has\s+to|require|requires|requiring)\s+"
    r"(?:to\s+)?(?:(?:make|reach|take|finalize|finalise)\s+)?"
    r"(?:(?:a|the|final|formal|clear|firm|specific)\s+)?decision\b|"
    r"\bdecision\s+(?:is\s+)?(?:needed|required|pending|open|under\s+review|"
    r"to\s+be\s+(?:made|reached|taken))\b|"
    r"\b(?:decision|choice|outcome)\s+(?:(?:will|would|may|might|could)\s+be\s+)?"
    r"(?:is|remains|stays|will\s+remain|may\s+remain|might\s+remain)\s+"
    r"(?:still\s+)?(?:pending|open|unresolved|undecided)\b|"
    r"\b(?:decision|choice|outcome)\s+(?:is|remains)\s+not\s+"
    r"(?:yet\s+)?(?:final|finalized|finalised|made|reached)\b|"
    r"\bdecision\s+(?:will|would|may|might|could)\s+be\s+"
    r"(?:made|reached|taken|finalized|finalised|announced)\b|"
    r"\b(?:may|might|could|possibly|probably)\s+(?:have\s+)?"
    r"(?:decided|agreed|concluded|approved|chosen)\b",
    re.IGNORECASE,
)
CONTRASTIVE_CLAUSE_PATTERN = re.compile(
    r";\s*|,\s*(?:but|however|although)\s+|\s+(?:but|however|although)\s+",
    re.IGNORECASE,
)
NEGATED_ACTION_AND_PATTERN = re.compile(
    r"\s+and\s+(?=(?:(?i:i|we|you|he|she|it|they)\b|"
    r"[A-Z][a-zA-Z'’-]*(?:\s+[A-Z][a-zA-Z'’-]*){0,2}|"
    r"(?i:(?:the|our|your)\s+(?:design\s+team|product\s+team|engineering\s+team|"
    r"team|group|company|department|project|manager|owner|lead)))\s+"
    r"(?i:will|won't|should|shouldn't|must|mustn't|need to|needs to|has to|have to)\b)"
)
MARKDOWN_SPECIAL_PATTERN = re.compile(r"([\\`*_{}\[\]()#+.!|>~-])")


def _escape_markdown_text(value: str) -> str:
    escaped = html.escape(" ".join(value.split()), quote=False)
    return MARKDOWN_SPECIAL_PATTERN.sub(r"\\\1", escaped)


def _split_sentences(transcript: str) -> List[tuple[str, bool]]:
    raw_sentences = re.split(r"(?<=[.!?])\s+|[\r\n]+", transcript)
    sentences = []
    for raw_sentence in raw_sentences:
        is_question = raw_sentence.rstrip().endswith("?")
        sentence = " ".join(raw_sentence.split()).strip().rstrip(".!?").strip()
        if len(sentence) >= 5:
            sentences.append((sentence, is_question))
    return sentences


def _split_contrastive_clauses(sentence: str) -> List[str]:
    clauses = [clause.strip() for clause in CONTRASTIVE_CLAUSE_PATTERN.split(sentence) if clause.strip()]
    expanded = []
    for clause in clauses:
        conjunction = NEGATED_ACTION_AND_PATTERN.search(clause)
        if conjunction and NEGATED_COMMITMENT_PATTERN.search(clause[:conjunction.start()]):
            left, right = clause[:conjunction.start()].strip(), clause[conjunction.end():].strip()
            if left and right:
                expanded.extend((left, right))
                continue
        expanded.append(clause)
    return expanded


def _has_decision_evidence(clause: str) -> bool:
    for match in DECISION_PATTERN.finditer(clause):
        marker = match.group(0).casefold()
        if marker in {"approved", "chosen"} and DECISION_ADJECTIVE_PREFIX_PATTERN.search(clause[:match.start()]):
            continue
        return True
    return False


def _transcript_fence(transcript: str) -> str:
    longest_run = max((len(run) for run in re.findall(r"`+", transcript)), default=0)
    return "`" * max(3, longest_run + 1)


class MeetingDictateEngine:
    @staticmethod
    def format_meeting_notes(transcript_text: str) -> Dict[str, Any]:
        """Format supplied text; keyword matches are heuristic, not AI transcription."""
        if not isinstance(transcript_text, str):
            raise ValueError("Transcript must be text.")
        if len(transcript_text) > MAX_TRANSCRIPT_CHARACTERS:
            raise ValueError(f"Transcript must not exceed {MAX_TRANSCRIPT_CHARACTERS} characters.")
        if not transcript_text.strip():
            raise ValueError("Transcript text cannot be empty.")

        action_items: List[str] = []
        decisions: List[str] = []
        key_points: List[str] = []

        for sentence, is_question in _split_sentences(transcript_text):
            clauses = _split_contrastive_clauses(sentence)
            action_clauses = [
                clause for clause in clauses
                if not is_question
                and ACTION_PATTERN.search(clause)
                and not CONDITIONAL_COMMITMENT_PATTERN.search(clause)
                and not NEGATED_COMMITMENT_PATTERN.search(clause)
                and not TENTATIVE_WILL_PATTERN.search(clause)
                and not (
                    STATE_ONLY_OBLIGATION_PATTERN.search(clause)
                    and not STATE_FOLLOW_ON_ACTION_PATTERN.search(clause)
                    and len(tuple(ACTION_PATTERN.finditer(clause))) == 1
                )
            ]
            decision_clauses = [
                clause for clause in clauses
                if not is_question
                and _has_decision_evidence(clause)
                and not NEGATED_DECISION_PATTERN.search(clause)
                and not UNRESOLVED_DECISION_PATTERN.search(clause)
            ]
            action_items.extend(action_clauses)
            decisions.extend(decision_clauses)
            if not action_clauses and not decision_clauses and len(key_points) < 6:
                key_points.append(sentence)

        markdown_lines = [
            "# Meeting Notes & Transcript",
            "**Processed by:** OfficeKit Dictate & Meeting Transcriber",
            "",
            "## 📌 Key Discussion Points",
        ]
        if key_points:
            markdown_lines.extend(f"- {_escape_markdown_text(point)}" for point in key_points)
        else:
            markdown_lines.append("- No discussion points were extracted.")

        markdown_lines.extend(["", "## ✅ Action Items & Next Steps"])
        if action_items:
            markdown_lines.extend(f"- [ ] {_escape_markdown_text(item)}" for item in action_items)
        else:
            markdown_lines.append("- No action items were identified.")

        markdown_lines.extend(["", "## 🎯 Key Decisions"])
        if decisions:
            markdown_lines.extend(
                f"- **Decision:** {_escape_markdown_text(decision)}" for decision in decisions
            )
        else:
            markdown_lines.append("- No formal decisions were recorded.")

        fence = _transcript_fence(transcript_text)
        markdown_lines.extend(
            ["", "## 🎙️ Full Transcript", "", f"{fence}text", transcript_text, fence]
        )

        return {
            "summary": " ".join(key_points[:3]),
            "action_items": action_items,
            "decisions": decisions,
            "markdown": "\n".join(markdown_lines),
            "word_count": len(transcript_text.split()),
        }
