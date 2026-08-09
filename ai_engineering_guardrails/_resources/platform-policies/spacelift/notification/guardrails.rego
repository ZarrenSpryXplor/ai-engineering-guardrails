package spacelift

import rego.v1

config := data.guardrails.config

production if {
	some label in input.run_updated.stack.labels
	label in config.production_labels
}

inbox contains {
	"title": "Protected Spacelift run requires attention",
	"body": sprintf("Stack %s run %s entered %s", [stack.id, run.id, run.state]),
	"severity": "WARN",
} if {
	stack := input.run_updated.stack
	run := input.run_updated.run
	production
	run.type in {"TRACKED", "TASK"}
	run.state in config.notification_states
}
