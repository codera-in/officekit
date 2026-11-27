//! Always-on, offline grammar checks for the Speech Coach Live Workspace (Harper, Apache-2.0).
//! Runs in this process on this Mac: no model download, no network, nothing logged.

use crate::coach_workspace::NewFix;
use harper_core::linting::{LintGroup, LintKind, Linter, Suggestion};
use harper_core::spell::FstDictionary;
use harper_core::{Dialect, Document};
use std::sync::{Mutex, OnceLock};

const MAX_QUOTE_CHARS: usize = 60;
const MAX_FIXES_PER_SENTENCE: usize = 3;

static LINTER: OnceLock<Mutex<(std::sync::Arc<FstDictionary>, LintGroup)>> = OnceLock::new();

/// Speech is recognised text, so spelling, capitalisation and punctuation findings are the
/// recogniser's doing; only mistakes a speaker can make are kept. Returns the pattern id.
fn pattern_for(kind: LintKind) -> Option<&'static str> {
    match kind {
        LintKind::Agreement => Some("grammar.subject_verb"),
        LintKind::Grammar | LintKind::Nonstandard | LintKind::WordOrder => Some("grammar.harper"),
        LintKind::Miscellaneous => Some("grammar.articles"),
        LintKind::Repetition | LintKind::Redundancy => Some("vocabulary.repetition"),
        LintKind::Usage | LintKind::Eggcorn | LintKind::Malapropism | LintKind::WordChoice => {
            Some("vocabulary.word_choice")
        }
        _ => None,
    }
}

/// One clear replacement Harper is sure about, with where it sits in the text (in characters).
struct Finding {
    start: usize,
    end: usize,
    quote: String,
    suggestion: String,
    hint: String,
    pattern_id: &'static str,
}

fn findings(text: &str) -> Vec<Finding> {
    let cell = LINTER.get_or_init(|| {
        let dictionary = FstDictionary::curated();
        let linter = LintGroup::new_curated(dictionary.clone(), Dialect::American);
        Mutex::new((dictionary, linter))
    });
    let Ok(mut guard) = cell.lock() else {
        return Vec::new();
    };
    let (dictionary, linter) = &mut *guard;
    let document = Document::new_plain_english(text, dictionary);
    let mut found = Vec::new();
    for lint in linter.lint(&document) {
        let Some(pattern_id) = pattern_for(lint.lint_kind) else {
            continue;
        };
        let Some(Suggestion::ReplaceWith(replacement)) = lint.suggestions.first() else {
            continue;
        };
        let quote: String = text
            .chars()
            .skip(lint.span.start)
            .take(lint.span.len())
            .collect();
        let suggestion: String = replacement.iter().collect();
        if quote.is_empty()
            || quote.chars().count() > MAX_QUOTE_CHARS
            || suggestion.is_empty()
            || suggestion.chars().count() > MAX_QUOTE_CHARS
            || suggestion == quote
        {
            continue;
        }
        found.push(Finding {
            start: lint.span.start,
            end: lint.span.end,
            quote,
            suggestion,
            hint: lint.message,
            pattern_id,
        });
    }
    found
}

/// Grammar and word-choice fixes Harper finds in one finished sentence.
pub fn check_sentence(sentence: &str) -> Vec<NewFix> {
    let mut fixes: Vec<NewFix> = Vec::new();
    for finding in findings(sentence) {
        if fixes.iter().any(|fix| fix.quote == finding.quote) {
            continue;
        }
        fixes.push(NewFix {
            quote: finding.quote,
            suggestion: finding.suggestion,
            hint: finding.hint,
            pattern_id: finding.pattern_id.to_string(),
        });
        if fixes.len() == MAX_FIXES_PER_SENTENCE {
            break;
        }
    }
    fixes
}

/// Prefer one grounded clarity rewrite. Fall back to grammar when the local model cannot help.
/// Returning either a rewrite or individual fixes prevents overlapping corrections in Copy.
pub fn check_workspace_sentence(sentence: &str, response: Option<&str>) -> Vec<NewFix> {
    if let Some(found) = response
        .and_then(|response| crate::speech_coach::validate_workspace_suggestion(sentence, response))
    {
        return vec![NewFix {
            quote: found.quote,
            suggestion: found.suggestion,
            hint: found.hint,
            pattern_id: found.pattern_id,
        }];
    }
    check_sentence(sentence)
}

/// The most corrections applied to one dictation, so a long ramble is never rewritten wholesale.
const MAX_APPLIED_FIXES: usize = 5;

/// A correction applied to dictated text, shown in "How it was made".
#[derive(Clone, Debug, PartialEq, serde::Serialize)]
pub struct AppliedFix {
    pub from: String,
    pub to: String,
    pub hint: String,
}

fn has_digit(text: &str) -> bool {
    text.chars().any(|c| c.is_ascii_digit())
}

/// True when `index` (a character offset) sits inside an open pair of quotation marks.
fn inside_quotes(chars: &[char], index: usize) -> bool {
    let straight = chars[..index].iter().filter(|c| **c == '"').count();
    let open = chars[..index].iter().filter(|c| **c == '\u{201C}').count();
    let close = chars[..index].iter().filter(|c| **c == '\u{201D}').count();
    straight % 2 == 1 || open > close
}

/// Applies Harper's clear replacements to dictated text. Numbers, quoted text and any word the
/// person keeps in their dictionary or word list are never changed, and at most
/// `MAX_APPLIED_FIXES` corrections are made.
pub fn fix_text(text: &str, protected_terms: &[String]) -> (String, Vec<AppliedFix>) {
    let chars: Vec<char> = text.chars().collect();
    let protected: Vec<String> = protected_terms
        .iter()
        .map(|term| term.to_lowercase())
        .filter(|term| !term.is_empty())
        .collect();
    let mut chosen: Vec<Finding> = Vec::new();
    for finding in findings(text) {
        let lowered = finding.quote.to_lowercase();
        if has_digit(&finding.quote)
            || has_digit(&finding.suggestion)
            || inside_quotes(&chars, finding.start)
            || protected.iter().any(|term| lowered.contains(term.as_str()))
            || chosen
                .iter()
                .any(|other| finding.start < other.end && other.start < finding.end)
        {
            continue;
        }
        chosen.push(finding);
        if chosen.len() == MAX_APPLIED_FIXES {
            break;
        }
    }
    chosen.sort_by_key(|finding| finding.start);
    let mut fixed = String::with_capacity(text.len());
    let mut cursor = 0;
    for finding in &chosen {
        fixed.extend(&chars[cursor..finding.start]);
        fixed.push_str(&finding.suggestion);
        cursor = finding.end;
    }
    fixed.extend(&chars[cursor..]);
    let applied = chosen
        .into_iter()
        .map(|finding| AppliedFix {
            from: finding.quote,
            to: finding.suggestion,
            hint: finding.hint,
        })
        .collect();
    (fixed, applied)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn workspace_uses_one_rewrite_or_local_grammar_fallback() {
        let source = "We buyed fruit today.";
        let response = "PATTERN: sentence_clarity\nQUOTE: We buyed fruit today.\nSUGGESTION: We bought fruit today.\nHINT: Use the irregular past tense.";
        let fixes = check_workspace_sentence(source, Some(response));
        assert_eq!(fixes.len(), 1);
        assert_eq!(fixes[0].quote, source);
        assert_eq!(fixes[0].suggestion, "We bought fruit today.");
        for response in [
            None,
            Some("NONE"),
            Some("malformed"),
            Some(
                "PATTERN: sentence_clarity\nQUOTE: not in source\nSUGGESTION: Invented.\nHINT: No.",
            ),
        ] {
            let fixes = check_workspace_sentence(source, response);
            assert!(fixes
                .iter()
                .any(|fix| fix.quote == "buyed" && fix.suggestion == "bought"));
        }
        assert!(check_workspace_sentence("We bought fruit today.", None).is_empty());
    }

    #[test]
    fn dictated_text_gets_clear_fixes_applied_in_place() {
        let (fixed, applied) = fix_text("We buyed fruit and a apple was cheap.", &[]);
        assert_eq!(fixed, "We bought fruit and an apple was cheap.");
        assert_eq!(
            applied
                .iter()
                .map(|a| (a.from.as_str(), a.to.as_str()))
                .collect::<Vec<_>>(),
            vec![("buyed", "bought"), ("a", "an")]
        );
        assert!(applied.iter().all(|a| !a.hint.is_empty()));
    }

    #[test]
    fn text_with_nothing_clear_to_fix_comes_back_unchanged() {
        let sentence = "It was the ad-hoc calls where they directly join the call.";
        assert_eq!(fix_text(sentence, &[]), (sentence.to_string(), vec![]));
        assert_eq!(fix_text("", &[]), (String::new(), vec![]));
    }

    #[test]
    fn words_in_the_personal_dictionary_and_quoted_text_are_left_alone() {
        let (fixed, applied) = fix_text("We buyed fruit.", &["Buyed".to_string()]);
        assert_eq!((fixed.as_str(), applied.len()), ("We buyed fruit.", 0));
        let quoted = "He wrote \"we buyed fruit\" in the note.";
        assert_eq!(fix_text(quoted, &[]).0, quoted);
        let curly = "He wrote \u{201C}we buyed fruit\u{201D} in the note.";
        assert_eq!(fix_text(curly, &[]).0, curly);
    }

    #[test]
    fn corrections_per_dictation_are_capped() {
        let text = "We buyed one. We buyed two. We buyed three. We buyed four. We buyed five. We buyed six. We buyed seven.";
        let (fixed, applied) = fix_text(text, &[]);
        assert_eq!(applied.len(), MAX_APPLIED_FIXES);
        assert_eq!(fixed.matches("bought").count(), MAX_APPLIED_FIXES);
        assert_eq!(fixed.matches("buyed").count(), 2);
    }

    #[test]
    fn irregular_verbs_are_corrected_with_a_reason() {
        let fixes = check_sentence("We buyed fruit and the market was busy.");
        let fix = fixes.iter().find(|fix| fix.quote == "buyed").unwrap();
        assert_eq!(fix.suggestion, "bought");
        assert!(!fix.hint.is_empty());
        assert!(fix.pattern_id.starts_with("grammar."));
    }

    #[test]
    fn subject_verb_and_article_mistakes_are_found() {
        let fixes = check_sentence("They was late and a apple was cheap.");
        assert!(fixes
            .iter()
            .any(|fix| fix.quote == "was" && fix.suggestion == "were"));
        assert!(fixes
            .iter()
            .any(|fix| fix.quote == "a" && fix.suggestion == "an"));
    }

    #[test]
    fn a_correct_sentence_has_no_fixes() {
        assert!(check_sentence("I bought fruit and the price is low.").is_empty());
    }

    #[test]
    fn spelling_findings_are_left_to_the_recogniser() {
        let fixes = check_sentence("We buyed fruit today.");
        assert!(fixes.iter().all(|fix| !fix.hint.contains("spell")));
    }

    #[test]
    fn at_most_three_fixes_per_sentence() {
        let fixes =
            check_sentence("He don't like it and they was late and I goed to a apple stand.");
        assert!(fixes.len() <= MAX_FIXES_PER_SENTENCE);
    }
}
