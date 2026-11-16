# Security maintenance

`security.yml` audits the locked Windows dependency graph (all groups, including CPU/CUDA/Vulkan)
with uv and scans fetched Git history with Gitleaks. It runs on pushes, pull requests, weekly and
on demand. Releases require both jobs to pass. Tool versions/actions and the Gitleaks binary hash
are pinned; logs redact detected secret values. These scans need no provider credentials.
Update the scanner pins as well as application dependencies when reviewing advisories.

Local equivalents, with uv 0.13.8 and Gitleaks 8.30.1:

```powershell
uv audit --locked --python-platform x86_64-pc-windows-msvc --python-version 3.12
gitleaks git --redact --log-opts="--all" .
```

Git scanning covers committed history. Scan proposed files too before committing; never upload
personal preferences, credentials, caches or model files as scan artifacts. A successful scan is
not proof that every secret or vulnerability is detectable. Rotate an exposed credential first;
removing it from the latest revision does not revoke it.

## Dependency boundaries

ChatGPT identity validation requires RSA signatures, the fixed issuer/audience, expiry, nonce and
required claims. It rejects all `crit` headers because this flow implements no critical JWS
extensions. PyJWT is pinned to 2.15.1; signed regression tokens exercise unknown/malformed critical
headers and accepted ordinary headers. See the [upstream advisory](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-752w-5fwx-jx9f).

DiskCache 5.6.3 remains a required import of the unmodified upstream llama-cpp-python package.
Its [pickle deserialization advisory](https://github.com/advisories/GHSA-w8v5-vhqr-4h9v) requires
reading attacker-modified cache data. DanteJP never enables llama.cpp's optional prompt/disk cache;
its own translation cache uses SQLite text values, not pickle. Native category-model verification
fails if a backend enables an upstream cache or constructs a DiskCache during model loading,
inference or switching. Keep that boundary when changing adapters.

There is currently no published DiskCache fix. `tool.uv.audit.ignore-until-fixed` scopes the
exception to this advisory and reports it again once a fix is listed. This is an exposure decision,
not a claim that the dependency is patched. Reassess it on upstream changes; never enable that
cache under the exception or replace upstream packaging with a local shim.

## Repository and publisher setup

After creating the GitHub repository, enable dependency alerts, private vulnerability reporting
and secret scanning/push protection where available. Protect the default branch and release tags;
require fast checks and both security jobs. Verify these settings in GitHub: workflow files alone
cannot configure or prove them. See [GitHub security settings](https://docs.github.com/en/code-security/getting-started/quickstart-for-securing-your-repository).

The portable EXE is unsigned. SHA-256 sidecars detect changed bytes but do not establish publisher
identity. Production Authenticode signing requires a publisher certificate or managed signing
service. When configured, sign and verify the EXE after PyInstaller and before ZIP/checksum creation,
and test the signed artifact. Keep signing credentials in a protected release environment and
unavailable to pull requests. See [Microsoft SignTool](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool).
