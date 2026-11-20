# Product roadmap: beating Linear and Asana (P6–P10)

Date: 2026-11-20. Base: the `custom` branch of github.com/ujjwalsittu/plane (Plane CE v1.5.0 plus our
P1–P5 work), deployed at plane.azeonics.com.

## Intent

Make this fork the best project tool for **our own teams first, then sell it**.

How we actually work today: AI agents (Claude sessions over the MCP) create and update almost all
work items, comments and milestones; three people (Ujjwal, Debasis, Yogesh) open Plane to check
status. When a person checks status they want three answers, fast:

1. **What's done**
2. **What's blocked**
3. **What needs me**

Today Plane doesn't answer them: OSMG's M1 milestone (22 decisions only Ujjwal can make, due the next
day, none started) was only noticed because an agent went looking.

The selling point that follows: _the project tool built for AI agents and the people who supervise
them_. Linear and Asana are adding agents to a human-first tool; we start from the agent-first loop.

## Goals

- Answer done / blocked / needs-me at a glance, across all projects, and push the urgent part to the
  person (Slack) before it's late.
- Make agents first-class: visible as actors, startable from Plane, governed, auditable.
- Reach parity with Linear and Asana on the planning features buyers compare (goals, portfolios,
  timeline, workload, rules, intake, insights).
- Be sellable: own brand, hosted multi-tenant, enterprise security, importers.

## Non-goals

- In-app code review (Linear's Diffs / Guided Reviews). Reviews stay in GitHub; we keep showing PR
  status, checks and reviews on the work item.
- Our own hosted agent runtime with customer model keys (Linear's cloud coding agent). We start
  Claude sessions instead; revisit when selling.
- Email or WhatsApp digests for now (Slack and in-app were chosen). Plane's existing email
  notifications stay as they are.
- Native mobile and desktop apps; a PWA covers mobile.

## Anti-goals (would count as failure even if it works)

- Features that only pay off when humans type a lot. Agents do the writing; humans read and decide.
- Status that can drift from reality. The Brief is computed from data; AI text sits on top of it,
  never instead of it.
- Changes that make upstream merges impossible. Keep work additive (today: about 7% new code,
  234 upstream lines removed) and follow UPSTREAM_SYNC.md.

## Constraints

- **License:** Plane CE is AGPL-3.0. Anything built into the fork must be available as source to
  every user, including hosted customers. Parts we want to keep closed (AI and agent services,
  digests) must be separate services that talk to the core over its API. A lawyer confirms this
  before launch.
- **Trademark:** we can't sell it as "Plane" or with its logo; it needs its own brand (P10).
- **MCP compatibility:** the official Plane SDK and MCP tool shapes stay working; new capabilities
  get MCP tools so agents can use them.
- **Team:** built mostly by Claude sessions, reviewed by Ujjwal; small, frequent deploys as in P1–P5.

## Approaches decided

| Decision                     | Options considered                                                                    | Picked                                               | Why                                                                                                                                  |
| ---------------------------- | ------------------------------------------------------------------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Base                         | Keep forking Plane CE · rewrite from scratch · fork plus closed side-services         | **Fork Plane CE, closed side-services where useful** | The fork is ~93% upstream and our changes are additive; a rewrite means rebuilding ~400k lines first.                                |
| Agent execution              | Start Claude sessions from Plane · only integrate outside agents · own hosted runtime | **Start Claude sessions**                            | Biggest differentiator; builds on the MCP and GitHub work we have; far smaller than a hosted runtime.                                |
| Brief and alerts             | Email · WhatsApp · Slack · in-app only                                                | **Slack and in-app**                                 | Where the team already works.                                                                                                        |
| Code review                  | Build in-app · leave in GitHub                                                        | **GitHub**                                           | GitHub does it well; large build for little gain.                                                                                    |
| Client and business tracking | Early · after the core · skip                                                         | **After the core (P8)**                              | Useful for client projects like OSMG and for selling, but supervision and agents come first.                                         |
| First screen                 | Computed Brief · agent-written updates · digest only                                  | **Computed Brief, AI summary on top**                | Can't drift from reality; Slack digest reuses the same queries.                                                                      |
| Open or closed code          | Everything in the fork now · closed side-services from P6                             | **Everything in the fork for now**                   | Fastest, same pipeline as P1–P5. What stays closed is decided with the lawyer (item 36), accepting some rework to split it out then. |
| Late phases                  | Dates hold, cut scope · scope holds, dates move                                       | **Dates hold**                                       | Each phase has must-haves and stretch items; unfinished stretch items move to the next phase.                                        |
| Hosting when selling         | One shared instance · one per customer · both                                         | **One shared instance**                              | Plane is already multi-workspace. Every new setting (AI keys, Slack, branding) is per workspace from now on, not instance-wide.      |

### Calls made after the review (mine, correct if wrong)

- **MCP:** we keep using the official Plane MCP and match its tool shapes, as in P2–P5; our small MCP
  image patch is extended only where no official tool exists.
- **Decisions:** today's decisions (e.g. OSMG M1's "Decide / Confirm / Gather" items) are work items
  assigned to a person with a shared label. Decision requests (item 4) build on that convention, so
  existing ones show up on day one; no migration.
- **Agent attribution:** a minimal version of agent identity moves into P6 (item 8a): agent activity
  is told apart from human activity by how it arrived (API key vs browser session) and shown as such
  on the Brief. Full agent identities stay in P7.
- **AI provider:** the Claude API. One key per installation in P6, per-workspace keys (bring your
  own) in P7. Run cost is shown where the API reports it; Claude Code sessions show duration only.
- **Slack:** an internal app for our workspace in P6, with tokens and user mapping stored per
  workspace so per-customer installs (OAuth) can be added in P10 without a rebuild.

## Phases and features

Target dates are my proposal, chosen to keep the P1–P5 pace (about one phase every 4–6 weeks).

### P6 · Supervision — target 2026-12-18

Must-have: 1, 3, 4, 6, 8a. Stretch: 2, 5, 7.

1. **Brief home page.** One cross-project screen: _Needs me_ (open items assigned to me, mentions,
   decision requests; overdue first, then by milestone date), _Blocked_ (open "blocked by", "waiting
   on", stale in-progress items), _Done since my last visit_ (grouped by project, showing who did
   it, agent or person). Milestones due in the next 7 days on top.
2. **AI summary on the Brief.** A short "what changed, what needs you" paragraph generated from the
   same data (Asana Dash / Linear Pulse equivalent), with links to the items it mentions.
3. **Blocked as first class.** Surface "blocked by" relations, add "waiting on" (a person or
   something external, with a note), detect stale items (in progress with no activity for N days).
4. **Decision requests and approvals.** An agent or person can ask for a decision on a work item
   with options; the asked person answers or approves from the Brief or Slack; the answer is
   recorded on the item and the agent is notified.
5. **Project updates and health.** On track / at risk / off track updates per project and
   initiative, drafted by agents from activity, with milestone burn-up and a predicted finish date.
6. **Slack app.** Daily brief as a DM, alerts for milestones due tomorrow or overdue and for new
   decision requests; answer decisions and approve from Slack.
7. **Priority inbox.** Notifications that need action come first; snooze; mark all done.
   8a. **Agent attribution (minimal).** Mark activity that came through API keys (agents) apart from
   browser sessions (people), and show "agent" or "person" on the Brief and activity feeds.

### P7 · Agent-native — target 2027-01-29

Must-have: 8, 9, 10, 12, 13. Stretch: 11, 14, 15, 16, 17.

8. **Agents as members.** Agent identities with names and avatars, activity attributed to the agent
   (not a shared bot), and a delegation model: a person stays the owner, the agent is a
   contributor.
9. **Run log and live presence.** Each work item shows agent runs: session, steps, linked PRs and
   commits, duration and cost, plus "agent working on this now".
10. **Start Claude sessions from Plane.** Delegating an item to an agent starts a Claude session
    (locally or in the cloud) with the item as its brief; progress and results stream back to the
    run log.
11. **Loops.** Scheduled or triggered agent automations with run history (e.g. weekly project
    update, daily triage sweep, stale-item nudges).
12. **Guardrails.** Per-agent scopes, approval gates for risky actions (deleting, closing
    milestones, changing dates), audit trail, AI spend limits, bring-your-own model key.
13. **Event subscriptions.** Webhooks and a streaming feed per workspace or project, so agents react
    to changes instead of polling.
14. **Ask the workspace.** Chat grounded in work items, pages, milestones and GitHub, answering with
    links ("what's blocking OSMG M3?").
15. **Triage intelligence.** Suggest assignee, project, labels and duplicates for new items and
    intake.
16. **Meetings to action items.** Paste notes or a transcript and get proposed work items with
    owners and dates to accept.
17. **MCP completeness.** Close the remaining "not available on this edition" gaps: customers,
    project grouping, workflows, project updates, parallel cycles.

### P8 · Planning parity and client work — target 2027-03-26

Must-have: 18, 19, 20, 22, 23, 25, 29. Stretch: 21, 24, 26, 27, 28, 30.

18. **Goals and OKRs** with weighted progress rolled up from initiatives and projects.
19. **Portfolios** grouping projects, with health roll-up (also clears the project-grouping gap).
20. **Timeline with dependencies** between work items and projects, and the critical path.
21. **Workload and capacity** per person (and agent throughput), with placeholder roles.
22. **Rules engine.** When / if / then automations, round-robin assignment, SLAs, auto-close and
    auto-archive of stale items.
23. **Intake.** Forms with branching, Slack and email intake, routing to the right project.
24. **Customer requests** linked to work items, with customer segments and request counts.
25. **Dashboards and insights.** Cycle time, lead time, burn-up, custom widgets, CSV export.
26. **Richer custom fields.** Formula and reference fields; one work item in several projects.
27. **Approvals and proofing** on attachments (annotate PDFs and images).
28. **Recurring work items.**
29. **Timesheets, budgets and billable hours**, built on work logs.
30. **Read-only share links** for projects, timelines and updates (for clients).

### P9 · UI and speed — target 2027-04-30

Must-have: 31, 32, 33. Stretch: 34, 35.

31. **Keyboard-first command palette** for every action.
32. **Instant UI.** Optimistic updates, local cache, offline reading.
33. **Peek views, inline editing, density.** Redesigned list and board.
34. **Linear-style inbox** design on top of P6's priority inbox.
35. **Mobile PWA** for the Brief, inbox, decisions and work items.

### P10 · Ready to sell — target 2027-06-25

Must-have: 36, 37, 38, 39, 40, 41. Stretch: 42, 43.

36. **Licensing plan.** Lawyer-reviewed AGPL plan and which services stay separate and closed.
37. **New brand.** Name, logo, domain, and removing Plane marks.
38. **Hosted multi-tenant service.** Signup, workspaces, plans and billing (Razorpay and Stripe).
39. **Enterprise access.** SSO/SAML/SCIM, audit log, guest management, view-only seats.
40. **Data and compliance.** India data residency, scheduled off-volume backups (absorbs PLAT-17),
    SOC 2 readiness using our own GRC platform.
41. **Importers** from Linear, Asana, Jira and GitHub Issues.
42. **Developer platform.** Public API and webhook docs, SDK, Slack and other integrations listing.
43. **AI governance.** Admin controls over what AI and agents can read, and no-training guarantees.

## Left to the builder

- Data models, endpoints and UI layout for each feature, following the patterns used in P1–P5
  (shared `plane/utils/*` helpers, external API plus session-auth app views, MCP-compatible shapes,
  i18n in `milestone.json`, tests per feature).
- How a Claude session is launched (local CLI, remote trigger or cloud) for item 10, as long as
  progress and results come back to the run log.
- Exact stale thresholds, digest timing and default Slack message layout.
- Splitting each feature into deployable steps.

## Loading into Plane

Each phase becomes a milestone in the Plane Platform (PLAT) project with its target date, and each
numbered feature becomes a work item in that milestone with its description from this document.
Must-have items get high priority, stretch items medium.
PLAT-17 (scheduled backups) moves into P10 under item 40.
