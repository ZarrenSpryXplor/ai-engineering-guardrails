package spacelift

import rego.v1

test_prd_requires_human_approval if {
  fixture := {"stack":{"labels":["lifecycle:prd"],"space_id":"example-prd-space"},"run":{"type":"TRACKED","user_provided_metadata":["change-ticket=SYNTHETIC-1","change-owner=example-team"]},"reviews":{"current":{"approvals":[]}}}
  not approve with input as fixture
  not reject with input as fixture
}

test_prd_sensitive_team_can_approve if {
  fixture := {"stack":{"labels":["lifecycle:prd"],"space_id":"example-prd-space"},"run":{"type":"TRACKED","user_provided_metadata":["change-ticket=SYNTHETIC-1","change-owner=example-team"]},"reviews":{"current":{"approvals":[{"session":{"teams":["example-sensitive-approvers"]},"identity":{"ulid":"reviewer-id"}}]}}}
  approve with input as fixture
  not reject with input as fixture
}

test_prd_missing_metadata_rejected if {
  fixture := {"stack":{"labels":["lifecycle:prd"],"space_id":"example-prd-space"},"run":{"type":"TRACKED","user_provided_metadata":[]},"reviews":{"current":{"approvals":[]}}}
  reject with input as fixture
}

test_prd_self_approval_rejected_if_identities_are_available if {
  fixture := {"stack":{"labels":["lifecycle:prd"],"space_id":"example-prd-space"},"run":{"type":"TRACKED","creator_identity":{"ulid":"same-id"},"user_provided_metadata":["change-ticket=SYNTHETIC-1","change-owner=example-team"]},"reviews":{"current":{"approvals":[{"session":{"teams":["example-sensitive-approvers"]},"identity":{"ulid":"same-id"}}]}}}
  reject with input as fixture
}
