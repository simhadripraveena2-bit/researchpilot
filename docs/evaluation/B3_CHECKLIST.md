# B3 operational checklist (G-MATCH, G-LATEST-DATES)

Turns `B3_ISOLATION.md` into steps a custodian can tick off. **Status: not started.** No
custodian is named and no B3 data exists.

Rule: B3 items, labels and per-item results never reach developers, CI, shared cloud
environments or any AI system. This repository, its developers and the AI assistant that built
it have never seen B3 data. Nothing here may be done by a developer on the custodian's behalf.

Owner of every step: **the B3 custodian** (`EVALUATION_ROLES.md`), unless stated otherwise.

## A. Custodian

- [ ] A1. Custodian named, with a deputy (evaluation lead records it in
      `EVALUATION_ROLES.md`).
- [ ] A2. Custodian declares no development role on this repository (no commits, no
      prompting AI coding assistants on it).
- [ ] A3. Custodian has read the guidelines, `B1_PROTOCOL.md` and this checklist.

## B. External storage

- [ ] B1. A storage location outside this repository and its forks, with no access from
      developer machines, CI or cloud-agent environments. For example: a private repository
      in a separate organisation, or an access-controlled bucket.
- [ ] B2. Layout:
      `b3/<benchmark>/<version>/{b3.json, recordings/, annotations/, adjudication/}`, plus
      `b3/audit.log` and `b3/hashes/`.
- [ ] B3. Encryption at rest; backups in the same access domain.
- [ ] B4. Never copy B3 files into issue trackers, chat, shared drives, prompts or any AI
      tool.

## C. Access control

- [ ] C1. Read/write: custodian and deputy. Write-only drop for B3 annotators and the
      adjudicator, each seeing only their own assignment.
- [ ] C2. No developer, CI token or service account has read access. Verify by listing the
      grants; record the list in the audit log.
- [ ] C3. Review access quarterly and when people change roles; record each review.

## D. Dataset hashing

- [ ] D1. On freeze, record the SHA-256 of each B3 file (dataset and every recording) in
      `hashes/<version>.sha256`.
- [ ] D2. Compute the **work-hash list**: SHA-256 of each lower-cased identifier, as
      `cases.work_keys`. This list, without labels, is the only B3 artefact developers may
      receive.
- [ ] D3. Before every run, verify the file hashes. On a mismatch, stop and investigate.

## E. Split-overlap checks

- [ ] E1. Before freeze, run the overlap check against B0, B1 and B2 (`overlapping_works`)
      **on the custodian machine**. Replace any overlapping B3 work.
- [ ] E2. Publish the work-hash list to developers (D2). A CI check can then refuse any new
      B0–B2 case whose work hash is in B3. *(Code task for developers: they receive the hash
      list only.)*
- [ ] E3. After each B0–B2 change, the custodian re-runs E1 and logs the result.

## F. Locked evaluation run

- [ ] F1. The evaluation lead requests a run for a **tagged commit**; the custodian records
      the tag and SHA.
- [ ] F2. Fresh checkout of that tag on a custodian machine (not in Docker:
      `guard_split` refuses B3 inside the image). Dependencies installed from the lockfile
      beforehand; no network during the run (recordings only).
- [ ] F3. Set `RP_BENCHMARK_CUSTODIAN=1` and run:
      ```bash
      uv run python scripts/run_benchmarks.py /secure/b3/g_match/<version>/b3.json --admin-url <local postgres> --out /secure/b3/reports/<run-id>
      ```
      Same for G-LATEST-DATES.
- [ ] F4. No re-runs to "fix" a result. A harness error (not evaluable) is reported as such
      and re-run only after a code fix that is reviewed without B3 details.
- [ ] F5. One run per release candidate. Repeated runs against the same B3 version are
      limited and logged, to avoid tuning against B3 through feedback.

## G. Aggregate-only results

- [ ] G1. Release only `*-b3.md`. `report.py` already strips case IDs, identifiers, titles,
      explanations and per-case results for B3. Check the file before release anyway.
- [ ] G2. Report the metrics with 95% confidence intervals (§2a: R1 allowance) and failure
      **categories** with counts. No examples.
- [ ] G3. Never answer developer questions about specific B3 items. Category-level
      clarification only.

## H. Audit log

- [ ] H1. Append-only `b3/audit.log`, one line per event: date, person, action (access
      grant/review, freeze, hash check, overlap check, run, report release, retirement),
      commit SHA, dataset version, outcome.
- [ ] H2. The evaluation lead reviews the log at each release decision.

## I. Retirement of exposed cases

- [ ] I1. A B3 item is **exposed** if its contents or label reach anyone outside the custodian
      domain, or if a B3 result led to a change aimed at it (§2a).
- [ ] I2. Exposed items move to B2 (with their labels) and are replaced by new items from the
      same stratum. The new items are labelled under B1_PROTOCOL by B3 annotators.
- [ ] I3. Record each retirement (item hash, reason, replacement hash, date) in the audit log.
      Publish the updated work-hash list.
- [ ] I4. After any release-blocking failure leads to a fix, retire the items in the failing
      categories that the fix was designed around.

## J. What developers provide (code, no B3 access needed)

- [x] `guard_split` refuses B3 in the repository and without `RP_BENCHMARK_CUSTODIAN=1`.
- [x] Aggregate-only B3 reports; run metadata (SHA, rule version, dataset hash).
- [x] `work_keys` / `overlapping_works`.
- [ ] CI check against a published B3 work-hash list (E2).
- [ ] Optional `--verify-hashes` flag for `run_benchmarks.py` (D3).
- [ ] B1/B3 schema with ground truth and two annotations (B1_PROTOCOL §2).
