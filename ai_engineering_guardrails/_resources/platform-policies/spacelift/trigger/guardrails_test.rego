package spacelift

import rego.v1

test_only_configured_finished_tracked_runs_trigger if {
  fixture := {"run":{"type":"TRACKED","state":"FINISHED"},"stack":{"id":"example-source-stack"}}
  "example-dependent-stack" in trigger with input as fixture
}

test_tasks_do_not_trigger if {
  fixture := {"run":{"type":"TASK","state":"FINISHED"},"stack":{"id":"example-source-stack"}}
  count(trigger with input as fixture) == 0
}
