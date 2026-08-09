# GENERATED — DO NOT EDIT
# Canonical source: platform-policies/spacelift/login/guardrails.rego

package spacelift

import rego.v1

config := data.guardrails.config

admin if {
	some team in input.session.teams
	team in config.admin_teams
}

allow if input.session.idp_subject in config.allowed_idp_subjects

deny if {
	not admin
	not allow
}
