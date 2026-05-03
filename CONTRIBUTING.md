# Contributing to python-oa3-client

Thanks for your interest in contributing! This repo is a Python companion client framework on top of [openadr3](https://github.com/grid-coordination/python-oa3) — it adds a `BaseClient` lifecycle, `VenClient` / `BlClient` wrappers, notification channels (MQTT, webhook), and optional mDNS/DNS-SD VTN discovery. The underlying spec, raw HTTP, and Pydantic models live in `python-oa3`; this repo is the framework layer that consumes them.

## How to contribute

### Discussions

Use [Discussions](https://github.com/grid-coordination/python-oa3-client/discussions) for:

- Questions about how to use the client framework — VEN registration, lifecycle, channel selection, `__getattr__` delegation to `OpenADRClient`, mDNS modes
- API and design judgment calls — "should `python-oa3-client` model X?" / "which layer does Y belong in — `python-oa3` or `python-oa3-client`?"
- VTN behavior gaps that affect the framework — e.g. odd `/notifiers` responses, MQTT URI scheme variants, webhook callback reachability across NAT
- Coordination with the upstream [OpenADR 3.1.0 specification](https://github.com/grid-coordination/python-oa3/blob/main/resources/openadr3.yaml) and the [VTN Reference Implementation](https://github.com/oadr3-org/openadr3-vtn-reference-implementation)
- Sharing what you're building on top of `python-oa3-client` (VENs, business-logic clients, integrations)

Discussions are open-ended — a good place to think out loud or scope something before it becomes a concrete change. Aligned outcomes from a Discussion often turn into one or more Issues.

### Issues

Use [Issues](https://github.com/grid-coordination/python-oa3-client/issues) for actionable changes:

- Bugs in client construction, auth (Bearer or OAuth2 client-credentials), VEN registration idempotency, or program lookup
- Channel bugs — MQTT connection lifecycle, webhook receiver routing, message coercion, `await_messages` timing
- mDNS/DNS-SD discovery issues — TXT-record parsing, fallback behavior across the four `DiscoveryMode` values, `advertise_vtn` interop
- VTN behavior gaps that should be absorbed at the framework layer (Postel's Law: be liberal in what you accept) rather than in `python-oa3` itself
- Test failures or unexpected behavior with concrete repro steps
- Documentation errors, unclear explanations, or stale prose in `README.md` or `doc/`
- Discussion outcomes that have alignment and a clear scope

If a bug is in raw HTTP, request building, or coerced entity shape, it likely belongs in [`python-oa3`](https://github.com/grid-coordination/python-oa3) instead — file there. If you're not sure which repo, file here and we'll move it.

If you're not sure whether something is an Issue or a Discussion, start with a Discussion — we can convert it later.

### Pull requests

Pull requests are welcome.

- For small fixes (typos, broken links, single-test corrections, single-channel bug fixes, mDNS edge cases), open a PR directly.
- For substantive changes (new notification channel types, new lifecycle hooks, new discovery modes, new auth modes), open a Discussion or Issue first so we can align on scope before you invest the effort.
- All changes pass `pytest tests/` and `ruff check src tests` / `ruff format --check src tests` cleanly. CI runs lint on every push and PR.
- Match the existing tone and structure. The framework keeps `BaseClient` (auth + lifecycle), `VenClient` / `BlClient` (entity-aware wrappers), and notification channels (`NotificationChannel` protocol implementations) as roughly orthogonal layers; patches that fit cleanly into one layer without leaking concerns across them are the easiest to land. In particular, raw HTTP and coercion concerns belong in `python-oa3`, not here.
- One commit per logical change is fine; we don't require squash or any particular branch naming.

## Development

```bash
pip install -e ".[dev]"           # install with dev dependencies (includes mqtt/webhooks/mdns extras)
pytest tests/ -v                  # run the unit test suite (offline)
ruff check src tests              # lint
ruff format --check src tests     # format check (drop --check to apply)
```

Optional integration tests under `examples/` (e.g. `smoke_test.py`, `smoke_test_mdns.py`) exercise live VTN-RI, Mosquitto, or zeroconf and are not run by `pytest tests/`. Run them manually when changes touch the relevant integration surface.

### Pre-commit hooks

This project uses [pre-commit](https://pre-commit.com/) to run Ruff lint and format checks automatically:

```bash
pip install pre-commit
pre-commit install
```

Ruff lint + format are also enforced in CI via `.github/workflows/lint.yml`.

### Relationship to python-oa3

`python-oa3-client` depends on `openadr3>=0.3.0` and exposes its `OpenADRClient` methods directly via `__getattr__` delegation on `BaseClient`. When deciding where a change belongs:

- **In `python-oa3`**: spec types, raw HTTP request/response, Pydantic models, coercion to entities, time handling.
- **In `python-oa3-client`** (this repo): client lifecycle, auth flows beyond bare Bearer (OAuth2 token fetch, User-Agent composition), VEN registration semantics, program-name caching, notification channel implementations, mDNS discovery, VEN-scoped convenience methods.

If a patch needs to span both repos, file the design discussion in whichever feels more central and link the two PRs.

## Code of conduct

Be respectful and constructive. We're a small project and appreciate everyone who takes the time to file an issue or send a PR.

## Important notice

This library is provided on an "as-is" basis. Updates and maintenance, including responses to issues filed on GitHub, will take place on an "as time and resources permit" basis. Library output (notification messages, coerced payloads, discovered VTN records) is best-effort against the [OpenADR 3.1.0 specification](https://github.com/grid-coordination/python-oa3/blob/main/resources/openadr3.yaml) and the behavior of real-world VTN implementations (including the [VTN Reference Implementation](https://github.com/oadr3-org/openadr3-vtn-reference-implementation)). This library is not authoritative for billing, dispatch, or grid operations — independent verification against the source spec and your VTN's actual responses is recommended for any consumer relying on these results for operational correctness.
