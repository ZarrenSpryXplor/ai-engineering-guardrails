# .NET capability policy

- Inspect solutions, projects, `global.json`, `Directory.Build.*`, `Directory.Packages.props`, NuGet configuration, local tool manifests, and repository scripts first.
- Honour central package management and solution conventions. Preserve target frameworks, nullable context, language versions, analyzers, warning configuration, package sources, and credentials boundaries.
- Test the affected project before the applicable solution and use existing formatting/analyzer tools.
- Never add NuGet credentials, alter sources to bypass restore failures, push packages, install global tools/workloads, clear all NuGet caches as a first repair, execute database updates, or regenerate migration history as a shortcut.
