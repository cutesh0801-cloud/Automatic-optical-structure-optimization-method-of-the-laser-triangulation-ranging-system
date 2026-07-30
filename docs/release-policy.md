# Release policy

Scheimpflug OptiMeter releases are deliberate and append-only. A push to
`main` or to a tag never creates a release. Version releases are started only
with `workflow_dispatch` from `main`. A narrowly scoped
`release/build-YYYYMMDD.N` branch creation may start a maintenance release only
when that branch is an exact SHA alias of the latest remote `main`.

Routine fixes, refinements, and small feature additions are maintenance work:
each completed maintenance update must be published as a new
`build-YYYYMMDD.N` prerelease, but it must not change the application version
or create a product-version release. A version is changed only for a large,
coherent update whose user-visible scope warrants a new product release, and
only after the version checklist below is explicitly reviewed. “Maintenance”
here describes release policy and must not be confused with a SemVer `MINOR`
number.

## Release classes

| Class | Purpose | Tag | App version | GitHub release |
| --- | --- | --- | --- | --- |
| Maintenance | Publish each completed routine fix, refinement, or small feature without changing the released app version | `build-YYYYMMDD.N` | Must remain at an existing released `pyproject.toml` version | Prerelease |
| Version | Publish a deliberate application version | Exactly `v<project.version>` from `pyproject.toml` | Changed and reviewed before dispatch | Normal release |

`N` starts at 1 and increases when more than one maintenance build is needed
for the same date. The date must be a real calendar date. A maintenance build
is allowed only when the corresponding `v<project.version>` tag already exists
in the dispatched commit's history and has a published, non-prerelease GitHub
release. It cannot be used as an indirect version release.

## Workflow immutability and server hardening

The workflow provides append-only behavior through its own release path: it
refuses existing tags, releases, and assets, repeats the collision checks
immediately before publication, and has no update, delete, or clobber command.
It cannot prevent a repository administrator from modifying a release through
another interface.

Enabling GitHub's Immutable Releases setting is strongly recommended as an
administrator follow-up. That repository-level protection locks release tags
and assets after publication. Follow GitHub's
[release immutability instructions](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/establish-provenance-and-integrity/prevent-release-changes)
when administrative access is available.

- Never move, force-push, reuse, or delete a published release tag.
- Never edit a published release to replace its binaries or checksums.
- Never use `gh release upload --clobber` or an equivalent overwrite option.
- Never delete and recreate a release to make corrected assets appear under
  the same tag.
- If a maintenance build is wrong, correct the source and issue the next
  `build-YYYYMMDD.N` prerelease.
- If a version release is wrong, make the appropriate version change and
  issue a new version release.

The workflow checks for an existing local/fetched tag, remote tag, and GitHub
release both before building and immediately before publishing. It fails
closed when absence cannot be proven. `gh release create` receives new assets
only; there is no update or asset-clobber path.

## Maintenance release procedure

Before dispatch:

1. Confirm the completed maintenance change has been reviewed and merged, and
   the selected ref is the current `main` containing only the intended release
   scope since the previous build.
2. Confirm `project.version` in `pyproject.toml` has not changed from the
   already published version.
3. Confirm the corresponding `v<project.version>` tag is an ancestor of
   `main` and its GitHub release is neither a draft nor a prerelease.
4. Choose the next unused `build-YYYYMMDD.N` tag.
5. Review the generated-release-note range and ensure it describes only the
   intended maintenance changes.

An authorized maintainer can dispatch the `Release` workflow from `main` with:

- `release_type`: `maintenance`
- `release_tag`: the new `build-YYYYMMDD.N` value
- `confirmation`: `RELEASE_MAINTENANCE`

When manual dispatch is unavailable, an authorized GitHub integration may
create a new branch named
`release/build-YYYYMMDD.N` at the exact current remote `main` SHA. For this
one-shot branch-creation event only, the workflow derives:

- `release_type`: `maintenance`
- `release_tag`: the branch name with `release/` removed
- `confirmation`: internal `RELEASE_MAINTENANCE`

The workflow queries `refs/heads/main` from `origin` and requires its SHA to
equal `GITHUB_SHA`. A branch with an extra commit, an outdated `main` commit,
or any other name fails before the build starts. This branch mechanism cannot
start a version release. Updating an existing release branch does not trigger
publication; every maintenance build requires a new date/sequence branch.

The resulting GitHub release is always marked as a prerelease.

## Version release checklist

Do not enter the confirmation phrase until every item is complete:

1. The release commit is reviewed, merged, and is the current `main` head.
2. `project.version` in `pyproject.toml` is the intended version and the
   proposed tag is exactly `v<project.version>`, including spelling, case, and
   punctuation.
3. Runtime-visible version values and packaging metadata have been checked
   against `project.version`.
4. CI is green for the release commit, including lint, formatting, automated
   tests, public-source verification, Windows packaging, and portable smoke
   testing where available.
5. User-visible behavior, known limitations, upgrade impact, and generated
   release notes have been reviewed.
6. No private PDF, workbook, proprietary drawing, local path, credential, or
   machine-specific file is tracked or included in the package.
7. The proposed tag and GitHub release do not already exist.
8. The two generated assets have stable names:
   `Scheimpflug-OptiMeter-windows-x64.zip` and
   `Scheimpflug-OptiMeter-windows-x64.zip.sha256`.
9. GitHub's Immutable Releases setting is enabled when an administrator can
   configure it, or the missing administrator follow-up is explicitly
   recorded.
10. A maintainer accepts that the tag, release, binaries, and checksum will not
   be replaced after publication.

Dispatch the `Release` workflow with:

- `release_type`: `version`
- `release_tag`: exactly `v<project.version>`
- `confirmation`: `RELEASE_VERSION`

The exact, case-sensitive `RELEASE_VERSION` phrase is the final explicit
publication confirmation. A typo or tag/version mismatch stops the workflow
before dependencies are installed or artifacts are built.

## Preserved build pipeline

After policy validation, both release classes use the same release-quality
pipeline:

1. install the locked Python 3.12 environment;
2. verify no private source documents are tracked;
3. run Ruff lint and formatting checks;
4. run the test suite with the Qt and Matplotlib headless backends;
5. build the PyInstaller application;
6. smoke-test the portable application;
7. assemble the ZIP and SHA-256 assets; and
8. create a new GitHub release and tag at the selected commit;
9. verify the published tag target, draft/prerelease state, and the exact
   names, byte sizes, upload state, and server SHA-256 digest of both assets.

Failures before the publish step create no release. Publication itself uses
multiple GitHub API calls: create a draft, upload assets, and publish. A
failure during those calls can leave a tag, draft, partial asset set, or
published release. Post-publication verification can also fail after a release
is already visible. The workflow never rolls back or overwrites these objects.

## Partial publication runbook

If the publish command or post-publication verification fails:

1. Record the failed workflow run URL, commit SHA, requested tag, and local
   asset checksums.
2. Inspect both the tag and release without modifying them:

   ```powershell
   git ls-remote --tags origin "refs/tags/TAG" "refs/tags/TAG^{}"
   gh release view TAG --json tagName,targetCommitish,isDraft,isPrerelease,isImmutable,assets
   ```

3. Do not blindly rerun, delete, retag, or upload with `--clobber`.
4. If neither tag nor release exists, the same request may be retried after
   confirming that the failure happened before publication.
5. If a maintenance tag or any associated release exists, treat the tag as
   consumed, correct the cause, and use the next `build-YYYYMMDD.N`.
6. If a version tag or associated release exists, stop and perform a release
   review. Published objects remain untouched; a corrected version uses a new
   application version and tag.
7. An unpublished draft left by a failed API sequence is an administrator
   incident. Preserve the audit evidence and obtain explicit repository-owner
   approval before any cleanup; the workflow does not clean it automatically.
