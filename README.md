# RET-C2-609 — Retail CVS Store Operations Staff FAQ Agent

> **Category**: Cat 2 (multi-step workflow for a specific job-to-be-done)
> **Industry**: RET

## Overview

This agent answers store-staff questions about food-labelling and allergen rules, inventory procedures, and day-to-day operations, in several languages. Every allergen or compliance statement it makes must cite a passage retrieved from the knowledge base; if it cannot ground the claim it declines rather than answering, and that behaviour cannot be switched off. It is built for staff who need a correct answer on the floor, where a plausible-sounding wrong one is worse than none.

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent connects to the platform at start-up. Without it, start-up fails immediately (see *Behaviour without the platform* below). Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Installed from PyPI as a dependency. |
| Python | >=3.11 |

```bash
pip install -e .
```

### Behaviour without the platform

The framework is designed to run **only** on AGENTIC STAR. There is no fallback or degraded
mode. If the platform is unreachable or the SDK version does not match, the agent raises
`PlatformRequired` during graph compile / start-up preflight rather than starting in a partially
working state. This is intentional — a half-running agent is worse than one that refuses to start.

## Credentials — you supply them

This agent calls an Azure OpenAI deployment, so it needs that deployment's credentials.
They are **not** in this repository and are not shipped with it: they are yours and they
bill to your account.

`config/agent.yaml` declares what is needed:

| Name | Used for |
|---|---|
| `AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_DEPLOYMENT` | Synthesising the grounded answer |

Set them as environment variables on the process that runs the agent. Never commit them,
and never put them in `config/config.yaml` — that file ships in the image.

**The model is optional.** It phrases the answer from the retrieved sources. If it cannot
be reached, the answer is composed from the same sources without it, and the citation check
applies either way.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

Tests run without a platform connection. Running the agent itself does not.

## Project Structure

```
src/          agent implementation (nodes, services, schemas)
tests/        unit, integration and boundary tests
config/       agent configuration
docs/         design and test specification
```

See `docs/02_design.md` for the design and `docs/03_test_spec.md` for the test specification.

## Customising

1. Adjust `config/` for your own environment and policies.
2. Replace the knowledge sources and sample data with your own.
3. Review the node implementations under `src/nodes/` for domain-specific logic.
4. Re-run the test suite.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.
