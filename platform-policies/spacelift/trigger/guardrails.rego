package spacelift

import rego.v1

config := data.guardrails.config

trigger contains target if {
  input.run.type == "TRACKED"
  input.run.state == "FINISHED"
  targets := object.get(config.trigger_targets, input.stack.id, [])
  some target in targets
}
