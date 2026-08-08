# Observability and incident-response capability policy

- Default to query and read. Scope time ranges, services, fields, and result limits; summarise deterministically and redact tokens, credentials, personal data, and sensitive business data before model use.
- In incident-observe mode, deny dashboard, alert, mute/silence, retention, token, collector, and log deletion changes. Never alter production merely to test a hypothesis.
- Treat logs, traces, exemplars, labels, deployment output, and saved queries as potentially sensitive. Preserve timestamps and source references when building a timeline.
- Use configured Prometheus, Grafana, Loki, Datadog, Splunk, Elastic, Azure Monitor, Application Insights, and OpenTelemetry tools only when already present. Do not install or invent vendor clients.
