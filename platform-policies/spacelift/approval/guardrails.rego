package spacelift

import rego.v1

config := data.guardrails.config

production if {
  some label in input.stack.labels
  label in config.production_labels
}

production if input.stack.space_id in config.protected_space_ids

metadata_present(key) if {
  some item in input.run.user_provided_metadata
  startswith(item, sprintf("%s=", [key]))
  trim_prefix(item, sprintf("%s=", [key])) != ""
}

missing_metadata contains key if {
  production
  some key in config.required_change_metadata
  not metadata_present(key)
}

sensitive_approval if {
  some review in input.reviews.current.approvals
  some team in review.session.teams
  team in config.sensitive_approver_teams
}

self_approval if {
  creator := input.run.creator_identity.ulid
  some review in input.reviews.current.approvals
  review.identity.ulid == creator
}

task if input.run.type == "TASK"

approve if {
  not production
  not task
}

approve if {
  production
  count(missing_metadata) == 0
  sensitive_approval
}

approve if {
  task
  not production
  sensitive_approval
}

reject if count(missing_metadata) > 0

reject if self_approval
