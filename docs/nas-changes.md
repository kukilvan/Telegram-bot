# Changes for the NAS

For the NAS project and its update command (ADR 0017). An update of the app on the NAS is a rebuild of a `master` commit; migrations of the database run by themselves at start, after a copy. This file lists, newest first, every change that needs **more than that rebuild**, or that the NAS copy of the compose file must follow:

- a new, renamed or removed `.env` name (with its meaning and whether it is required);
- a change to `docker-compose.yml` (the NAS repeats its load-bearing parts in its own `compose.yaml`);
- a runtime setting of the `Dockerfile` (`ENV`, `EXPOSE`, `HEALTHCHECK`, `CMD`, a `USER` line);
- a one-off step on the NAS.

The session that makes such a change adds the entry in the same commit (`docs/workflow.md`, «End of a session»). The update command can compare this file, `docker-compose.yml` and `.env.example` between the running commit and the new one (on the PC, with git) and stop to show what changed instead of deploying.

Entry format: `## <date> — <stage or ticket>`, then what to do on the NAS; «Nothing to do» when the entry only announces.

## 2026-11-25 — answer to the NAS project (7.3)

Nothing to do; announced because the build changed:
- The image installs the packages from `requirements.lock` (exact versions with hashes, `pip install --require-hashes`), not from `requirements.txt`.
- The base image is pinned by an exact tag and its digest (`python:3.12.16-slim@sha256:…`), the Dockerfile frontend too (`docker/dockerfile:1.29@sha256:…`). A newer base image comes only by an entry here.
- The Google Drive archive is made at LZMA2 preset 6 instead of 9 (at most about 100 MiB of memory); old archives open as before.
- `docker-compose.override.example.yml`: the example path is `/volume1/…` (the HDD mirror on the owner's NAS).
