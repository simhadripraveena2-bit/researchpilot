# B3 (held-out) isolation: what is enforced, what is not, and the proposal

EVALUATION_FRAMEWORK §2a: "The implementing developer, including any AI coding assistant,
never reads B3 items or answers."

## Enforced in code (`backend/src/researchpilot/evaluation/cases.py`, `report.py`)

| Control | How |
|---|---|
| B3 data cannot live in the repository | `guard_split` refuses a B3 dataset whose file is inside the repository tree. |
| Only the custodian runs B3 | `guard_split` refuses B3 unless `RP_BENCHMARK_CUSTODIAN=1` is set by the person running it. |
| B1–B3 need expert labels and real data | `guard_split` refuses non-`expert_adjudicated` labels and `synthetic` cases outside B0. |
| Case IDs carry their split | `GM-B3-…` / `GD-B3-…`; a mismatch is refused. |
| B3 reports are aggregate-only | No case IDs, identifiers, titles, explanations or per-case results; lists are reduced to counts. |
| No overlap between splits | `overlapping_works()` compares SHA-256 hashes of each split's identifiers. Only hashes need to be shared between custodian and developers. |
| Recording is B0-only | `run_benchmarks.py --record` refuses other splits. |

## Not enforceable in code (limitations)

- The environment variable is a **procedural** guard, not access control: anyone who can
  read the B3 file can set it. The real protection must be **storage access control**.
- A developer or AI assistant with shell access to a machine holding B3 could read it. B3
  must therefore never be on machines or in containers used for development, including
  cloud sessions with AI assistants.
- The repository check uses the installed package's location. In the Docker image this
  resolves to `/`, so B3 is always refused inside the container. The custodian runs from a
  checkout (fail-safe, but the image can't run B3).
- The recorded responses a B3 run needs reveal its works. They must live with the B3 data,
  not in this repository.

## Proposal

1. **Custodian storage:** a private bucket or repository readable only by the custodian
   (not the development team, not CI, not AI sessions). It holds `b3.json` files and their
   recordings.
2. **Runs:** the custodian checks out a tagged commit of this repository on a custodian
   machine, sets `RP_BENCHMARK_CUSTODIAN=1` and runs
   `scripts/run_benchmarks.py /secure/b3/g_match.json --out /secure/reports`. They publish
   only the aggregate report (`*-b3.md`).
3. **Separation check:** the custodian publishes the SHA-256 work hashes of B3. A CI check
   compares them with B0–B2 (`overlapping_works`) without revealing B3 items.
4. **Retirement:** when B3 results lead to changes, the affected items move to B2 and are
   replaced (§2a). The custodian records this in the B3 change log.
5. **Audit:** the custodian logs each B3 run (commit SHA, dataset version, date). Reports
   cite the run.

Status: no B3 exists yet. No B1/B2 exist yet. Only B0 (AI-proposed labels) is in this
repository.
