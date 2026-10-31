"""Prompts and JSON schemas for each pipeline stage.

The guidelines follow Blaha & Rumbaugh's object-oriented analysis rules for keeping
the right classes and associations. They are deliberately generic: nothing here is
tuned to the evaluation benchmark.
"""

SYSTEM = """You are a senior requirements analyst who builds conceptual domain models \
(classes, attributes, associations) from requirements and design documents.

A domain class is a concept in the problem domain that the system must keep information \
about: people and organizations it records, physical or digital things, places, documents, \
records, transactions, and events that are stored. Discard candidates that are:
- irrelevant: outside the scope of the system described;
- implementation: constructs of the software rather than the domain (system, app, database, \
screen, page, button, API, notification mechanism, log, account settings);
- operation: an action or process, unless it is recorded as an object with its own \
properties (a stored "booking" is a class, "booking a lesson" is not);
- redundant: another name for a concept you already have; keep the most descriptive name;
- vague: too general to be a distinct concept (information, data, details, content, item);
- attribute: a property of another object (name, date, price, status, email, address, \
amount, a preference value);
- role: a mere access or permission level about which nothing is recorded (visitor, \
logged-in user). Keep actors the system stores information about.

Naming: use the document's own terminology and language. Use singular nouns. For English, \
write names in lowercase words separated by spaces (e.g. "shopping list").

Evidence: when asked for evidence, copy short quotes verbatim from the document \
(at most 25 words each). Never paraphrase inside an evidence quote."""

_EVIDENCE = {"type": "array", "items": {"type": "string"}}

CLASSES_TASK = """Task: derive the domain classes for the system described in the document.
Work in two passes: first list every candidate noun or noun phrase, then apply the discard \
rules and keep only the true domain classes. Return only the final classes, each with a \
one-sentence definition and 1-3 evidence quotes."""

CLASSES_SCHEMA = {
    "type": "object",
    "properties": {"classes": {"type": "array", "items": {
        "type": "object",
        "properties": {"name": {"type": "string"}, "definition": {"type": "string"},
                       "evidence": _EVIDENCE},
        "required": ["name", "definition", "evidence"],
        "additionalProperties": False}}},
    "required": ["classes"],
    "additionalProperties": False,
}

MERGE_TASK = """Task: {k} analysts extracted domain classes from the document independently. \
Below are the distinct names they produced, with how many analysts used each name and one \
definition.

{candidates}

Group names that denote the same domain concept: synonyms, spelling or number variants, \
abbreviations, or a longer name for the same thing. Do not merge different concepts, and do \
not merge a subtype into its supertype unless the document uses them interchangeably. Every \
name must appear in exactly one group. For each group, choose as canonical the most \
descriptive name the document itself uses."""

MERGE_SCHEMA = {
    "type": "object",
    "properties": {"groups": {"type": "array", "items": {
        "type": "object",
        "properties": {"canonical": {"type": "string"},
                       "members": {"type": "array", "items": {"type": "string"}}},
        "required": ["canonical", "members"],
        "additionalProperties": False}}},
    "required": ["groups"],
    "additionalProperties": False,
}

VERIFY_CLASSES_TASK = """Task: review these candidate domain classes against the document \
and the discard rules. "Agreement" is the share of independent analysts who proposed the \
candidate; it is evidence, not proof.

{candidates}

For each candidate decide keep or reject. If two candidates denote the same concept, keep the \
more descriptive one and reject the other as redundant. Reject a candidate the document does \
not support. Do not reject a concept the system clearly needs to keep information about."""

CLASS_CATEGORIES = ["valid", "irrelevant", "implementation", "operation", "redundant",
                    "vague", "attribute", "role", "unsupported"]


def verify_schema(ids: list[str], categories: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {"verdicts": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string", "enum": ids},
                           "decision": {"type": "string", "enum": ["keep", "reject"]},
                           "category": {"type": "string", "enum": categories},
                           "reason": {"type": "string"}},
            "required": ["id", "decision", "category", "reason"],
            "additionalProperties": False}}},
        "required": ["verdicts"],
        "additionalProperties": False,
    }


ATTRIBUTES_TASK = """Task: the domain classes of this system are:
{classes}

List the attributes of these classes that the document states or clearly requires (data \
the system must store about each object). An attribute is a simple property, not another \
class; a reference to another class is an association, not an attribute. Give each a \
datatype and 1-2 evidence quotes."""

DATATYPES = ["string", "text", "integer", "decimal", "money", "boolean", "date",
             "datetime", "duration", "enum", "file", "other"]


def attributes_schema(class_names: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {"attributes": {"type": "array", "items": {
            "type": "object",
            "properties": {"class": {"type": "string", "enum": class_names},
                           "name": {"type": "string"},
                           "datatype": {"type": "string", "enum": DATATYPES},
                           "evidence": _EVIDENCE},
            "required": ["class", "name", "datatype", "evidence"],
            "additionalProperties": False}}},
        "required": ["attributes"],
        "additionalProperties": False,
    }


RELATIONS_TASK = """Task: the domain classes of this system are:
{classes}

Identify the relationships between these classes that the system must record. Use only the \
classes listed. Kinds: association, aggregation (whole-part), composition (part cannot exist \
without the whole), generalization (source is a subtype of target). Rules:
- Discard derived relationships that can be obtained by following other relationships \
(if A-B and B-C exist, do not add A-C unless it carries its own meaning in the document).
- Discard relationships that describe implementation rather than the domain.
- Decompose relationships among three or more classes into binary ones.
Give each a short verb-phrase name, multiplicities, and 1-2 evidence quotes."""

RELATION_KINDS = ["association", "aggregation", "composition", "generalization"]
MULTIPLICITIES = ["1", "0..1", "*", "1..*"]


def relations_schema(class_names: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {"relations": {"type": "array", "items": {
            "type": "object",
            "properties": {"source": {"type": "string", "enum": class_names},
                           "target": {"type": "string", "enum": class_names},
                           "kind": {"type": "string", "enum": RELATION_KINDS},
                           "name": {"type": "string"},
                           "source_multiplicity": {"type": "string", "enum": MULTIPLICITIES},
                           "target_multiplicity": {"type": "string", "enum": MULTIPLICITIES},
                           "evidence": _EVIDENCE},
            "required": ["source", "target", "kind", "name", "source_multiplicity",
                         "target_multiplicity", "evidence"],
            "additionalProperties": False}}},
        "required": ["relations"],
        "additionalProperties": False,
    }


VERIFY_RELATIONS_TASK = """Task: review these candidate relationships between domain classes \
against the document. "Agreement" is the share of independent analysts who proposed it.

{candidates}

Reject a relationship that is derived (it follows from a path of other candidates; say \
which path), redundant with another candidate, describes implementation, or is not supported \
by the document. Keep relationships the system must record directly."""

RELATION_CATEGORIES = ["valid", "derived", "redundant", "implementation", "irrelevant",
                       "unsupported"]
