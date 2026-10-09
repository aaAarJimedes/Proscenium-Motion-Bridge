# GitHub delivery

This project follows the workspace's single main branch and single release page policy. The primary branch is main; repository visibility remains public.

## Source synchronization

Use local git and gh with the existing user authentication. Inspect the repository, origin, current account, status, and staged changes before writes. Commit only the current task's changes, run relevant project checks, push normally, and verify the remote commit. Preserve uncommitted work, historical tags, and commits; do not force-push or rewrite history. Honor branch protection and any existing review requirements.

## Releases

The maintained release page uses v0.10.0 as its tag. Later validated versions may take over the page only after its complete version history, notes, and downloadable assets have been migrated.

Put current downloads first, followed by historical versions from newest to oldest. Each historical layer retains its original release notes, version identity, and real downloadable assets. Keep original Git tags for source history. Download and verify the actual bytes before retiring old pages; page titles and catalogs alone do not count as asset migration.

Before changing release history, fully paginate branches, tags, releases, and assets. Save the original release metadata, notes, assets, filename mapping, sizes, and SHA-256 hashes in this project's recovery directory. Serialize release operations and check that CI is idle. Do not overwrite asset names: keep versioned names, and use a stable archive-<version>- prefix for conflicting historical filenames without adding nested archive prefixes.

Upload the installable package, its build/checksum manifest, and any existing updater metadata as real assets. Do not introduce an updater where the project has none. Verify every original asset's target mapping, byte count, SHA-256, and actual download; rewrite notes to use preserved downloads. Retire superseded pages only within the user's authorized migration and after all data and recovery checks pass. Never use tag-cleanup options. Original page/asset IDs, timestamps, and old download URLs may change; record replacement URLs.

After migration, verify that there is one formal release page (or zero if no validated release exists), one primary branch, complete historical version layers and assets, unchanged historical tag refs, and working latest downloads. Stop on a mismatch, preserving the local version, old pages still present, and recovery assets. Never change access channels to bypass a platform approval block.

Credentials, tokens, keys, cookies, private input data, runtime databases, caches, and build environments must not enter source commits or release assets. Build outputs belong in the project's delivery directory; recovery materials and downloaded verification copies belong in its task-specific temporary directory.
