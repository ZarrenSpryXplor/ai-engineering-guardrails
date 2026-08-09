package spacelift

import rego.v1

config := data.guardrails.config
is_pull_request if not is_null(input.pull_request)
tracked_branch if input.push.branch in config.tracked_branches
supported_event if object.get(input.push, "event", "PUSH") in config.tracked_events

# Only configured branches and source-control events create apply-capable runs.
track if {
	tracked_branch
	supported_event
}

# Feature branches and pull requests produce plan-only proposed runs.
propose if {
	is_pull_request
	not tracked_branch
}

ignore if {
	not track
	not propose
}
