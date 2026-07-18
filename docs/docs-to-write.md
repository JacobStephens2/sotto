Here is a description of each core document raised across this conversation, grouped by the role it plays in building a cross-platform application. [atlassian](https://www.atlassian.com/work-management/knowledge-sharing/documentation/software-design-document)

## Product Definition

- **Concept Brief** — Your north star. States the app name, one-sentence description, target users, problem, value proposition, design pillars, primary use cases, and explicit non-goals. It acts as the filter every later decision runs through, preventing feature creep before the project has a clear identity. [perplexity](https://www.perplexity.ai/search/6254f347-04ec-4dea-af94-59dc935d0531)
- **Product Requirements Document (PRD) / Mission** — Translates the concept into something buildable: user roles, user stories, functional and non-functional requirements, edge cases, and acceptance criteria. It defines *what* should happen and why, without prescribing implementation. [projectmanager](https://www.projectmanager.com/blog/great-project-documentation)
- **Roadmap** — Breaks the build into phases in implementation order, continuously updated as the project evolves. Kept separate from the PRD so scheduling churn doesn't destabilize the product definition. [projectmanager](https://www.projectmanager.com/blog/great-project-documentation)

## Architecture & Decisions

- **Architecture Overview / Software Design Document** — The technical blueprint. Covers system architecture, data design (models, ER diagrams, validation), interface/API design, component design, and assumptions. For cross-platform work, it should explicitly document the shared-core-vs-platform-shell boundary so platform code doesn't absorb business logic. [for-managers](https://for-managers.com/8-essential-project-planning-documents/)
- **Architecture Decision Records (ADRs)** — One short Markdown file per architecturally significant decision, capturing context, the decision, and consequences. Cross-platform apps generate many "forever decisions" (framework choice, module boundaries, persistence, sync policy), and ADRs keep those from becoming undocumented tribal knowledge. [youtube](https://www.youtube.com/watch?v=Fsx36ZTGMag)
- **Data Model / Domain Model** — Defines core entities, relationships, invariants, state machines, and validation rules. Especially valuable with a shared business-logic core, since every platform client depends on the same domain definitions. [atlassian](https://www.atlassian.com/work-management/knowledge-sharing/documentation/software-design-document)
- **API Contract** — Documents auth scheme, endpoints, request/response formats, errors, pagination, and versioning. Keeps multiple platform clients and the backend from coupling by accident; an OpenAPI file can serve as the executable contract. [github](https://github.com/github/spec-kit)

## Cross-Platform-Specific

- **Platform Strategy + Capability Matrix** — States which platforms you support, in what order, whether UI and logic are shared or native, and where parity is required versus where platform divergence is acceptable. The capability matrix (push, offline, biometrics, background tasks per platform) prevents false assumptions that every feature behaves identically everywhere. [projectmanagement](https://www.projectmanagement.com/discussion-topic/198325/core-project-management-documentation---order-of-creation)
- **Vertical Slice Plan** — Defines the smallest *complete*, production-quality path through the real architecture—one workflow exercising bootstrapping, navigation, persistence, and CI/CD across platforms. It proves the architecture and product direction without endless planning. [atlassian](https://www.atlassian.com/work-management/knowledge-sharing/documentation/software-design-document)

## Quality, Release & Compliance

- **Testing / Validation Plan** — Documents the test pyramid, the device/OS matrix, scenarios across physical devices and emulators, and merge-readiness criteria. Pushing deterministic business-logic tests into the shared core maximizes coverage. [newsletter.pragmaticengineer](https://newsletter.pragmaticengineer.com/p/rfcs-and-design-docs)
- **Release / CI/CD Plan** — Covers branching, build pipelines, app signing, store submission flows, beta distribution, and rollback. Turns "code that runs" into software you can ship and operate repeatedly. [projectmanagement](https://www.projectmanagement.com/discussion-topic/198325/core-project-management-documentation---order-of-creation)
- **Release / Compliance Checklist** — Bundles store-required artifacts: privacy policy, App Privacy Labels / Data Safety disclosures, Terms of Service, account deletion, and AI-transparency disclosure. Missing these tends to cause late rejection or rework, particularly with external AI and sensitive data. [perplexity](https://www.perplexity.ai/search/fccfa0b0-9cb2-4e85-ad60-8f5b20815cb4)

## Style Guides

- **Code Style Guide** — Naming, formatting, comment discipline, and module grouping, plus rules for what lives in the shared core versus platform shells and how platform-specific code is isolated. [blogs.embarcadero](https://blogs.embarcadero.com/9-best-practices-for-cross-platform-app-development/)
- **Design System / UI Style Guide** — Typography, color, spacing, component library, and accessibility rules, noting where platforms intentionally follow native conventions instead of forced visual parity. [atlassian](https://www.atlassian.com/work-management/knowledge-sharing/documentation/software-design-document)
- **Documentation / Writing Style Guide** — Declarative phrasing and consistent ADR/spec formatting so your specs read as contracts—useful given your spec-driven, agent-assisted workflow. [martinfowler](https://martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html)

## Agent & Workflow (For Your Setup)

- **Spec-Driven Files (`constitution.md`, `requirements.md`, `plan.md`, `tasks.md`, `validation.md`)** — Turn specifications into executable constraints that guide what coding agents generate, rather than passive documentation written after the fact. [projectmanager](https://www.projectmanager.com/blog/great-project-documentation)
- **Agent Context & State (`CLAUDE.md`, `_state.md`)** — A root file carrying project standards and persistent instructions, plus per-component state files logging current phase, decisions, and next steps so sessions and sub-agents hand off cleanly. [reddit](https://www.reddit.com/r/ClaudeAI/comments/1pef530/how_do_you_prosetup_claude_code_for_fullstack/)

A practical note: treat the product, architecture, and platform docs as living documents committed atomically with the code they govern, so they version alongside the implementation rather than drifting out of sync. [perplexity](https://www.perplexity.ai/search/a6a78a4c-7aad-4573-a564-a36942858997)