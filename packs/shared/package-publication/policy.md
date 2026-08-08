# Package publication boundary

- Package and release publication remains a human-controlled external action. Agents may prepare, pack, sign locally where separately authorised, inspect, and verify a release candidate, but must never upload or publish it.
- Deny Maven deploy/release goals, Gradle publishing/release tasks, NuGet push, twine/uv/Poetry publication, npm/pnpm/Yarn publication, Helm push, and equivalent release creation/upload commands.
- Never print registry credentials or reinterpret “finish the release” as authority to publish.
