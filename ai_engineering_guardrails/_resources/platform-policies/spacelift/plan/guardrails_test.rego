package spacelift

import rego.v1

test_configuration_has_ordered_thresholds if data.guardrails.config.warning_resource_changes < data.guardrails.config.maximum_resource_changes

test_configuration_protects_types if count(data.guardrails.config.critical_resource_types) > 0

test_configuration_has_security_boundaries if {
	count(data.guardrails.config.privilege_sensitive_resource_types) > 0
	count(data.guardrails.config.public_exposure_resource_types) > 0
	count(data.guardrails.config.allowed_regions) > 0
	count(data.guardrails.config.allowed_account_ids) > 0
}

test_public_exposure_is_denied if {
	fixture := {"spacelift": {"run": {"type": "PROPOSED"}}, "terraform": {"resource_changes": [{"address": "example.public", "type": "example_public_resource", "change": {"actions": ["update"], "after": {"publicly_accessible": true, "region": "example-region-1", "account_id": "000000000000"}}}]}}
	actual_denials := deny with input as fixture
	count(actual_denials) > 0
}
