# Routing and cost

Routing is optional execution guidance for native product subagents. It is separate from behavioural policy, deterministic enforcement, safety profiles, and trust modes. A lower tier never grants authority or reduces required review.

## Portable abstraction

Capability tiers are `economy`, `balanced`, and `deep`. Reasoning levels are independently `low`, `medium`, and `high`; concurrency and write capability are separate again. Vendor IDs live only in `routing/model-maps/`.

The five canonical roles are:

- `workstation_explorer`: economy, read-only repository mapping and evidence;
- `workstation_test_analyst`: economy or balanced, read-only test/log classification;
- `workstation_implementer`: balanced, the single bounded writer;
- `workstation_reviewer`: balanced or deep, read-only correctness/security/compatibility review;
- `workstation_verifier`: balanced or deep, independent read-only completion verification.

`none` installs no native routing agents. `economy` limits bounded read work and concurrency to one. `balanced` uses economy exploration, balanced ordinary implementation/review, deep high-risk judgement, at most two read-only agents and one writer. `quality` promotes interpretation and high-risk review, at most three independent read-only agents and one writer. No profile permits parallel writers or more than two bounded attempts before escalation.

## Delegation and escalation

Do not delegate a task that a few targeted reads or commands can complete. Delegate for context isolation, specialist read-only analysis, independent verification, genuinely independent work, or bounded high-volume work suited to a cheaper model. Every delegation states objective, scope, modification permission, return format, completion criteria, and escalation conditions.

Escalate when evidence conflicts, ambiguity remains material, more than two viable paths remain, security or a public contract is involved, production or persistent data appears, two bounded attempts fail, scope thresholds are exceeded, verification conflicts, or capability/context is insufficient. Economy agents may collect high-risk evidence but cannot make the final decision. Reuse a useful existing agent context and stop agents that no longer help.

## Product maps and availability

Current verified defaults are Codex Luna/Terra/Sol, Claude `haiku`/`sonnet`/`opus`, and Cursor `inherit`. VS Code, Visual Studio, and JetBrains maps also use inherited selection: the installer omits `model` rather than guessing a plan-specific identifier. VS Code installs native custom agents only when routing is explicit. Visual Studio custom agents are user-selectable, version-dependent roles rather than automatic subagents. JetBrains emits a reviewable manual Copilot bundle because that surface is Preview. Cursor explicit IDs depend on provider, plan, and organisation and may fall back. Model files are configuration, not proof of account entitlement. Status therefore says configured but availability unverified.

```sh
ai-guardrails routing show --profile balanced --product all
ai-guardrails routing validate
ai-guardrails routing set balanced --product cursor \
  --model-override cursor:economy=provider/model-id --dry-run
```

The installer never edits the primary model, never sets Claude's global subagent-model environment variable, and does not install a global concurrency override.

## Context and output

Native roles search before large reads, use targeted ranges, avoid rereading unchanged data, run narrow tests before broad suites, request terse output where supported, and summarise logs without losing exit status or diagnostically useful failures. No output-filtering or command-rewriting hook is installed.

## Measurement limits

The content-free metrics schema can represent product, model, task class, tier, reasoning, subagent count, available token counts, duration, retries, escalations, and outcome. It excludes prompts, code, commands, arguments, and tool output. This repository installs no collector and uploads no telemetry.

API-token billing, included subscription usage, product credits, third-party model pools, and list-price estimates are different accounting systems. Lower latency is not the same as lower cost, and extra subagent contexts can increase tokens. Use product-native usage information and compare representative completed tasks; do not promise exact monetary savings.

## Evaluate before changing routing

Treat a routing change as a small configuration experiment, not a model popularity contest. Start with 10–20 representative, bounded tasks and compare the same tasks against the current profile. Record only outcome, unnecessary files or dependencies, diff size, verification result, retries, duration, and product-native token data when it is available. Include at least one task where the correct answer is to make no code change and one that can expose unnecessary abstraction.

Keep the comparison local or use product-native reporting. Do not upload prompts, source, commands, or logs; do not add a telemetry collector or an LLM evaluation framework. A configuration should remain unchanged unless it produces reliable task outcomes with no material increase in unnecessary edits or verification failures.

- [Codex pricing and plans](https://developers.openai.com/codex/pricing)
- [Claude Code costs and `/usage`](https://code.claude.com/docs/en/costs)
- [Cursor models and pricing](https://cursor.com/docs/models-and-pricing.md)
