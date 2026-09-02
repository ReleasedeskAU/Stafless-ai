<a name="readme-top"></a>

# StaffLess AI

**StaffLess AI** is ReleaseDesk Everywhere’s search and RAG engine. This
repository is our MIT-only fork of [onyx-foss](https://github.com/onyx-dot-app/onyx-foss).
The upstream project is Onyx; compose names, API paths, and `ONYX_*`
environment variables stay as that software ships them.

Display text in this fork uses **StaffLess AI**. Internal identifiers are
not renamed, so future `git fetch upstream` merges stay small. See
[UPSTREAM-SYNC.md](UPSTREAM-SYNC.md) for remotes and how to pull foss
updates.

## License

MIT (same as onyx-foss). This tree does **not** include Onyx Enterprise
(`backend/ee` is an empty stub).

## Deploy

Do not pull Docker Hub `onyxdotapp/onyx-backend` — those images are built
from the main Onyx repo and include Enterprise code. Build the backend
from **this** tree (`--target runtime`). Prep files live in the
ReleaseDesk repo under `docs/onyx-deploy/`.

## Syncing from upstream

```bash
git remote -v
# origin    https://github.com/ReleasedeskAU/Stafless-ai.git
# upstream  https://github.com/onyx-dot-app/onyx-foss.git  (fetch only)
```

Never push to `upstream`. Full process: [UPSTREAM-SYNC.md](UPSTREAM-SYNC.md).
