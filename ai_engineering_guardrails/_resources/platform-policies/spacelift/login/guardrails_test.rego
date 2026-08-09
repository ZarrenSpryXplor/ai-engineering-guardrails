package spacelift

import rego.v1

test_configured_subject_allowed if {
	fixture := {"session": {"idp_subject": "user:example/example-user", "teams": []}}
	allow with input as fixture
	not deny with input as fixture
}

test_unknown_subject_denied if {
	fixture := {"session": {"idp_subject": "user:example/unknown", "teams": []}}
	deny with input as fixture
}
