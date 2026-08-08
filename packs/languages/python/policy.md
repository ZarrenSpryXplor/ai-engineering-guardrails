# Python capability policy

- Determine the existing manager from `pyproject.toml`, locks, requirements, environment files, and repository commands before installing. Preserve uv, Poetry, PDM, pip-tools, Pipenv, or the established pip workflow.
- Use a project virtual environment; never install into system Python, use `--break-system-packages`, add `--trusted-host`, disable TLS, or replace lock formats.
- Preserve Ruff, Black, isort, mypy, Pyright, pylint, pytest, tox, and nox settings. Do not globally suppress a local error or rewrite a full lock without justification.
- Run the narrowest applicable test/check first. Never publish with twine, uv, Poetry, or an equivalent tool, and preserve database migration history.
