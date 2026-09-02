# Syncing StaffLess AI with onyx-foss

This repository is a full copy of [onyx-dot-app/onyx-foss](https://github.com/onyx-dot-app/onyx-foss)
with StaffLess AI overlay commits on top. Engine identifiers (`ONYX_*`,
compose names, API paths, Python/TS types) stay as upstream ships them.

**Never push to `upstream`.** Fetch only. This clone has `upstream` push
disabled (`git remote set-url --push upstream DISABLE`).

## Remotes

| Remote | URL | Use |
| --- | --- | --- |
| `origin` | `https://github.com/ReleasedeskAU/Stafless-ai.git` | Our fork. Push overlay commits here. |
| `upstream` | `https://github.com/onyx-dot-app/onyx-foss.git` | MIT-only Onyx mirror. Fetch only. |

```bash
git remote -v
# origin    …/ReleasedeskAU/Stafless-ai.git  (fetch + push)
# upstream  …/onyx-dot-app/onyx-foss.git     (fetch)
# upstream  DISABLE                          (push)
```

If you clone fresh:

```bash
git clone https://github.com/ReleasedeskAU/Stafless-ai.git
cd Stafless-ai
git remote add upstream https://github.com/onyx-dot-app/onyx-foss.git
git remote set-url --push upstream DISABLE
git fetch upstream
```

## Why `onyx-foss`, not `onyx-dot-app/onyx`

`onyx-foss` is a **one-way generated mirror**, not a git fork of
`onyx-dot-app/onyx`. It does **not** track `onyx` as a git remote.

How it is produced (in the **main** Onyx repo, not here):

1. `backend/scripts/make_foss_repo.sh` clones main Onyx, runs
   `git filter-repo` to drop `backend/ee` from history, rewrites LICENSE
   blobs to MIT, commits a stub `backend/ee/__init__.py`.
2. `.github/workflows/sync_foss.yml` runs that script daily and
   **`git push --force`** to `onyx-dot-app/onyx-foss` `main`.

There is no shared commit graph back to `onyx`. Tracking `onyx` as our
upstream would pull `backend/ee` (Enterprise) and dual-license history.
We track **foss** so MIT-only stays the default.

## Force-push warning (read before every sync)

Because foss **rewrites `main` with `--force` after `git filter-repo`**,
SHAs on `upstream/main` usually **do not** match yesterday’s foss `main`.
A textbook `git merge upstream/main` may:

- report unrelated histories, or
- produce a huge conflict set, or
- look like it succeeded while duplicating trees.

Treat foss as a **snapshot source**, not a stable shared branch. Our
overlay is a small file list (below). The repeatable 3-month process is
**replay the overlay onto a fresh foss snapshot**, not “hope merge is
clean.”

## Overlay files (ours — keep during sync)

Add paths here when the display rebrand (or other overlay) lands.

- `UPSTREAM-SYNC.md` — this document
- `README.md` — StaffLess AI fork readme (foss regenerates theirs on every force-push)

## Procedure A — try a normal merge first (fast path)

Use this when `git merge-base main upstream/main` prints a commit (histories
still share ancestry). That is uncommon after a foss force-push.

```bash
git checkout main
git fetch origin
git fetch upstream
git status                    # must be clean
git merge-base main upstream/main || echo "no shared base — use Procedure B"

git checkout -b sync/foss-$(date +%Y-%m-%d)
git merge upstream/main
```

Resolve conflicts:

- Prefer **upstream** for engine code you did not overlay.
- Prefer **ours** for overlay files listed above.
- Do not re-introduce `backend/ee` beyond foss’s stub `__init__.py`.

```bash
git push -u origin HEAD
# open a PR into main, or merge locally if that is your process
```

Never: `git push upstream`, `git push --force origin main` (unless you
explicitly intend to rewrite the fork), or `git reset --hard` on `main`
without a backup branch.

## Procedure B — replay overlay onto a new foss snapshot (usual path)

Use this when there is no merge-base, merge is unreadable, or foss has
force-pushed since our last sync.

```bash
git checkout main
git fetch origin
git fetch upstream
git status                    # must be clean

# Backup current fork main (includes overlay)
git branch backup/pre-foss-sync-$(date +%Y-%m-%d)

# Isolated branch at the new foss snapshot
git checkout -B vendor/onyx-foss upstream/main

# Branch from that snapshot to re-apply overlay
git checkout -b sync/foss-$(date +%Y-%m-%d)
```

Restore overlay files from the backup branch (repeat for each path in
the overlay list):

```bash
git checkout backup/pre-foss-sync-YYYY-MM-DD -- UPSTREAM-SYNC.md
# git checkout backup/pre-foss-sync-YYYY-MM-DD -- <other overlay paths>
git add UPSTREAM-SYNC.md
git commit -m "Restore StaffLess AI overlay on onyx-foss snapshot"
```

Sanity checks:

- `backend/ee/` is still only the foss stub (no Enterprise package).
- Overlay display strings (once added) are still StaffLess AI.
- `ONYX_*` env names, API paths, and compose image variables unchanged.

```bash
git push -u origin HEAD
```

Merge `sync/foss-…` into `main` after review. Delete the backup branch
only after you are sure the sync is good.

### Optional: keep overlay as patches

If the overlay grows, export it before Procedure B:

```bash
git log --reverse --pretty=format:%H main ^vendor/onyx-foss > /tmp/overlay-commits.txt
# or: git format-patch vendor/onyx-foss..main -o /tmp/staffless-overlay
```

Then on `sync/foss-…` (created from `upstream/main`):

```bash
git am /tmp/staffless-overlay/*.patch
```

Skip any patch that no longer applies; re-do that change by hand.

## What not to do

- Do not add `onyx-dot-app/onyx` as `upstream` (pulls `ee/`).
- Do not `git pull` from foss into `main` without a backup branch.
- Do not rename internal identifiers to make the UI say StaffLess AI —
  that makes every future sync worse. Display strings only.
- Do not copy `backend/ee` from the main Onyx repo into this fork.

## After a successful sync

1. Update this file if overlay paths changed.
2. Rebuild the backend image from **this** tree (`--target runtime`); do
   not pull Hub `onyxdotapp/onyx-backend` (that image is main Onyx + `ee`).
3. Note the foss commit you synced: `git rev-parse upstream/main`.
