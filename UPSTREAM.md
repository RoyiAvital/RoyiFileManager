# Upstream maintenance

`RoyiFileManager` preserves the public `fman` Python namespace so existing
plug-ins continue to work and upstream application changes remain easy to
merge.

When this source archive is placed in a Git repository, configure remotes as
follows:

```powershell
git remote add upstream https://github.com/mherrmann/fman.git
git fetch upstream
```

Merge upstream changes into a temporary integration branch. Keep fork changes
grouped by purpose: Windows-only build, portable storage, branding, offline
services, and Windows tests. Do not mechanically rename the `fman` package,
its public classes, or existing configuration keys.

Before publishing this fork, rotate every credential that was present in the
original source archive and use repository or CI secret storage for any new
release credentials. Never commit private keys or signing passwords.