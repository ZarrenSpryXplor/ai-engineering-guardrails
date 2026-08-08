# API and schema compatibility policy

- Identify consumers, versioning policy, compatibility direction, generated outputs, and the repository's native compiler or checker before changing a public contract.
- Review removed fields/endpoints, changed requiredness, incompatible type/format changes, enum narrowing, response and error semantics, event evolution, GraphQL nullability, and Protobuf field-number reuse. Reserve removed Protobuf names and numbers.
- Change authoritative schemas rather than generated clients or rendered documentation. Regenerate only through existing repository tooling and review the complete generated diff.
- Use native compatibility tools when present. JSON parsing or textual comparison is not semantic OpenAPI, GraphQL, Protobuf, AsyncAPI, Avro, or event compatibility validation; report that limitation explicitly.
