//! Plain-words grammar and word-choice rules for Speech Coach fixes, so a correction teaches why.
//! Fixed text bundled with the app: nothing is generated, fetched, logged or sent anywhere.
//!
//! A rule is shown only when it describes the fix in front of the speaker. A rule that does not fit
//! is worse than none, so the broad checker categories either get a rule that is true of all of
//! them or must match the words of the fix.

use serde::Serialize;

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Rule {
    /// The Speech Coach pattern id this rule explains (see `speech_coach::is_supported_language_pattern`).
    pub id: &'static str,
    pub title: &'static str,
    /// The rule in one or two sentences, for someone who has not studied grammar.
    pub rule: &'static str,
    pub wrong: &'static str,
    pub right: &'static str,
}

const IRREGULAR_ID: &str = "grammar.irregular_forms";
const ARTICLES_ID: &str = "grammar.articles";

pub const RULES: [Rule; 10] = [
    Rule {
        id: "grammar.subject_verb",
        title: "Subject–verb agreement",
        rule: "A plural subject takes a plural verb (are, were, have). Only a singular subject takes is, was or has.",
        wrong: "The prices is low.",
        right: "The prices are low.",
    },
    Rule {
        id: "grammar.tense",
        title: "Verb tense",
        rule: "Keep to one time frame. Use the past form for things that are finished and the present form for what is true now.",
        wrong: "Yesterday we go to the market.",
        right: "Yesterday we went to the market.",
    },
    Rule {
        id: ARTICLES_ID,
        title: "Articles",
        rule: "Use a before a consonant sound, an before a vowel sound, and the for one specific thing you both know.",
        wrong: "I need a umbrella.",
        right: "I need an umbrella.",
    },
    Rule {
        id: "grammar.prepositions",
        title: "Prepositions",
        rule: "Many verbs and adjectives go with one fixed preposition, such as depend on, interested in and good at.",
        wrong: "It depends of the price.",
        right: "It depends on the price.",
    },
    Rule {
        id: "grammar.sentence_clarity",
        title: "Sentence clarity",
        rule: "Give each sentence one main idea. Put the subject and verb early, and split a long sentence in two.",
        wrong: "The plan that we made after the meeting that ran long on Monday is ready.",
        right: "We made the plan after Monday's long meeting. It is ready.",
    },
    Rule {
        id: IRREGULAR_ID,
        title: "Irregular forms",
        rule: "Some common words break the usual pattern: verbs that do not add -ed in the past (buy → bought, go → went) and nouns that do not add -s for the plural (child → children).",
        wrong: "We buyed fruit.",
        right: "We bought fruit.",
    },
    Rule {
        id: "vocabulary.vague_word",
        title: "Vague word",
        rule: "Words like thing, stuff and nice say very little. Name the specific thing instead.",
        wrong: "We fixed a few things.",
        right: "We fixed three login bugs.",
    },
    Rule {
        id: "vocabulary.repetition",
        title: "Repeated wording",
        rule: "Saying the same idea twice weakens it. Say it once.",
        wrong: "We should plan ahead in advance.",
        right: "We should plan ahead.",
    },
    Rule {
        id: "vocabulary.precision",
        title: "Word precision",
        rule: "Choose the word that says exactly what you mean. A more specific word is clearer than a general one.",
        wrong: "We made a big change.",
        right: "We made a major change.",
    },
    Rule {
        id: "vocabulary.word_choice",
        title: "Word choice",
        rule: "Some words are mixed up or used in a way that is not standard. Use the word whose meaning fits what you mean.",
        wrong: "That is a mute point.",
        right: "That is a moot point.",
    },
];

fn has_article(quote: &str, suggestion: &str) -> bool {
    format!("{quote} {suggestion}")
        .to_lowercase()
        .split(|c: char| !c.is_alphabetic())
        .any(|word| matches!(word, "a" | "an" | "the"))
}

/// The rule behind a fix, or None when no written rule describes it.
///
/// The checker's "Miscellaneous" findings land under the articles pattern, so that rule is shown
/// only when an article is part of the fix. A generic grammar finding has no rule of its own and is
/// matched by what the checker said it found.
pub fn rule_for(
    pattern_id: &str,
    hint: &str,
    quote: &str,
    suggestion: &str,
) -> Option<&'static Rule> {
    let id = match pattern_id {
        "grammar.harper" if hint.to_lowercase().contains("irregular") => IRREGULAR_ID,
        "grammar.harper" => return None,
        ARTICLES_ID if !has_article(quote, suggestion) => return None,
        other => other,
    };
    RULES.iter().find(|rule| rule.id == id)
}

/// Every rule, for the saved note to show beside a pattern.
#[tauri::command]
pub fn speech_coach_rules() -> Vec<&'static Rule> {
    RULES.iter().collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_pattern_a_fix_can_carry_has_a_rule() {
        for id in [
            "grammar.subject_verb",
            "grammar.tense",
            "grammar.prepositions",
            "grammar.sentence_clarity",
            "vocabulary.vague_word",
            "vocabulary.repetition",
            "vocabulary.precision",
            "vocabulary.word_choice",
        ] {
            assert!(
                crate::speech_coach::is_supported_language_pattern(id),
                "{id} is a supported pattern"
            );
            assert!(rule_for(id, "", "x", "y").is_some(), "{id} has a rule");
        }
        assert!(crate::speech_coach::is_supported_language_pattern(
            ARTICLES_ID
        ));
        assert!(rule_for(ARTICLES_ID, "", "a apple", "an apple").is_some());
    }

    #[test]
    fn a_generic_grammar_finding_gets_a_rule_only_when_it_says_what_it_found() {
        assert_eq!(
            rule_for(
                "grammar.harper",
                "Use the irregular form",
                "buyed",
                "bought"
            )
            .map(|rule| rule.title),
            Some("Irregular forms")
        );
        assert!(rule_for(
            "grammar.harper",
            "Did you mean to spell this word?",
            "x",
            "y"
        )
        .is_none());
        assert!(rule_for("grammar.harper", "", "x", "y").is_none());
        assert!(rule_for("grammar.unknown", "", "x", "y").is_none());
    }

    #[test]
    fn the_articles_rule_is_shown_only_when_an_article_is_part_of_the_fix() {
        assert!(rule_for(ARTICLES_ID, "", "a umbrella", "an umbrella").is_some());
        assert!(rule_for(ARTICLES_ID, "", "the the", "the").is_some());
        assert!(
            rule_for(
                ARTICLES_ID,
                "Possible wording slip",
                "very good",
                "excellent"
            )
            .is_none(),
            "a Miscellaneous finding with no article gets no article rule"
        );
        assert!(
            rule_for(ARTICLES_ID, "", "another", "other").is_none(),
            "'a' inside another word is not an article"
        );
    }

    #[test]
    fn the_precision_and_word_choice_rules_are_true_of_any_fix_in_their_category() {
        for id in ["vocabulary.precision", "vocabulary.word_choice"] {
            let rule = rule_for(id, "", "very good", "excellent").expect("rule");
            for narrow in ["affect", "effect", "moot", "mute"] {
                assert!(
                    !rule.rule.contains(narrow),
                    "{id} rule must not teach one word pair: {}",
                    rule.rule
                );
            }
        }
    }

    #[test]
    fn the_real_checker_output_for_an_irregular_verb_and_noun_gets_the_irregular_rule() {
        let fixes = crate::coach_grammar::check_sentence("We buyed fruit and the market was busy.");
        let buyed = fixes
            .iter()
            .find(|fix| fix.quote == "buyed")
            .expect("the checker flags buyed");
        let rule = rule_for(
            &buyed.pattern_id,
            &buyed.hint,
            &buyed.quote,
            &buyed.suggestion,
        )
        .expect("a rule for the real finding");
        assert_eq!(rule.title, "Irregular forms");
        // A noun the checker flags with the same message must not be taught as a past tense.
        let nouns = crate::coach_grammar::check_sentence("The childs played in the garden.");
        for fix in &nouns {
            if let Some(rule) = rule_for(&fix.pattern_id, &fix.hint, &fix.quote, &fix.suggestion) {
                assert!(
                    !rule.title.to_lowercase().contains("past tense"),
                    "{} → {} must not be labelled a past tense",
                    fix.quote,
                    fix.suggestion
                );
            }
        }
    }

    #[test]
    fn rules_are_short_and_each_example_shows_a_real_difference() {
        let mut ids = std::collections::BTreeSet::new();
        for rule in &RULES {
            assert!(ids.insert(rule.id), "{} appears once", rule.id);
            assert!(!rule.title.is_empty());
            assert!(rule.rule.len() <= 220, "{} rule fits a small card", rule.id);
            assert_ne!(rule.wrong, rule.right, "{} example differs", rule.id);
            assert!(rule.wrong.len() <= 80 && rule.right.len() <= 80);
        }
    }

    #[test]
    fn the_subject_verb_rule_says_when_a_plural_subject_takes_are() {
        let rule = rule_for("grammar.subject_verb", "", "prices is", "prices are").expect("rule");
        assert!(rule.rule.contains("plural subject takes a plural verb"));
        assert!(rule.rule.contains("singular subject takes is"));
    }

    #[test]
    fn the_command_returns_every_rule_with_the_field_names_the_notes_screen_reads() {
        let rules = speech_coach_rules();
        assert_eq!(rules.len(), RULES.len());
        let json = serde_json::to_value(&rules).unwrap();
        for entry in json.as_array().unwrap() {
            for key in ["id", "title", "rule", "wrong", "right"] {
                assert!(
                    entry.get(key).is_some_and(|value| value.is_string()),
                    "{key} is a string"
                );
            }
        }
    }
}
