# GENERATED — DO NOT EDIT
# Canonical source: platform-policies/spacelift/notification/guardrails_test.rego

package spacelift

import rego.v1

test_protected_unconfirmed_run_routes_to_inbox if {
  fixture := {"run_updated":{"stack":{"id":"example-stack","labels":["lifecycle:prd"]},"run":{"id":"example-run","type":"TRACKED","state":"UNCONFIRMED"}}}
  count(inbox with input as fixture) == 1
}

test_nonproduction_finished_run_is_not_routed if {
  fixture := {"run_updated":{"stack":{"id":"example-stack","labels":["lifecycle:dev"]},"run":{"id":"example-run","type":"TRACKED","state":"FINISHED"}}}
  count(inbox with input as fixture) == 0
}
