# auto-research-driver

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

An orchestration skill that drives the stages of a TMLR paper from S1 to S6, with
budget alerts so a run stops before it spends more than intended.

## Usage

This is an agent skill, not a library: point your agent at
[SKILL.md](SKILL.md), which defines the stages, the gates between them, and the budget
thresholds.

## What is in here

| Path | Contents |
|---|---|
| [SKILL.md](SKILL.md) | the orchestration definition (stages, gates, alerts) |
| `.github/workflows/` | CI, nightly runs, release, and the scan-alarm workflow |

The repository description records the last self-test result; check the workflows for
the current one rather than trusting a number in the description.

## License

MIT. See [LICENSE](LICENSE).
