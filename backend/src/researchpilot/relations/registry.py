"""Code mirror of ``relation_registry`` / ``relation_endpoint_rules`` (ARCHITECTURE §12.4.1).

Every relationship type has exactly one PostgreSQL source. Types whose source tables arrive
in later releases are listed with ``introduced_in`` and ``available = False``; the database
registry contains exactly the available ones (tested, R1-65 (a)).
"""

from __future__ import annotations

from dataclasses import dataclass

from researchpilot.domain.enums import RelationClass, ScopePolicy


@dataclass(frozen=True)
class RelationSpec:
    type: str
    relation_class: RelationClass
    source_table: str
    from_column: str
    to_column: str
    scope_column: str | None
    scope_policy: ScopePolicy
    introduced_in: str
    source_column: str | None = None
    type_discriminator: str | None = None
    projected: bool = True
    available: bool = True  # False: the source table arrives in a later release

    @property
    def is_research(self) -> bool:
        return self.relation_class is RelationClass.RESEARCH

    @property
    def discriminator_value(self) -> str | None:
        """Value of ``type_discriminator`` that selects this type (e.g. role 'introduces')."""
        if self.type_discriminator is None:
            return None
        return self.type.lower() if self.type_discriminator == "role" else self.type


_R = RelationClass.RESEARCH
_S = RelationClass.STRUCTURAL
_G = ScopePolicy.GLOBAL_ONLY
_P = ScopePolicy.PROJECT_ONLY
_PG = ScopePolicy.PROJECT_OR_GLOBAL
_SCOPE = "scope_project_id"


def _entity(type_: str) -> RelationSpec:
    return RelationSpec(
        type_,
        _R,
        "entity_links",
        "subject_uid",
        "entity_id",
        _SCOPE,
        _PG,
        "R1",
        type_discriminator="role",
    )


def _research(type_: str, policy: ScopePolicy = _PG) -> RelationSpec:
    return RelationSpec(
        type_,
        _R,
        "research_relations",
        "from_uid",
        "to_uid",
        _SCOPE,
        policy,
        "R1",
        type_discriminator="type",
    )


SPECS: tuple[RelationSpec, ...] = (
    RelationSpec("CITES", _R, "citations", "citing_id", "cited_id", _SCOPE, _G, "R1"),
    RelationSpec("AUTHORED_BY", _R, "paper_authors", "paper_id", "author_id", _SCOPE, _G, "R1"),
    RelationSpec(
        "AFFILIATED_WITH", _R, "author_affiliations", "author_id", "group_id", _SCOPE, _G, "R1"
    ),
    _entity("INTRODUCES"),
    _entity("USES_METHOD"),
    _entity("EVALUATES_ON"),
    RelationSpec(
        "REPORTS_LIMITATION",
        _R,
        "limitations",
        "paper_id",
        "id",
        None,
        _G,
        "R2",
        source_column="paper_id",
        available=False,
    ),
    _research("EXTENDS"),
    _research("CONTRADICTS"),
    _research("RELATED_TO"),
    _research("ADDRESSES"),
    _research("DERIVED_FROM"),
    _research("VALIDATED_BY", _P),
    RelationSpec(
        "IMPLEMENTED_BY",
        _R,
        "item_code_links",
        "item_id",
        "repo_id",
        _SCOPE,
        _PG,
        "R4",
        available=False,
    ),
    RelationSpec(
        "HAS_VERSION",
        _S,
        "paper_manifestations",
        "paper_id",
        "id",
        None,
        _G,
        "R1",
        source_column="paper_id",
    ),
    RelationSpec(
        "IN_PROJECT", _S, "project_items", "item_id", "project_id", "project_id", _P, "R1"
    ),
    RelationSpec(
        "PART_OF",
        _S,
        "structural_relations",
        "child_uid",
        "parent_uid",
        _SCOPE,
        _P,
        "R1",
        type_discriminator="type",
    ),
    RelationSpec(
        "RESULT_FOR",
        _S,
        "structural_relations",
        "child_uid",
        "parent_uid",
        _SCOPE,
        _PG,
        "R2",
        type_discriminator="type",
        available=False,
    ),
)

BY_TYPE: dict[str, RelationSpec] = {s.type: s for s in SPECS}
AVAILABLE: tuple[RelationSpec, ...] = tuple(s for s in SPECS if s.available)

# entity_links roles that are assessment data, not graph relationships (never projected).
NON_PROJECTED_ENTITY_ROLES = frozenset({"compares_against", "reports_metric"})

RESEARCH_TABLES = frozenset(s.source_table for s in AVAILABLE if s.is_research)
STRUCTURAL_TABLES = frozenset(s.source_table for s in AVAILABLE if not s.is_research)

# Allowed endpoint combinations (type, from_kind, to_kind); '*' = any kind.
ENDPOINT_RULES: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("CITES", "Paper", "Paper"),
        ("AUTHORED_BY", "Paper", "Author"),
        ("AFFILIATED_WITH", "Author", "ResearchGroup"),
        *{("INTRODUCES", "Paper", k) for k in ("Method", "Dataset", "Benchmark", "Metric")},
        *{("USES_METHOD", k, "Method") for k in ("Paper", "Proposal", "Experiment")},
        *{
            ("EVALUATES_ON", a, b)
            for a in ("Paper", "Method", "Proposal", "Experiment")
            for b in ("Dataset", "Benchmark")
        },
        ("EXTENDS", "Paper", "Paper"),
        ("EXTENDS", "Method", "Method"),
        ("CONTRADICTS", "Paper", "Paper"),
        ("CONTRADICTS", "Result", "Result"),
        ("CONTRADICTS", "Paper", "Hypothesis"),
        ("RELATED_TO", "*", "*"),
        ("ADDRESSES", "Paper", "Gap"),
        ("ADDRESSES", "Paper", "Topic"),
        ("ADDRESSES", "Proposal", "Hypothesis"),
        ("ADDRESSES", "Experiment", "Hypothesis"),
        ("DERIVED_FROM", "Gap", "Limitation"),
        ("DERIVED_FROM", "Gap", "LimitationCluster"),
        ("DERIVED_FROM", "Gap", "Paper"),
        ("DERIVED_FROM", "Hypothesis", "Gap"),
        ("DERIVED_FROM", "Proposal", "Hypothesis"),
        ("VALIDATED_BY", "Hypothesis", "Result"),
        ("VALIDATED_BY", "Hypothesis", "Experiment"),
        ("HAS_VERSION", "Paper", "PaperVersion"),
        ("IN_PROJECT", "Paper", "Project"),
        ("PART_OF", "Topic", "Objective"),
    }
)


def allowed(type_: str, from_kind: str, to_kind: str) -> bool:
    return any((type_, a, b) in ENDPOINT_RULES for a in (from_kind, "*") for b in (to_kind, "*"))


# Reference columns into node-source tables that are NOT relationship sources
# (ARCHITECTURE §12.4.3), keyed by "table.column". Columns named ``project_id`` /
# ``scope_project_id`` that reference projects are access-control scope. Any other reference
# column must be a registered source column or be declared here (R1-65 (c), (d)).
_MANIFESTATION_DATA = (
    "paper_dates",
    "paper_identifiers",
    "paper_source_links",
    "paper_version_links",
    "paper_versions",
    "manifestation_authors",
)
DECLARED_NON_SOURCES: dict[str, str] = {
    "papers.id": "supertype identity (research_items)",
    "entities.id": "supertype identity (research_items)",
    "papers.first_public_manifestation_id": "derived pointer (resolved first public version)",
    "papers.abstract_manifestation_id": "derived pointer (which version the abstract is from)",
    "papers.merged_into_id": "decision log (merge representation; HAS_VERSION is the link)",
    "projects.id": "access-control scope (composite key of the active objective)",
    "paper_match_decisions.paper_a": "decision log",
    "paper_match_decisions.paper_b": "decision log",
    "paper_merge_events.surviving_id": "decision log",
    "paper_merge_events.merged_id": "decision log",
    "project_items.discovered_from_item_id": "project memory (how an item was found)",
    "claim_evidence.item_id": "evidence (node data of a claim)",
    "evidence_spans.paper_id": "node data (owning work)",
    "evidence_spans.manifestation_id": "node data (version the quote comes from)",
    "author_affiliations.paper_id": "edge property of AFFILIATED_WITH",
    "entity_links.manifestation_id": "edge property (version the evidence comes from)",
    **{f"{t}.manifestation_id": "node data (owning version)" for t in _MANIFESTATION_DATA},
    **{
        f"{t}.paper_id": "node data (owning version's work, denormalised; moves with HAS_VERSION)"
        for t in _MANIFESTATION_DATA
    },
}
