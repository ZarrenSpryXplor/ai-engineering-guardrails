package spacelift

import rego.v1

config := data.guardrails.config
changes := object.get(input, "terraform", {"resource_changes": []}).resource_changes
proposed := object.get(object.get(input, "spacelift", {}), "run", {"type": "PROPOSED"}).type == "PROPOSED"

deletion_or_replacement(resource) if {
	"delete" in resource.change.actions
}

replacement(resource) if {
	"delete" in resource.change.actions
	"create" in resource.change.actions
}

critical_change(resource) if resource.type in config.critical_resource_types

privilege_broadening(resource) if {
	resource.type in config.privilege_sensitive_resource_types
	some action in resource.change.actions
	action in {"create", "update"}
}

public_exposure(resource) if {
	resource.type in config.public_exposure_resource_types
	after := object.get(resource.change, "after", {})
	object.get(after, "publicly_accessible", false)
}

public_exposure(resource) if {
	resource.type in config.public_exposure_resource_types
	after := object.get(resource.change, "after", {})
	object.get(after, "public_network_access_enabled", false)
}

disallowed_region(resource) if {
	after := object.get(resource.change, "after", {})
	region := object.get(after, "region", object.get(after, "location", ""))
	region != ""
	not region in config.allowed_regions
}

disallowed_account(resource) if {
	after := object.get(resource.change, "after", {})
	account := object.get(after, "account_id", "")
	account != ""
	not account in config.allowed_account_ids
}

deny contains sprintf("proposed run deletes or replaces %s", [resource.address]) if {
	proposed
	some resource in changes
	deletion_or_replacement(resource)
}

warn contains sprintf("tracked run deletes or replaces %s; human approval is required", [resource.address]) if {
	not proposed
	some resource in changes
	deletion_or_replacement(resource)
}

deny contains sprintf("proposed run replaces %s", [resource.address]) if {
	proposed
	some resource in changes
	replacement(resource)
}

deny contains sprintf("protected resource type changed: %s", [resource.type]) if {
	some resource in changes
	critical_change(resource)
	deletion_or_replacement(resource)
}

deny contains sprintf("privilege-sensitive resource changed: %s", [resource.address]) if {
	some resource in changes
	privilege_broadening(resource)
}

deny contains sprintf("resource becomes publicly reachable: %s", [resource.address]) if {
	some resource in changes
	public_exposure(resource)
}

deny contains sprintf("resource targets a disallowed region: %s", [resource.address]) if {
	some resource in changes
	disallowed_region(resource)
}

deny contains sprintf("resource targets a disallowed account: %s", [resource.address]) if {
	some resource in changes
	disallowed_account(resource)
}

deny contains sprintf("resource change count %d exceeds configured maximum %d", [count(changes), config.maximum_resource_changes]) if count(changes) > config.maximum_resource_changes

warn contains sprintf("resource change count %d exceeds configured warning threshold %d", [count(changes), config.warning_resource_changes]) if {
	count(changes) > config.warning_resource_changes
	count(changes) <= config.maximum_resource_changes
}
