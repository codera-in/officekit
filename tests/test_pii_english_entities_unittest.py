from dataclasses import dataclass

from officekit.engines.pii_english_entities import PiiEnglishEntityDetector


@dataclass
class FakeEntity:
    text: str
    label_: str
    start_char: int
    end_char: int


class FakeDoc:
    def __init__(self, entities):
        self.ents = entities


class FakeModel:
    def __init__(self, entities_by_line):
        self.entities_by_line = entities_by_line

    def __call__(self, text):
        return FakeDoc(self.entities_by_line.get(text.strip(), []))


def _entity(line, text, label):
    start = line.index(text)
    return FakeEntity(text, label, start, start + len(text))


def test_detects_resume_name_employer_and_school_as_review_only_candidates():
    text = (
        "ALICE ANDERSON\n"
        "VP of Engineering\n"
        "Acme Systems LLC\n"
        "Northstar School of Engineering\n"
        "Springfield, IL\n"
        "Blockchain Banking Solution\n"
        "Cypher (cypher.example) YC 22\n"
    )
    model = FakeModel({
        "ALICE ANDERSON": [_entity("ALICE ANDERSON", "ALICE ANDERSON", "GPE")],
        "VP of Engineering": [_entity("VP of Engineering", "VP of Engineering", "ORG")],
        "Acme Systems LLC": [_entity("Acme Systems LLC", "Acme Systems LLC", "ORG")],
        "Northstar School of Engineering": [_entity("Northstar School of Engineering", "Northstar School of Engineering", "PERSON")],
        "Springfield, IL": [_entity("Springfield, IL", "Springfield", "GPE")],
        "Blockchain Banking Solution": [_entity("Blockchain Banking Solution", "Blockchain Banking Solution", "PERSON")],
        "Cypher (cypher.example) YC 22": [_entity("Cypher (cypher.example) YC 22", "Cypher", "PERSON")],
    })

    matches = PiiEnglishEntityDetector(model=model).detect(text)

    assert [(item["value"], item["type"]) for item in matches] == [
        ("ALICE ANDERSON", "person"),
        ("Acme Systems LLC", "organization"),
        ("Northstar School of Engineering", "organization"),
        ("Cypher", "organization"),
    ]
    assert all(item["confidence"] == "possible" for item in matches)
    assert all(item["_source"] == "heuristic" for item in matches)
    assert all(text[item["_start"]:item["_end"]] == item["value"] for item in matches)


def test_ignores_locations_and_header_lines_that_are_not_names():
    text = "EXPERIENCE\nSpringfield, IL\n"
    model = FakeModel({
        "EXPERIENCE": [],
        "Springfield, IL": [_entity("Springfield, IL", "Springfield", "GPE")],
    })

    assert PiiEnglishEntityDetector(model=model).detect(text) == []


def test_finds_people_and_organizations_in_generic_document_fields():
    text = (
        "Invoice\n"
        "Prepared by: Maya Chen\n"
        "Approved by: Ravi Kumar, Finance Lead\n"
        "Company: Acme\n"
        "Supplier: Northstar Labs\n"
        "Please contact support for questions.\n"
    )

    matches = PiiEnglishEntityDetector().detect(text)

    assert [(item["value"], item["type"]) for item in matches] == [
        ("Maya Chen", "person"),
        ("Ravi Kumar", "person"),
        ("Acme", "organization"),
        ("Northstar Labs", "organization"),
    ]
    assert all(item["confidence"] == "possible" for item in matches)
    assert all(text[item["_start"]:item["_end"]] == item["value"] for item in matches)


def test_rejects_non_text_and_oversized_input():
    detector = PiiEnglishEntityDetector(model=FakeModel({}))

    try:
        detector.detect(b"not text")
        assert False, "non-text input should be rejected"
    except ValueError as error:
        assert "must be text" in str(error)

    try:
        detector.detect("x" * (detector.MAX_TEXT_BYTES + 1))
        assert False, "oversized text should be rejected"
    except ValueError as error:
        assert "too much text" in str(error)
