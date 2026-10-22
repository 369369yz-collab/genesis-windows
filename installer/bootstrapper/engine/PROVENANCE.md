# Embedded 7-Zip engine — provenance

The bootstrapper embeds the **official 7-Zip x64 console engine**,
extracted byte-for-byte from the official distribution installer
`7z2605-x64.exe` (7-Zip 26.05, 7-zip.org) already held in the persistent
tool store at `~/workspace/genesis_full_setup/tools/x64sfx/7z2605-x64.exe`.
No file was modified; extraction was a plain `7zz e` of two members.

| File | Bytes | SHA-256 | PE machine |
|---|---|---|---|
| `7z.exe` | 577,536 | `94205cfc054dd3bbeb978905bc619a65b3f04e9e73bb2717841110b6f46d962e` | 0x8664 |
| `7z.dll` | 1,908,736 | `78bf6b668d75801e3aa180b4ccb16e6d8395fba80dec8a065055bb6f8dfabb82` | 0x8664 |

7-Zip is free software (LGPL / BSD, see the 7-Zip license); redistribution
of the unmodified console binaries is permitted. `build_bootstrapper.sh`
verifies both pins before compiling and fails closed on any mismatch.
