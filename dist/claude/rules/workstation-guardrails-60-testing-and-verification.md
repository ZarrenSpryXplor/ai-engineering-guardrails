<!-- GENERATED — DO NOT EDIT
Canonical source: policy/fragments/60-testing-and-verification.md
-->
<!-- Canonical policy ID: testing-and-verification -->

## Testing and verification

- Add or update tests when behaviour changes. Run the narrowest relevant tests first, then broader applicable checks.
- Run applicable formatting, linting, type checking, and static analysis.
- Review generated files and the final Git diff.
- Report commands run and observed outcomes, including checks that could not be run.
- Do not modify or delete legitimate tests merely to produce a passing result, and do not update snapshots blindly.
