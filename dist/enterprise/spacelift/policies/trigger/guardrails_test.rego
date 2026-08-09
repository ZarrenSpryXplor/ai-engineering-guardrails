# GENERATED — DO NOT EDIT
# Canonical source: platform-policies/spacelift/trigger/guardrails_test.rego

package spacelift

import rego.v1

test_only_configured_finished_tracked_runs_trigger if {
	fixture := {"run": {"type": "TRACKED", "state": "FINISHED"}, "stack": {"id": "example-source-stack"}}
	"example-dependent-stack" in trigger with input as fixture
}

test_tasks_do_not_trigger if {
	fixture := {"run": {"type": "TASK", "state": "FINISHED"}, "stack": {"id": "example-source-stack"}}
	actual_triggers := trigger with input as fixture
	count(actual_triggers) == 0
}
