# Java capability policy

- Inspect Maven/Gradle manifests, modules, wrappers, toolchains, and repository scripts before choosing commands. Prefer `./mvnw`/`mvnw.cmd` and `./gradlew`/`gradlew.bat`; never switch build systems incidentally.
- Preserve source/target levels, Java toolchains, compiler settings, Maven scopes, Gradle configurations, annotation processors, repositories, wrapper versions, lockfiles, and verification settings.
- Test the affected module first, then the applicable aggregate build. A skipped test is not verification.
- Never add insecure repositories, weaken TLS/checksums/signatures, clear all of `~/.m2` or `~/.gradle`, deploy Maven artifacts, or run Gradle publication/release tasks.
