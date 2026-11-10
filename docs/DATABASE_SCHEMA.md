# Database Schema

**Status:** canonical. It consolidates `docs/plan/03` and
`docs/plan/11 §11.6`, adding the Research Intelligence Engine tables and
the `research_items` supertype.

PostgreSQL 16 with `pgvector` and `pg_trgm`. PostgreSQL is the
transactional source of truth; from R2, Neo4j holds a synchronised knowledge
graph built from these tables (§16, ARCHITECTURE §12). Conventions: UUIDv7 primary keys;
`created_at` and `updated_at` as `timestamptz`; enums managed by Alembic;
`jsonb` only for variable payloads. The **Rel.** column gives the release
that introduces each table (see IMPLEMENTATION_ROADMAP).

## 1. Overview

```
users ─< projects ─┬─< research_objectives ─< objective_sub_questions
                   ├─< research_runs ─< run_events, checkpoints, task_executions
                   │                 └─< search_queries ─< search_results
                   ├─< project_items (membership, inclusion, reading status)
                   ├─< notes, decisions, overrides, feedback
                   └─< reports, monitors, impact_alerts, experiments

research_items (supertype: id, item_type)
   ├── papers ─┬─ paper_identifiers, paper_authors, citations, documents
   │           └─ document_sections ─ evidence_spans, equations
   ├── entities (method, architecture, algorithm, dataset, benchmark, metric,
   │             model, task, concept, term) ─ *_details, entity_links
   ├── code_repositories
   ├── gaps
   └── ideas (hypotheses)

assessments (item × objective) ─< assessment_signals, recommendation_cards
papers ─< paper_manifestations ─< paper_identifiers, paper_dates, paper_versions, documents
                                (preprint and published versions kept distinct)
projects ─< latest_scans ─< latest_scan_entries (Latest Research)
projects ─< tutor_conversations ─< tutor_messages ─< tutor_message_evidence (Ask & Learn)
                              └─< conversation_summaries
projects ─< teaching_sessions ─< understanding_checks; concept_progress; saved_explanations
papers ─< paper_match_decisions (version matching, D29)
claims ─< claim_evidence, claim_verifications
domain_events (outbox) ─▶ graph sync (R2+) ─▶ Neo4j knowledge graph (read model)
graph_nodes, research_relations, structural_relations, relation_registry, author_affiliations, research_groups, entity_tombstones (graph-ready, §16)
```

## 2. Research items (supertype)

| Table | Columns | Rel. |
|---|---|---|
| `research_items` | `id PK, item_type enum(paper, method, architecture, algorithm, dataset, benchmark, metric, model, task, concept, term, repository, gap, idea), project_id null (set for gaps/ideas, which are project-scoped), created_at` | R0 |

Every subtype table uses the same `id` as both its primary key and a foreign
key to `research_items.id`. Assessments, overrides, feedback, notes,
decisions and project membership reference `research_items.id`, which gives
real referential integrity across item types.

## 3. Users, projects, objectives, runs

| Table | Key columns | Rel. |
|---|---|---|
| `users` | `id, display_name, email null, auth_provider enum(local_none, oidc, password) , auth_subject null, password_hash null (argon2id), mfa_enabled bool, default_level, timezone (IANA, e.g. Europe/Berlin), timezone_source enum(browser, user), preferences jsonb, created_at, deleted_at` (a single `local_none` user for local development; auth fields required for hosted deployment, gate H) | R0 (auth fields: H) |
| `project_members` | `project_id, user_id, role enum(owner, editor, viewer), added_at, PK(project_id, user_id)`; every project-scoped query checks membership; Postgres row-level security policies on project-scoped tables | R0 (single owner) / H |
| `security_audit_log` | `id bigserial, user_id null, event enum(login, login_failed, permission_denied, export, deletion, retention_run, settings_change), project_id null, details jsonb (no content), ip_hash, created_at` | H |
| `deletion_log` | `id, subject_hash (one-way salted hash of the user/project ID; no raw IDs), scope enum(conversation, all_conversations, learning_progress, project, account, retention_expiry), object_counts jsonb, requested_at, completed_at` (aggregate audit only; no content, no raw IDs) | R1 |
| `projects` | `id, user_id, title, topic, expertise_level enum, goal enum(learn_field, review_literature, find_gap, plan_experiment, write_proposal, track_field), settings jsonb (incl. enabled sources such as bioRxiv/medRxiv), tutor_retention_policy enum(keep_until_deleted, delete_after_days, do_not_store) default keep_until_deleted, tutor_retention_days int null, status` | R0 |
| `research_objectives` | `id, project_id, version int, core_question, target_tasks text[], focus_concepts text[], exclusions text[], constraints jsonb, expertise_level, goal, source enum(planner, user_edit, feedback_suggestion), created_at, UNIQUE(project_id, version)` | R1 |
| `objective_sub_questions` | `id, key text (SQ1…), text, ordinal` — belongs to its objective version through `structural_relations` (`PART_OF`, exactly one, cascade on delete); no `objective_id` column (single-source rule) | R1 |
| `objective_weight_profiles` | `id, objective_id, weights jsonb, source enum(default, adapted, user), version, active bool` | R1 |
| `research_runs` | `id (= LangGraph thread id), project_id, workflow enum, status enum(queued, running, awaiting_approval, succeeded, partially_succeeded, failed, cancelled), config jsonb, manifest jsonb (git sha, prompt versions, model IDs), objective_version, started_at, finished_at, error jsonb` | R0 |
| `task_executions` | `id, run_id, task (agent/service name), status, input_hash, output jsonb, error jsonb, started_at, finished_at` | R0 |
| `run_events` | `id bigserial, run_id, ts, level, type, message, data jsonb` | R0 |
| `checkpoints` | `id, run_id, name, payload jsonb, status enum(pending, approved, modified, rejected), decision jsonb, comment, decided_at` | R0 |
| `llm_usage` | `id, project_id, run_id null, task, provider, model, config_version, provisional bool, prompt_id, prompt_version, input_tokens, output_tokens, cached_tokens, cost_estimate numeric, created_at` | R1 |

## 4. Sources and provenance

| Table | Key columns | Rel. |
|---|---|---|
| `source_records` | `id, source enum, source_entity_id, endpoint, payload jsonb, payload_sha256, fetched_at, UNIQUE(source, source_entity_id, payload_sha256)` | R1 |
| `http_cache` | `key PK, source, url, status, headers jsonb, body, fetched_at, expires_at` | R1 |
| `search_queries` | `id, run_id, source, query_text, params jsonb, origin enum(user, planner, rule_expansion, latest_scan, gap_overlap_probe, gap_contradiction_probe, novelty_probe, monitor), rationale, status, result_count, total_available, cache_hit, error jsonb, executed_at` | R1 |
| `search_results` | `query_id, item_id (paper), rank, source_record_id, PK(query_id, item_id)` | R1 |

## 5. Papers, documents and evidence

| Table | Key columns | Rel. |
|---|---|---|
| `papers` | `id FK research_items, title, normalized_title (trgm index), abstract, abstract_status enum(available, unavailable, restricted), abstract_manifestation_id null, year, venue, publication_type, is_survey bool, is_open_access, language, fields_of_study text[], citation_counts jsonb ({source: {count, as_of}}), field_sources jsonb, metadata_level enum(stub, metadata, full_text), embedding vector(n) null, first_public_appearance timestamptz null (set only when date_confidence is verified or corroborated), first_public_basis enum(announced, posted, published_online, issue, issued, submission_only) null, first_public_precision enum(timestamp, day), first_public_manifestation_id null, first_public_event_id FK paper_dates null, candidate_public_date date null (best unconfirmed date, displayed only as "unconfirmed"), date_confidence enum(verified, corroborated, source_agreement, single_source, conflicting, uncertain) (D28)` — the **work** | R1 |
| `paper_manifestations` | `id, paper_id, kind enum(preprint, published, other), server_or_venue (arxiv, biorxiv, medrxiv, journal/proceedings name), primary_identifier_scheme, primary_identifier_value, peer_review_label enum(preprint_not_peer_reviewed, journal_version, unknown), url, license, is_open_access, created_from_source_record_id, created_at` — preprint and published versions stay distinct | R1 |
| `paper_dates` | `id, paper_id, manifestation_id FK paper_manifestations, event enum(preprint_submitted, preprint_announced, preprint_posted, version_submitted, version_announced, version_posted, accepted, published_online, issue_published, issued, reported_publication_date, index_created, metadata_updated, metadata_deposited, metadata_indexed, first_seen_by_researchpilot), value timestamptz (UTC; date-only values at 00:00 UTC with precision=day), precision enum(timestamp, day, month, year), version int null, is_primary bool (read directly from the system of record for this manifestation), reporting_source enum(arxiv_api, arxiv_announcement_feed, biorxiv_api, medrxiv_api, crossref, openalex, semantic_scholar, researchpilot), upstream_source enum(arxiv, biorxiv, medrxiv, crossref, pubmed, publisher, datacite, unknown) default unknown, upstream_evidence jsonb null (field path showing where the source got it; null if not exposed), source_record_id FK, retrieved_at, flags text[] (future_date, disagrees_with_primary, boundary_day)` — **one row per date event; never overwritten or deleted by matching; upstream provenance never guessed** | R1 |
| `paper_versions` | `paper_id, version int, submitted_at, source, source_record_id, PK(paper_id, version)` (arXiv versions) | R1 |
| `arxiv_announcement_log` | `id, category, arxiv_id, version, announce_type (new, cross, replace, replace_cross, as reported by the feed), announcement_day date, feed_fetched_at, source_record_id` — written by the daily capture job; produces `preprint_announced`/`version_announced` events when the paper is in the record | R1 |
| `paper_identifiers` | `paper_id, manifestation_id, scheme enum(doi, arxiv, s2_paper, s2_corpus, openalex, pmid, pmcid, dblp, acl), value, version, source, UNIQUE(scheme, value)` — **dedup guard** | R1 |
| `paper_merge_events` | `id, surviving_id, merged_id, match_decision_id FK paper_match_decisions, method enum(identifier, version_relation, evidence_rules, manual), created_at, reverted_at` — split restores identifiers and date claims by source record | R1 |
| `paper_match_decisions` | `id, paper_a, paper_b, relation enum(same_work, preprint_of, published_version_of, extended_version_of, erratum_of, comment_or_reply_of, unrelated), outcome enum(auto_match, possible_match, related_not_same, no_match), decided_by enum(system, user), user_status enum(pending, confirmed, rejected) null, confidence numeric, features jsonb (doi_match, arxiv_match, explicit_relation{source}, s2_both_ids, openalex_both_ids, title_sim, author_overlap, first_author_match, abstract_sim, date_order, venue_consistency, contradicting[]), rule_version, created_at, UNIQUE(paper_a, paper_b, rule_version)` — replaces `possible_duplicates`; user decisions are never overridden by re-matching (D29) | R1 |
| `authors` / `paper_authors` | `authors(id, display_name, normalized_name, orcid, s2_author_id, openalex_author_id)`; `paper_authors(paper_id, author_id, position, raw_name, raw_affiliations jsonb)` | R1 |
| `citations` | `citing_id, cited_id, sources text[], is_influential, intents text[], contexts jsonb, first_seen_run_id, PK(citing_id, cited_id)` | R1 |
| `paper_source_links` | `paper_id, source_record_id` | R1 |
| `documents` | `id, paper_id, manifestation_id, kind enum(pdf, tei, latex_source, plain_text), source_url, location_source enum(arxiv, s2_oa, openalex_oa, unpaywall, user_upload), license, version, sha256, storage_uri, page_count, retrieval_status enum(retrieved, unavailable, failed), failure_reason enum(no_oa_location, http_error, not_a_pdf, too_large, parse_failed, scanned_pdf, license_restricted, timeout, budget_exhausted), failure_detail, parser, retrieved_at` | R1 |
| `document_sections` | `id, document_id, ordinal, parent_id, heading, section_type enum, page_start, page_end, text, char_offset_start` | R1 |
| `chunks` | `id, section_id, ordinal, text, page, char_start, char_end, embedding vector(n)` | R1 |
| `evidence_spans` | `id, paper_id, manifestation_id null (which version the text comes from), document_id null, section_id null, location_kind enum(abstract, body_text, table, figure_caption, metadata, latex_source), page, char_start, char_end, bbox jsonb, quote, verification enum(exact, fuzzy, unverified), created_by` | R1 |
| `equations` | `id, paper_id, document_id, section_id, label, latex, context_text, source enum(arxiv_latex, grobid, user_selection), page, evidence_span_id` | R2 |

## 6. Research Intelligence Engine

| Table | Key columns | Rel. |
|---|---|---|
| `assessments` | `id, item_id, objective_id, tier enum(essential, recommended, optional, not_useful, insufficient_information), priority_score, dimensions jsonb ({dimension: {score, coverage, confidence, band}}), role_tags text[], stage enum(a_quick, b_detailed), signals_hash, weights_version, status enum(current, stale), computed_at, UNIQUE(item_id, objective_id)` | R1 |
| `assessment_history` | append-only copy of previous assessment rows (to show "tier changed") | R1 |
| `assessment_signals` | `id, assessment_id, key, family enum(semantic_match, citation_structure, content_extraction, resource_availability, llm_judgement, user, currency), dimension, value numeric null, raw jsonb, method enum(deterministic, llm_judgement, external_metadata, user), evidence jsonb, version, computed_at` | R1 |
| `relevance_judgements` | `id, item_id, objective_id, sub_question_key, label enum(direct, partial, tangential, not_relevant), quote_span_id, explanation, model, prompt_version, cross_check_of null, agreement enum(agree, disagree) null` — assessment data; any graph link it implies (ADDRESSES/CONTRADICTS/RELATED_TO) is a `research_relations` row referenced by `relation_uid null` | R1 |
| `recommendation_cards` | `id, assessment_id, level, content jsonb (six fields; statements reference claim ids), prompt_version, model, input_hash, status enum(current, stale), created_at, UNIQUE(assessment_id, level, prompt_version, input_hash)` | R1 |
| `overrides` | `id, project_id, item_id, objective_id, field enum(tier, role_tag, dimension, sub_question_relevance, use_case, inclusion), system_value jsonb, user_value jsonb, reason_code enum(wrong_topic, too_basic, already_known, low_quality, important_for_me, other) null, reason_text, active bool, created_at` | R1 |
| `feedback` | `id, project_id, target enum(card, statement, explanation, assessment, missing_item), target_id, kind enum(helpful, not_helpful, wrong, unclear, missing), comment, created_at, resolved_at` | R1 |
| `objective_suggestions` | `id, objective_id, suggestion jsonb, basis jsonb (override ids), status enum(pending, accepted, dismissed)` | R1 |

## 7. Claims and verification

| Table | Key columns | Rel. |
|---|---|---|
| `claims` | `id, project_id, kind enum(reported_finding, extracted_observation, ai_interpretation, unverified_hypothesis), grounding enum(grounded, background) null (required for ai_interpretation), text, created_by, origin_type enum(card, explanation, comparison, gap, idea, report), origin_id, status enum(active, hidden_pending_review, superseded, rejected)` | R1 |
| `claim_evidence` | `claim_id, evidence_span_id null, item_id null, signal_id null, relation enum(supports, contradicts, context), CHECK (at least one reference)` | R1 |
| `claim_verifications` | `id, claim_id, level enum(quote_verified, data_derived, metadata_confirmed, cross_checked, unverified), result enum(pass, fail), details jsonb, checked_at` | R1 |

## 8. Learning

| Table | Key columns | Rel. |
|---|---|---|
| `explanations` | `id, style enum(intuitive, step_by_step, technical, mathematical, practical_example, code, comparison) default intuitive, subject enum(item, section, equation, project_topic), item_id null, section_id null, equation_id null, project_id null, level, content jsonb (blocks referencing claim ids), model, prompt_version, input_hash, status, created_at`, CHECK exactly one subject reference, UNIQUE(subject reference, level, style, prompt_version, input_hash) — the cache for Ask & Learn "canonical asks" | R1 |
| `glossary_terms` | `id, project_id, entity_id (term/concept), salience, first_paper_id` | R1 |
| `concept_prerequisites` | `concept_id, prerequisite_id, basis enum(ai_interpretation, paper_evidence), evidence_span_id null, confidence` — **learning data**; not part of the research knowledge graph | R1 |
| `learning_paths` / `learning_path_items` | `paths(id, project_id, objective_id, level, version)`; `items(path_id, ordinal, item_type enum(concept, paper, section, exercise), item_id null, section_id null, exercise_id null, rationale, status enum(todo, done, skipped))` | R1 |
| `tutor_conversations` | `id, project_id, title, anchor_item_id null, anchor_section_id null, anchor_equation_id null, anchor_selection jsonb null (text + page + document), level, ephemeral bool (retention policy do_not_store), expires_at null (from retention policy), created_at, updated_at` | R1 |
| `tutor_messages` | `id, conversation_id ON DELETE CASCADE, ordinal, role enum(user, assistant), text (user) / content jsonb (assistant: blocks referencing claim ids), level, style, intent enum(ask, simpler, deeper, example, step_by_step, show_math, compare, implement, prerequisites, lesson_step, check_answer), scope enum(about_this_paper, about_project, general), view_context jsonb, answer_status enum(grounded, partially_grounded, background_only, not_found_in_sources, out_of_scope, error), teaching_session_id null, teaching_step enum(intuition, simple_example, technical, mathematical, algorithmic, paper_connection, implementation, understanding_check) null, missing_prerequisites jsonb, explanation_id null (served from cache), model, prompt_version, created_at` | R1 |
| `tutor_message_evidence` | `message_id, handle (E1…), evidence_span_id null, chunk_id null, equation_id null, item_id null, retrieval_rank, retrieval_score, used bool` | R1 |
| `conversation_summaries` | `id, conversation_id ON DELETE CASCADE, through_ordinal, summary_text (kind = ai_summary; context only, never evidence), carried_refs jsonb {evidence_span_ids, chunk_ids, equation_ids, item_ids, saved_explanation_ids, concepts_covered, open_questions}, model, prompt_version, created_at` | R1 |
| `teaching_sessions` | `id, project_id, conversation_id null ON DELETE SET NULL, concept_item_id null, anchor_item_id null, anchor_section_id null, level, plan jsonb (ordered steps with status pending/shown/skipped and skip reason), current_step, status enum(active, completed, stopped), created_at, updated_at` | R1 |
| `understanding_checks` | `id, teaching_session_id, concept_item_id, question jsonb (type mcq/short_answer, options, answer key, grounding claim ids), user_answer null, result enum(correct, partially_correct, incorrect, skipped) null, graded_by enum(deterministic, ai), created_at` — kept as learning progress | R1 |
| `concept_progress` | `project_id, concept_item_id, steps_seen text[], highest_level_reached, checks_attempted int, last_check_result, status enum(not_started, in_progress, understood_self_reported, check_passed, needs_review), updated_at, PK(project_id, concept_item_id)` — **project-level; independent of conversations** | R1 |
| `saved_explanations` | `id, project_id, title, item_id null, section_id null, concept_item_id null, content jsonb (copied answer blocks), claim ids (copied claims owned by this row), evidence refs, level, style, source_message_id null ON DELETE SET NULL, created_at` — independent copy; survives conversation deletion | R1 |
| `exercises` | `id, project_id, item_id, level, language, prompt, starter_code, solution, expected_output, verification_status enum(not_run, passed, failed)` | R2 |

## 9. Field map

| Table | Key columns | Rel. |
|---|---|---|
| `research_directions` | `id, project_id, run_id, label, label_method enum(keyword, llm), description, basis jsonb (algorithm, params, seed), stale bool` | R1 |
| *(folded)* | Direction membership is stored as `research_relations` rows: `RELATED_TO` with `basis = direction_membership` and `membership_score` in `properties` (single-source rule, ARCHITECTURE §12.4) | R1 |
| `direction_relations` | `direction_a, direction_b, relation enum(cites, shares_methods, shares_datasets), weight, signal jsonb` — **derived analytics** for the field map, recomputed from the record; **not a relationship source and never projected** to the graph (ARCHITECTURE §12.4.3) | R1 (cites) / R2 (others) |
| `taxonomy_nodes` | `id, project_id, parent_id, label, definition, entity_ids uuid[]` — **derived view** for the comparison UI; not projected (a future registry entry would use `structural_relations`) | R2 |

## 10. Entities and extractions

| Table | Key columns | Rel. |
|---|---|---|
| `entities` | `id FK research_items, type (= item_type), canonical_name, aliases text[], description, UNIQUE(type, canonical_name)` | R1 (concept, term) / R2 (others) |
| `dataset_details` | `entity_id, modality, size_text, license, license_source, hf_dataset_id, homepage, access enum(open, registration, restricted, unknown), fetched_at` | R2 |
| `model_details` | `entity_id, hf_model_id, parameters, license, license_source, base_model, fetched_at` | R4 |
| `metric_details` | `entity_id, definition_text, higher_is_better, range, evidence_span_id` | R2 |
| `entity_links` | `id, subject_uid, subject_kind enum(paper, method, proposal, experiment), entity_id, role enum(introduces, uses_method, evaluates_on, compares_against, reports_metric), manifestation_id null, extraction_run_id` + common relationship columns, UNIQUE(subject_uid, entity_id, role, scope_project_id). Replaces `paper_entity_mentions`. Graph types: introduces → INTRODUCES, uses_method → USES_METHOD, evaluates_on → EVALUATES_ON; `compares_against` and `reports_metric` are RIE data and are not projected | R2 (term/concept mentions: R1) |
| `paper_contributions` | `id, paper_id, type, summary, evidence_span_id NOT NULL` — node data for the Paper (not a relationship source) | R2 |
| `reported_results` | `id, value numeric null, value_text, unit, split, setting, is_own_method, evidence_span_id NOT NULL` — values and evidence only. The paper, method, dataset/benchmark and metric are `RESULT_FOR` rows in `structural_relations` (roles `reported_in`, `method`, `dataset`/`benchmark`, `metric`; cardinality enforced at commit). Read paths use the view `result_dimensions_v` (derived, not a source) | R2 |
| `limitations` | `id, paper_id, text, category, stated_by enum(authors, inferred), evidence_span_id NOT NULL` | R2 |
| `assumptions` | `id, paper_id, text, evidence_span_id NOT NULL` | R2 |
| `experimental_protocols` | `id, paper_id (owner), entity_link_ids uuid[] (references to the paper's `evaluates_on` / `compares_against` rows in `entity_links`), split, hyperparameters jsonb, evidence_span_ids uuid[]` — protocol details only; dataset and baseline links live solely in `entity_links` | R2 |
| `compute_reports` | `id, paper_id, hardware, quantity, duration_text, evidence_span_id NOT NULL` | R2 |
| *(folded)* | Paper-to-paper relations are `research_relations` rows: `EXTENDS` (`subtype` improves_on/extends), `CONTRADICTS`, or `RELATED_TO` (`basis` reproduces/compares_with) | R2 |

## 11. Implementations

| Table | Key columns | Rel. |
|---|---|---|
| `code_repositories` | `id FK research_items, host, owner, name, url, stars, license, last_pushed_at, archived, has_dependency_file, fetched_at` | R4 (URLs found in papers stored as unresolved links from R2) |
| `item_code_links` | `item_id (paper/method/model), repo_id, link_source enum(paper_text, hf_paper_page, readme_mentions_paper, name_search, manual), is_official bool null, evidence_span_id null` | R4 |

## 12. Gaps, ideas, experiments

| Table | Key columns | Rel. |
|---|---|---|
| `gaps` | `id FK research_items, project_id, kind enum(recurring_limitation, sparse_intersection, conflicting_results, missing_evaluation, user_defined), description, signal jsonb (computed numbers only; links to limitations/papers are `DERIVED_FROM` rows in `research_relations`), status enum(candidate, probed, open, partially_addressed, addressed, rejected)` | R3 |
| `gap_probes` | `id, gap_id, probe_kind enum(overlap, contradiction), query_ids uuid[], outcome enum(no_close_match, partial_overlap, already_addressed, contradicting_evidence, none_found), match_relation_uids uuid[] (the `ADDRESSES`/`CONTRADICTS` rows created in `research_relations`), probed_at` | R3 |
| `limitation_clusters` | `id, project_id, label, distinct_paper_count, distinct_group_count` — membership is `RELATED_TO` (`basis = cluster_membership`) in `research_relations` | R3 |
| `ideas` | `id FK research_items, project_id, statement, rationale, expected_outcome, falsification_criteria, version, system_status enum(draft, under_review, survived, revised, rejected), user_status enum(proposed, shortlisted, accepted, rejected, parked), user_reason` — the source gap is a `DERIVED_FROM` row in `research_relations` (exactly one active, enforced by trigger) | R3 |
| `novelty_checks` | `id, idea_id, query_ids, sources, nearest jsonb, result enum(no_close_match_found, similar_work_found, inconclusive), checked_at` | R3 |
| `red_team_reviews` | `id, idea_id, verdict enum(survives, needs_revision, reject), objections jsonb (type, argument, evidence ids, resolved bool), counter_evidence_ids uuid[]` | R3 |
| `experiment_plans` | `id, report_id (the proposal), protocol jsonb, ablations jsonb, compute_estimate jsonb (with basis), risks jsonb` — datasets, metrics and baselines are `entity_links` rows (subject = the proposal); the hypothesis link is `DERIVED_FROM` in `research_relations` | R4 |
| `experiments` | `id, project_id, title, status enum(planned, running, done, abandoned), notes, created_at` — the proposal it belongs to is `PART_OF` in `structural_relations` (detach on delete); the hypothesis tested is an `ADDRESSES` row in `research_relations` | R4 |
| `experiment_results` | `id, value, setting, kind = 'user_reported'` — the experiment (`PART_OF`, cascade) and the metric/dataset (`RESULT_FOR`) are rows in `structural_relations` | R4 |

## 13. Persistence, reports and events

| Table | Key columns | Rel. |
|---|---|---|
| `project_items` | `project_id, item_id, inclusion enum(candidate, included, excluded), exclusion_reason, dismissed_at null, dismiss_reason null, discovered_via enum(search, reference, citation, recommendation, manual, probe, latest_scan, monitor), discovered_in_run_id, discovered_from_item_id, reading_status enum(unread, to_read, reading, read, skipped), last_section_id, is_saved, tags text[], first_seen_at, PK(project_id, item_id)` | R1 |
| `notes` | `id, project_id, item_id null, section_id null, saved_explanation_id null, body, created_at` (user-written notes; saved tutor answers live in `saved_explanations`) | R1 |
| `decisions` | `id, project_id, item_id null, type enum(inclusion, override, idea_status, objective_change, other), summary, rationale, ref_id, created_at` | R1 |
| `reports` | `id, project_id, run_id, type enum(discovery, literature_review, proposal), version, content jsonb, rendered_markdown, item_set_hash, created_at` | R1 |
| `domain_events` | `id bigserial, type, item_id null, project_id null, payload jsonb, created_at, processed_at, attempts` | R0 |
| `monitors` | `id, project_id, schedule, query_ids, last_run_at, enabled` | R5 |
| `impact_alerts` | `id, project_id, new_item_id, target_item_id (gap/idea/experiment-linked idea), judgement jsonb, evidence_span_ids, status enum(new, dismissed, acknowledged), created_at` | R5 |

## 13a. Latest Research

| Table | Key columns | Rel. |
|---|---|---|
| `latest_scans` | `id, project_id, run_id, objective_id, window_start, window_end (UTC), fetch_start (window_start − 3 days overlap), display_timezone (for the digest text), sources text[] (incl. biorxiv, medrxiv when enabled), arxiv_categories text[], biorxiv_categories text[], openalex_capabilities text[] (basic \| premium_filters), status, coverage jsonb (per source: queried, returned, failed, budget_exhausted), counts jsonb (by release type, tier, action), created_at` | R1 |
| `latest_scan_entries` | `scan_id, paper_id, release_type enum(new_preprint, new_publication, published_version_of_preprint, revised_version, newly_indexed_older, date_uncertain), release_event_date, release_event_claim_id FK paper_dates, date_confidence (snapshot), public_date_basis (snapshot, e.g. submission_only), manifestation_id (the manifestation whose event placed it in the window), peer_review_label (snapshot), boundary_day bool, sub_question_keys text[], direction_ids uuid[], matched_query_ids uuid[], related_item_ids jsonb (snapshot: [{item_id, link: cites \| similar, relation_uid}]), relation_to_project jsonb (snapshot referencing `research_relations` uids), brief jsonb (eight answers, each referencing claim ids or a "can't tell" reason), action enum(read_now, save_for_later, deprioritise, check_manually), action_reason, first_seen_in_scan bool, PK(scan_id, paper_id)` | R1 |
| `latest_views` | `project_id, user_id, last_viewed_at` (for "new since last visit") | R1 |

User actions on entries (save, dismiss, read later, notes, overrides) are
stored in the shared tables (`project_items`, `notes`, `overrides`), not on
the scan. A paper's state is therefore consistent everywhere in the app.

## 14. Indexes and constraints (main ones)

- `paper_identifiers(scheme, value)` UNIQUE (dedup).
- `papers.normalized_title` GIN trigram; `papers(year)`, `papers(publication_date)`.
- `papers.embedding` and `chunks.embedding`: HNSW (pgvector).
- Full-text search: generated `tsvector` on title and abstract, GIN index.
- `assessments(objective_id, tier)`, `assessments(status)`.
- `overrides(item_id, objective_id) WHERE active`.
- `project_items(project_id, inclusion)`, `(project_id, reading_status)`.
- `citations(cited_id)`; `evidence_spans(paper_id)`;
  `structural_relations(parent_uid, type, role)` (benchmark lookups by dataset/metric).
- `domain_events(processed_at) WHERE processed_at IS NULL`.
- `paper_dates(paper_id, event)`, `paper_dates(manifestation_id)`; `papers(first_public_appearance)`; `paper_manifestations(paper_id, kind)`; `arxiv_announcement_log(arxiv_id, announcement_day)`.
- `latest_scan_entries(scan_id, release_type)`; `latest_scans(project_id, created_at DESC)`.
- `tutor_messages(conversation_id, ordinal)`; `tutor_conversations(project_id, updated_at DESC)`.
- `papers.first_public_appearance` is only ever set together with `first_public_event_id`, and only when `date_confidence ∈ (verified, corroborated)`. For `verified` the event must have `is_primary = true`. For `corroborated` there must be a second event within ±1 day whose `upstream_source` is known and differs (independence established). Enforced by a trigger. Agreement between sources with unknown or shared upstream provenance is `source_agreement`, never `corroborated`.
- `first_public_basis = submission_only` is allowed only for arXiv works without a captured announcement event; the UI must render its meaning.
- `paper_dates.event` values `preprint_submitted`, `accepted`, `index_created` and `metadata_*` can never be the `first_public_event_id`.
- `paper_match_decisions` with `decided_by = user` cannot be updated by the system.
- Retention: `tutor_messages` and `conversation_summaries` cascade on conversation delete; `saved_explanations`, `concept_progress` and `understanding_checks` do not.
- `concept_progress(project_id, status)`; `saved_explanations(project_id, created_at DESC)`; `tutor_conversations(expires_at) WHERE expires_at IS NOT NULL`.

## 15. Data retention and reproducibility

- Raw source records and run manifests are kept for the lifetime of the
  project.
- Deletions propagate to the Neo4j graph via `entity_tombstones` (§16); the
  graph never retains data deleted from PostgreSQL. Matching and merging never delete source records or date claims.
- Tutor conversations follow the project retention policy
  (`tutor_retention_policy`). A daily job deletes expired conversations.
  Saved explanations and learning progress are retained until deleted or
  reset explicitly.
- Reports, assessments history and objective versions are append-only.
- Embedding model name and version are stored per vector column version;
  changing models triggers a re-embed job and never mixes vectors.

## 16. Knowledge-graph readiness (R0–R1) and Neo4j sync (R2+)

PostgreSQL is the source of truth for everything that appears in the Neo4j
knowledge graph (ARCHITECTURE §12). These conventions make every table
graph-ready from R0, so Neo4j can be added in R2 without changing models.

### 16.1 Conventions for all graph-projected tables
- **Stable IDs:** UUIDv7 primary keys. The same UUID becomes the Neo4j
  `uid`. Composite-key link tables (e.g. `citations`, `paper_authors`)
  also get a `relation_uid uuid` column holding a
  deterministic UUIDv5 of `(relation_type, table, from_uid, to_uid,
  qualifier)`.
- **`row_version bigint not null default 1`**, incremented by trigger on
  every update. Used for idempotent, version-guarded sync.
- **Relationship tables** (the only sources of research relationships, one
  per type; ARCHITECTURE §12.4): `citations` (CITES), `paper_authors`
  (AUTHORED_BY), `author_affiliations` (AFFILIATED_WITH), `entity_links`
  (INTRODUCES, USES_METHOD, EVALUATES_ON), `limitations`
  (REPORTS_LIMITATION), `research_relations` (EXTENDS, CONTRADICTS,
  RELATED_TO, ADDRESSES, DERIVED_FROM, VALIDATED_BY), and from R4
  `item_code_links` (IMPLEMENTED_BY).
- **Structural relationship sources** (one per type, `assertion =
  structural`, no evidence): `paper_manifestations.paper_id` (HAS_VERSION),
  `project_items` (IN_PROJECT), and `structural_relations` (PART_OF,
  RESULT_FOR, and nothing else).
- **Not relationship sources:** access-control scope columns
  (`project_id`, `scope_project_id`), derived pointers, node data, derived
  analytics (`direction_relations`), learning data, decision logs, snapshots
  and project memory (full list: ARCHITECTURE §12.4.3).
- **Project-scope invariant** (ARCHITECTURE §12.4.2a): the trigger
  `enforce_relation_scope()` is attached to every relationship source table
  and rejects relationships that connect different projects' nodes, carry a
  scope different from their project-scoped endpoint, or are global (`null`)
  while touching a project-scoped node or produced in a project context.
  Global-only tables (`citations`, `paper_authors`, `author_affiliations`,
  `limitations`) also have `CHECK (scope_project_id IS NULL)`.
  `scope_project_id` references `projects(id) ON DELETE CASCADE` everywhere.
- **Common relationship columns** on every **research** relationship table listed above (structural sources carry only `assertion = structural`, scope and `row_version`):
  - `assertion enum(source_metadata, author_reported, extracted, computed, inferred, hypothesized, user_asserted, user_confirmed, rejected, structural)`
  - `confidence numeric null`
  - `evidence jsonb` (evidence span IDs with manifestation, source record IDs, signal IDs)
  - `provenance jsonb` (service/agent + version, prompt version, task/provider/model, source API)
  - `scope_project_id uuid null` (null = global)
  - `status enum(active, retracted) default active`
  - `row_version`
- Promotions of `assertion` (inferred → extracted after quote verification;
  inferred → user_confirmed) and rejections are written to
  `relation_assertion_log`.
- **Evidence by assertion** (CHECK constraints + trigger): `source_metadata`
  requires a source record ID; `author_reported` and `extracted` require
  ≥ 1 verified evidence span; `computed` requires a signal/computation
  reference; `inferred` requires confidence, ≥ 1 evidence reference and the
  producing task/model; `hypothesized` requires the source gap/evidence;
  user assertions require actor and time; `structural` requires none
  (ARCHITECTURE §12.5).
- **Single write path and sticky rejection:** all inserts and updates go
  through `RelationWriter`. Each relationship table has a unique natural
  key. A trigger forbids changing a row *from* `rejected` except by a
  user action, and automatic writes that hit a rejected row become logged
  no-ops. Fuzzy re-creation is blocked by `relation_suppressions`.

### 16.2 New tables

| Table | Key columns | Rel. |
|---|---|---|
| `graph_nodes` | `uid PK, kind (node label), scope_project_id null FK projects ON DELETE CASCADE, UNIQUE(uid, kind)` — node identity registry. Rows are written only by the registration triggers of tables in `node_source_registry`, under their conditions; `scope_project_id` equals the source row's project (null for global) and is **immutable** (trigger) | R0 |
| `node_source_registry` | `source_table PK, label, registration_condition, scope_rule enum(global, own_project_id, parent_project), introduced_in` — the complete node-source inventory (§16.3, ARCHITECTURE §12.3). Conditions: reports only where type is proposal; entities only where type is not term. Tables not listed (e.g. `experiment_plans`) have no registration trigger | R0 |
| `relation_registry` | `type PK, class enum(research, structural), source_table, source_column null, projected bool, required_evidence_policy, introduced_in` — exactly one row per type, so a type cannot have two sources (UNIQUE on `type`); mirrored by the code registry and checked against it in CI | R1 |
| `relation_endpoint_rules` | `type FK relation_registry, from_kind, to_kind, role null, cardinality (e.g. exactly_one_per_child), on_parent_delete enum(cascade_child, detach), PK(type, from_kind, to_kind, role)` | R1 |
| `structural_relations` | `id (uid), type enum(PART_OF, RESULT_FOR)` (**only these two**; CHECK + registry), `child_uid, child_kind, parent_uid, parent_kind` (composite FKs to `graph_nodes(uid, kind)`), `role null` (RESULT_FOR: reported_in, method, dataset, benchmark, metric), `assertion = structural` (CHECK), `scope_project_id null, row_version, created_at, UNIQUE(type, child_uid, parent_uid, role)` — the only owner of PART_OF and RESULT_FOR; endpoint, cardinality and delete rules from `relation_endpoint_rules` | R1 (PART_OF for sub-questions) / R2 (results) / R4 (experiments) |
| `research_relations` | `id (uid), type enum(EXTENDS, CONTRADICTS, RELATED_TO, ADDRESSES, DERIVED_FROM, VALIDATED_BY)` (**only these six types**; CHECK constraint), `from_uid, from_kind, to_uid, to_kind` (composite FKs to `graph_nodes(uid, kind)`; allowed combinations in `relation_endpoint_rules`), properties jsonb (e.g. subtype, basis, outcome, membership_score, qualifier), assertion, confidence, evidence, provenance, scope_project_id, status, row_version, created_at, updated_at, UNIQUE(type, from_uid, to_uid, (properties->>'qualifier'), scope_project_id)` — the single source for these six types (including direction membership, paper-to-paper relations, relevance-judge relations to project items, gap probe matches, hypothesis/proposal/experiment links) | R1 |
| `relation_assertion_log` | `id, relation_table, relation_id, from_assertion, to_assertion, reason (quote_verified, user_confirmed, user_rejected, source_retracted), actor (service or user), created_at` | R1 |
| `relation_suppressions` | `id, type, from_uid, to_uid null, fingerprint (hash of evidence span or normalised text; no content stored), scope_project_id, reason, created_by (user), created_at` — prevents rejected relationships from being re-created in a slightly different form | R1 |
| `relation_decisions` | `id, scope_project_id NOT NULL FK projects ON DELETE CASCADE, relation_table, relation_uid, decision enum(confirmed, rejected), decided_by (user), decided_at, UNIQUE(scope_project_id, relation_uid)` — project-scoped overlays for user decisions on **global** relationships (not a relationship source: no endpoints); applied by `GraphService` for that project only | R1 |
| `research_groups` | `id, display_name, ror_id null, openalex_institution_id null, country null, kind enum(institution, lab, consortium, unknown), source, source_record_id, row_version` | R1 |
| `author_affiliations` | `id, author_id, group_id, paper_id null, raw_affiliation, period jsonb null` + common relationship columns (assertion usually `source_metadata`) | R1 |
| `entity_tombstones` | `uid (opaque UUID or one-way UUIDv5), kind (label or relationship type), reason enum(user_delete, retention, project_delete, account_delete, merge_split, retracted, rejected), deleted_at, graph_removed_at null, verified_absent_at null, attempts, purge_after (= min(verified_absent_at, deleted_at + 30 days))` — **minimum metadata only**: no content, names, text, endpoint IDs, project IDs or user IDs; purged when verified absent from Neo4j or after 30 days (alert if unverified); see ARCHITECTURE §12.6a | R1 (written from R1; consumed from R2) |
| `graph_sync_state` | `uid, kind, pg_version, synced_version, status enum(pending, synced, failed, ineligible), attempts, last_error, last_synced_at, PK(uid)` | R2 |
| `graph_sync_runs` | `id, kind enum(incremental, reconciliation, rebuild), started_at, finished_at, graph_version, counts jsonb, mismatches jsonb, repaired jsonb, status` | R2 |
| `graph_dead_letters` | `id, uid, kind, event_id, error, attempts, created_at, resolved_at` | R2 |
| `graph_query_log` | `id, project_id, template_name, params_hash, assertion_policy, backend enum(postgres, neo4j), graph_version, result_count, created_at` — makes graph-derived signals reproducible (R3) | R2 |

### 16.3 Node sources (inventory)
Exactly these tables register rows in `graph_nodes`, under the stated
condition (mirrored in `node_source_registry`; ARCHITECTURE §12.3):

| Source table | Condition | Scope |
|---|---|---|
| `projects`, `research_objectives`, `objective_sub_questions`, `research_directions`, `limitation_clusters`, `gaps`, `ideas`, `experiments`, `experiment_results` | always | project (own or parent's) |
| `papers`, `paper_manifestations`, `authors`, `research_groups`, `limitations`, `reported_results`, `code_repositories` | always | global |
| `entities` | type ≠ `term` | global |
| `reports` | `type = 'proposal'` | project |

**Not node sources:** `experiment_plans` (node data of its Proposal,
projected as Proposal properties), glossary terms, non-proposal reports, and
every other table. They have no registration trigger.

### 16.4 Eligibility for sync (validated records only)
A row is projected only when: it comes from the registered single source
for its type (snapshots are never sources); its `status` is `active`; its
`assertion` is not `rejected` (rejected rows and suppressed fingerprints are
never projected, so resync and rebuild cannot resurrect them; project
`relation_decisions` overlays are never projected and are applied at query
time; rows violating the project-scope invariant are refused and alerted); extracted relationships have verified evidence; matches are
not `possible_match`; and claims are not hidden pending review. In R2 only
established assertions are eligible (`source_metadata`, `author_reported`,
`extracted`, `computed`, `user_asserted`, `user_confirmed`, `structural`).
`inferred` and `hypothesized` become eligible in R3, and are always
labelled.
