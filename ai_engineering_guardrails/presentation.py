"""Human-oriented CLI rendering backed by Rich."""

from __future__ import annotations

import os
from typing import Any, Mapping

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text


OUTCOME_STYLES = {
    "passed": "bold green",
    "skipped": "bold yellow",
    "warning": "bold yellow",
    "failed": "bold red",
    "installed": "bold green",
    "modified": "bold red",
    "stale": "bold yellow",
    "missing": "bold yellow",
    "unmanaged-collision": "bold red",
}


def _console(*, no_color: bool) -> Console:
    plain = no_color or "NO_COLOR" in os.environ
    return Console(
        color_system=None if plain else "auto",
        no_color=plain,
        markup=False,
        highlight=False,
    )


def _box(*, ascii_only: bool) -> box.Box:
    return box.ASCII if ascii_only else box.SIMPLE_HEAVY


def _text(value: object, style: str | None = None) -> Text:
    return Text(str(value), style=style)


def _outcome(value: object) -> Text:
    label = str(value)
    return _text(label.upper(), OUTCOME_STYLES.get(label))


def print_validation(
    report: Mapping[str, Any],
    *,
    no_color: bool,
    ascii_only: bool,
) -> None:
    console = _console(no_color=no_color)
    table = Table(
        title="AI Guardrails Validation",
        box=_box(ascii_only=ascii_only),
        header_style="bold cyan",
        show_lines=False,
    )
    table.add_column("Check", style="bold")
    table.add_column("Result", no_wrap=True)
    table.add_column("Details")
    for check in report["checks"]:
        table.add_row(
            _text(check["label"]),
            _outcome(check["outcome"]),
            _text(check["detail"]),
        )
    console.print(table)
    console.print(_text("All validation checks passed.", "bold green"))


def print_status(
    report: Mapping[str, Any],
    *,
    no_color: bool,
    ascii_only: bool,
) -> None:
    console = _console(no_color=no_color)
    table_box = _box(ascii_only=ascii_only)

    products = Table(
        title="AI Guardrails Status",
        box=table_box,
        header_style="bold cyan",
        show_lines=False,
    )
    products.add_column("Product", style="bold", overflow="fold")
    products.add_column("State", no_wrap=True)
    products.add_column("Available", overflow="fold")
    products.add_column("Safety / trust", overflow="fold")
    products.add_column("Routing", overflow="fold")
    products.add_column("Packs", justify="right")
    for product, details in report["products"].items():
        state_value = str(details["state"])
        safety = details.get("safety_profile")
        trust = details.get("trust_mode")
        products.add_row(
            _text(product),
            _text(state_value, OUTCOME_STYLES.get(state_value)),
            _text(details["product_availability"]),
            _text(f"{safety} / {trust}" if safety and trust else "not installed"),
            _text(
                f"{details['routing_profile']}\navailability={details['model_availability']}"
                if details.get("routing_profile") and details.get("model_availability")
                else details.get("routing_profile", "not installed")
            ),
            _text(len(details.get("installed_packs", []))),
        )
    console.print(products)

    controls = Table(
        title="Controls",
        box=table_box,
        header_style="bold cyan",
        show_header=False,
    )
    controls.add_column("Control", style="bold")
    controls.add_column("Value", overflow="fold")
    controls.add_row(_text("Selected home"), _text(report["home"]))
    controls.add_row(_text("Safety profile"), _text(report["safety_profile"] or "not installed"))
    controls.add_row(_text("Trust mode"), _text(report["trust_mode"] or "not installed"))
    controls.add_row(_text("Target mapping"), _text(report["target_mapping"]))
    controls.add_row(_text("Package publication"), _text(report["publication_policy"], "bold green"))
    indicators = report["credential_classes"]
    credential_detail = f"detected ({', '.join(indicators)})" if indicators else "not detected"
    controls.add_row(_text("Credential indicators"), _text(credential_detail + "; values were not inspected"))
    console.print(controls)

    details_table = Table(
        title="Product details",
        box=table_box,
        header_style="bold cyan",
        show_lines=False,
    )
    details_table.add_column("Product", style="bold")
    details_table.add_column("Enforcement and notes", overflow="fold")
    attention: list[str] = []
    for product, details in report["products"].items():
        notes = [
            f"shell={details.get('shell_enforcement', 'missing')}",
            f"structured={details.get('structured_tool_enforcement', 'missing')}",
            f"Spacelift MCP={details.get('spacelift_mcp_enforcement', 'pack not installed')}",
        ]
        installed_packs = details.get("installed_packs", [])
        installed_skill_packs = details.get("installed_skill_packs", [])
        if "installed_packs" in details:
            notes.append("packs=" + (", ".join(installed_packs) or "none"))
        if "installed_skill_packs" in details:
            notes.append("exposed pack skills=" + (", ".join(installed_skill_packs) or "none"))
        if details.get("effective_global_instruction_file"):
            notes.append("global instructions=" + str(details["effective_global_instruction_file"]))
        if details.get("hook_trust"):
            notes.append("hook trust=" + str(details["hook_trust"]))
        if details.get("hook_maturity"):
            notes.append(
                f"hook={details['hook_maturity']}; activation={details['hook_activation']}; "
                f"organisation may disable={str(details['organisation_may_disable_hooks']).lower()}"
            )
            notes.append("inline suggestions=" + str(details["inline_suggestions"]))
        if details.get("skills_compatibility"):
            notes.append("skills=" + str(details["skills_compatibility"]))
            notes.append("agents=" + str(details["agents_compatibility"]))
            notes.append("subagents=" + str(details["subagents"]))
        if details.get("project_rules"):
            notes.append("project rules=" + str(details["project_rules"]))
            notes.append("skill registration=" + str(details["skills_registration"]))
            notes.append("Copilot instructions=" + str(details["copilot_instructions"]))
        if details.get("native_approvals"):
            notes.append("native approvals=" + str(details["native_approvals"]))
        if details.get("model_mappings"):
            notes.append(
                "models=" + ", ".join(
                    f"{tier}={model}" for tier, model in details["model_mappings"].items()
                )
            )
            attention.append(f"{product}: model availability is unverified; product fallback may apply")
        details_table.add_row(_text(product), _text("\n".join(notes)))
        if details["state"] != "installed":
            attention.append(f"{product}: installation state is {details['state']}")
        if details.get("manual_user_rules") == "outstanding":
            attention.append(f"{product}: paste the generated User Rules in Cursor settings")
        if details.get("chat_instructions") == "manual outstanding":
            attention.append(f"{product}: confirm the manual Chat Instructions step")
    console.print(details_table)

    if attention:
        attention_table = Table(
            title="Attention",
            box=table_box,
            header_style="bold yellow",
            show_header=False,
        )
        attention_table.add_column("Item")
        for item in attention:
            attention_table.add_row(_text(item, "yellow"))
        console.print(attention_table)

    repository = report.get("repository")
    if isinstance(repository, Mapping):
        repository_table = Table(
            title="Repository context",
            box=table_box,
            header_style="bold cyan",
            show_header=False,
        )
        repository_table.add_column("Measure", style="bold")
        repository_table.add_column("Value", overflow="fold")
        repository_table.add_row(_text("Repository"), _text(repository["repo"]))
        repository_table.add_row(
            _text("Detected packs"),
            _text(", ".join(repository["active_packs"]) or "none"),
        )
        repository_table.add_row(
            _text("Disabled packs"),
            _text(", ".join(repository["disabled_packs"]) or "none"),
        )
        repository_table.add_row(
            _text("Evidence"),
            _text(f"{len(repository['evidence'])} bounded detector match(es)"),
        )
        repository_table.add_row(
            _text("Warnings"),
            _text("; ".join(repository["warnings"]) or "none"),
        )
        console.print(repository_table)

        if repository["evidence"]:
            evidence_table = Table(
                title="Repository evidence",
                box=table_box,
                header_style="bold cyan",
                show_lines=False,
            )
            evidence_table.add_column("Pack", style="bold", overflow="fold")
            evidence_table.add_column("Kind")
            evidence_table.add_column("Path", overflow="fold")
            for item in repository["evidence"]:
                evidence_table.add_row(
                    _text(item["pack_id"]),
                    _text(item["kind"]),
                    _text(item["path"]),
                )
            console.print(evidence_table)


def print_skills_audit(
    report: Mapping[str, Any],
    *,
    no_color: bool,
    ascii_only: bool,
) -> None:
    console = _console(no_color=no_color)
    table_box = _box(ascii_only=ascii_only)
    catalogue = report["catalogue"]
    exposure_key = "fresh_default" if "fresh_default" in catalogue else "selected_installation"
    exposure = catalogue[exposure_key]
    pressure = catalogue["estimated_catalogue_pressure"]

    summary = Table(
        title="Skills Audit",
        box=table_box,
        header_style="bold cyan",
        show_header=False,
    )
    summary.add_column("Measure", style="bold")
    summary.add_column("Value")
    summary.add_row(
        _text(f"Catalogue ({catalogue['scope']})"),
        _text(
            f"{catalogue['skill_count']} skills; {catalogue['total_description_characters']} description characters"
        ),
    )
    summary.add_row(
        _text("Estimated catalogue pressure"),
        _text(
            f"{pressure['level']} ({pressure['description_only_percent_of_reference']}% description-only reference)",
            "yellow" if pressure["level"] != "low" else "green",
        ),
    )
    summary.add_row(
        _text("Fresh default exposure" if exposure_key == "fresh_default" else "Selected installation"),
        _text(
            f"{exposure['skill_count']} skills; {exposure['description_characters']} description characters; "
            f"estimated pressure={exposure['estimated_pressure']['level']}"
        ),
    )
    summary.add_row(
        _text("Tiers"),
        _text(", ".join(f"{name}={count}" for name, count in catalogue["tier_counts"].items())),
    )
    summary.add_row(_text("Token estimate"), _text(report["token_estimate_method"]))
    longest = catalogue["longest_descriptions"]
    summary.add_row(
        _text("Longest descriptions"),
        _text(", ".join(f"{item['name']}={item['characters']}" for item in longest) or "none"),
    )
    console.print(summary)

    skills = Table(
        title="Skill footprint",
        box=table_box,
        header_style="bold cyan",
        show_lines=False,
    )
    skills.add_column("Skill", style="bold", overflow="fold")
    skills.add_column("Estimated tokens", justify="right")
    skills.add_column("References", justify="right")
    skills.add_column("Reference tokens", justify="right")
    for skill in report["skills"]:
        skills.add_row(
            _text(skill["name"]),
            _text(skill["estimated_tokens"]),
            _text(skill["reference_file_count"]),
            _text(skill["reference_estimated_tokens"]),
        )
    console.print(skills)

    for finding in report["findings"]:
        console.print(
            _text(
                f"{str(finding['level']).upper()}  {finding['id']}: {finding['message']}",
                OUTCOME_STYLES.get("failed" if finding["level"] == "error" else "warning"),
            )
        )
    if not report["audit_complete"]:
        console.print(_text("Audit incomplete; no clean result is asserted.", "bold yellow"))
    else:
        console.print(_text("Skill audit complete.", "bold green"))
    console.print(_text("Token and pressure values are estimates; model context changes the real budget.", "dim"))
