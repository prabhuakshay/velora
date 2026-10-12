# CI Image Build Cache

CI's `image` job builds the prod target with a plain `docker build` and no layer cache. It does not use Buildx with the `type=gha` cache the release workflow uses.

## Why this is out of scope

The job only checks that the Dockerfile still builds. A cold build takes about 30 seconds, and it runs in parallel with the `check` job (lint, types, tests), which takes several minutes. Caching it would not shorten CI.

It also can't share the release cache. A GitHub Actions run can read caches from its own ref and from the default branch only. The release workflow runs on a tag, so its cache is invisible to pushes on main and to PRs. The reverse (main writes, the release reads) works, but the release already waits for a full CI run first, so saving around 30 seconds on its build doesn't matter.

Reconsider if the `image` job becomes the slowest job in CI.

## Prior requests

- #120: "CI image job doesn't share the release workflow's build cache"
