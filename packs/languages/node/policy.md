# Node.js, JavaScript, and TypeScript capability policy

- Select the package manager from `package.json#packageManager`, repository configuration, lockfile evidence, then explicit override. Never mix npm, pnpm, and Yarn.
- Preserve manager major version, lockfiles, workspace boundaries, TypeScript strictness/target/module settings, ESLint and test settings. Prefer repository scripts and local binaries.
- Prefer reproducible repository-compatible installs (`npm ci`, frozen pnpm, immutable Yarn). Inspect unfamiliar lifecycle scripts before execution.
- Never globally install packages, publish, run unpinned remote execution through npx/npm exec/pnpm dlx/yarn dlx, force `npm audit fix`, disable type/lint checks, or update snapshots blindly.
