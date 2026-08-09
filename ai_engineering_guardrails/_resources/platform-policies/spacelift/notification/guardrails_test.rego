package spacelift

import rego.v1

test_protected_unconfirmed_run_routes_to_inbox if {
	fixture := {"run_updated": {"stack": {"id": "example-stack", "labels": ["lifecycle:prd"]}, "run": {"id": "example-run", "type": "TRACKED", "state": "UNCONFIRMED"}}}
	actual_inbox := inbox with input as fixture
	count(actual_inbox) == 1
}

test_nonproduction_finished_run_is_not_routed if {
	fixture := {"run_updated": {"stack": {"id": "example-stack", "labels": ["lifecycle:dev"]}, "run": {"id": "example-run", "type": "TRACKED", "state": "FINISHED"}}}
	actual_inbox := inbox with input as fixture
	count(actual_inbox) == 0
}
