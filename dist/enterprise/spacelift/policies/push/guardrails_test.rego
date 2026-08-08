# GENERATED — DO NOT EDIT
# Canonical source: platform-policies/spacelift/push/guardrails_test.rego

package spacelift

import rego.v1

test_tracked_branches_are_configured if count(data.guardrails.config.tracked_branches) > 0

test_events_are_configured if count(data.guardrails.config.tracked_events) > 0
