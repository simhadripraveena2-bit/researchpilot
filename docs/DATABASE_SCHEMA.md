# Database Schema

**Status:** canonical. It consolidates `docs/plan/03` and
`docs/plan/11 §11.6`, adding the Research Intelligence Engine tables and
the `research_items` supertype.

PostgreSQL 16 with `pgvector` and `pg_trgm`. Conventions: UUIDv7 primary keys;
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
   │             model, task, concept, term) ─ *_details, paper_entity_mentions
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
domain_events (outbox)
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
| `deletion_log` | `id, user_id, project_id null, scope enum(conversation, all_conversations, learning_progress, project, account, retention_expiry), object_counts jsonb, requested_at, completed_at` (no content) | R1 |
| `projects` | `id, user_id, title, topic, expertise_level enum, goal enum(learn_field, review_literature, find_gap, plan_experiment, write_proposal, track_field), settings jsonb (incl. enabled sources such as bioRxiv/medRxiv), tutor_retention_policy enum(keep_until_deleted, delete_after_days, do_not_store) default keep_until_deleted, tutor_retention_days int null, status` | R0 |
| `research_objectives` | `id, project_id, version int, core_question, target_tasks text[], focus_concepts text[], exclusions text[], constraints jsonb, expertise_level, goal, source enum(planner, user_edit, feedback_suggestion), created_at, UNIQUE(project_id, version)` | R1 |
| `objective_sub_questions` | `id, objective_id, key text (SQ1…), text, ordinal` | R1 |
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
| `relevance_judgements` | `id, item_id, objective_id, sub_question_key, label enum(direct, partial, tangential, not_relevant), quote_span_id, explanation, model, prompt_version, cross_check_of null, agreement enum(agree, disagree) null` | R1 |
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
| `concept_prerequisites` | `concept_id, prerequisite_id, basis enum(ai_interpretation, paper_evidence), evidence_span_id null, confidence` | R1 |
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
| `direction_members` | `direction_id, paper_id, membership_score` | R1 |
| `direction_relations` | `direction_a, direction_b, relation enum(cites, shares_methods, shares_datasets), weight, signal jsonb` | R1 (cites) / R2 (others) |
| `taxonomy_nodes` | `id, project_id, parent_id, label, definition, entity_ids uuid[]` | R2 |

## 10. Entities and extractions

| Table | Key columns | Rel. |
|---|---|---|
| `entities` | `id FK research_items, type (= item_type), canonical_name, aliases text[], description, UNIQUE(type, canonical_name)` | R1 (concept, term) / R2 (others) |
| `dataset_details` | `entity_id, modality, size_text, license, license_source, hf_dataset_id, homepage, access enum(open, registration, restricted, unknown), fetched_at` | R2 |
| `model_details` | `entity_id, hf_model_id, parameters, license, license_source, base_model, fetched_at` | R4 |
| `metric_details` | `entity_id, definition_text, higher_is_better, range, evidence_span_id` | R2 |
| `paper_entity_mentions` | `id, paper_id, entity_id, role enum(proposes, uses, compares_against, evaluates_on, reports_metric, extends, defines), evidence_span_id NOT NULL, extraction_run_id, confidence` | R2 (terms: R1) |
| `paper_contributions` | `id, paper_id, type, summary, evidence_span_id NOT NULL` | R2 |
| `reported_results` | `id, paper_id, method_id, dataset_id, metric_id, value, value_text, unit, split, setting, is_own_method, evidence_span_id NOT NULL` | R2 |
| `limitations` | `id, paper_id, text, category, stated_by enum(authors, inferred), evidence_span_id NOT NULL` | R2 |
| `assumptions` | `id, paper_id, text, evidence_span_id NOT NULL` | R2 |
| `experimental_protocols` | `id, paper_id, dataset_id, split, baselines uuid[], hyperparameters jsonb, evidence_span_ids uuid[]` | R2 |
| `compute_reports` | `id, paper_id, hardware, quantity, duration_text, evidence_span_id NOT NULL` | R2 |
| `paper_relations` | `from_paper_id, to_paper_id, relation enum(improves_on, extends, contradicts, reproduces, compares_with), basis jsonb, evidence_span_ids uuid[]` | R2 |

## 11. Implementations

| Table | Key columns | Rel. |
|---|---|---|
| `code_repositories` | `id FK research_items, host, owner, name, url, stars, license, last_pushed_at, archived, has_dependency_file, fetched_at` | R4 (URLs found in papers stored as unresolved links from R2) |
| `item_code_links` | `item_id (paper/method/model), repo_id, link_source enum(paper_text, hf_paper_page, readme_mentions_paper, name_search, manual), is_official bool null, evidence_span_id null` | R4 |

## 12. Gaps, ideas, experiments

| Table | Key columns | Rel. |
|---|---|---|
| `gaps` | `id FK research_items, project_id, kind enum(recurring_limitation, sparse_intersection, conflicting_results, missing_evaluation, user_defined), description, signal jsonb, status enum(candidate, probed, open, partially_addressed, addressed, rejected)` | R3 |
| `gap_probes` | `id, gap_id, probe_kind enum(overlap, contradiction), query_ids uuid[], outcome enum(no_close_match, partial_overlap, already_addressed, contradicting_evidence, none_found), matches jsonb (item ids + quote span ids), probed_at` | R3 |
| `limitation_clusters` | `id, project_id, label, limitation_ids uuid[], distinct_paper_count, distinct_group_count` | R3 |
| `ideas` | `id FK research_items, project_id, gap_id, statement, rationale, expected_outcome, falsification_criteria, version, system_status enum(draft, under_review, survived, revised, rejected), user_status enum(proposed, shortlisted, accepted, rejected, parked), user_reason` | R3 |
| `novelty_checks` | `id, idea_id, query_ids, sources, nearest jsonb, result enum(no_close_match_found, similar_work_found, inconclusive), checked_at` | R3 |
| `red_team_reviews` | `id, idea_id, verdict enum(survives, needs_revision, reject), objections jsonb (type, argument, evidence ids, resolved bool), counter_evidence_ids uuid[]` | R3 |
| `experiment_plans` | `id, idea_id, datasets uuid[], metrics uuid[], baselines uuid[], protocol jsonb, ablations jsonb, compute_estimate jsonb (with basis), risks jsonb` | R4 |
| `experiments` | `id, project_id, idea_id null, plan_id null, title, status enum(planned, running, done, abandoned), notes, created_at` | R4 |
| `experiment_results` | `id, experiment_id, metric_id, dataset_id, value, setting, kind = 'user_reported'` | R4 |

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
| `latest_scan_entries` | `scan_id, paper_id, release_type enum(new_preprint, new_publication, published_version_of_preprint, revised_version, newly_indexed_older, date_uncertain), release_event_date, release_event_claim_id FK paper_dates, date_confidence (snapshot), public_date_basis (snapshot, e.g. submission_only), manifestation_id (the manifestation whose event placed it in the window), peer_review_label (snapshot), boundary_day bool, sub_question_keys text[], direction_ids uuid[], matched_query_ids uuid[], related_item_ids jsonb ([{item_id, link: cites \| similar, score}]), relation_to_project jsonb, brief jsonb (eight answers, each referencing claim ids or a "can't tell" reason), action enum(read_now, save_for_later, deprioritise, check_manually), action_reason, first_seen_in_scan bool, PK(scan_id, paper_id)` | R1 |
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
  `reported_results(dataset_id, metric_id)`.
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
  project. Matching and merging never delete source records or date claims.
- Tutor conversations follow the project retention policy
  (`tutor_retention_policy`). A daily job deletes expired conversations.
  Saved explanations and learning progress are retained until deleted or
  reset explicitly.
- Reports, assessments history and objective versions are append-only.
- Embedding model name and version are stored per vector column version;
  changing models triggers a re-embed job and never mixes vectors.
