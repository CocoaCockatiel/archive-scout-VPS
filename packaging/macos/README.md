The universal macOS application is built by `scripts/build_macos.sh` on an Intel GitHub-hosted macOS runner using a Universal2 Python installation.

The release is a symlink-preserving ZIP named:

```text
ArchiveScout-macOS-Universal.zip
```

The script uses `ditto` to preserve bundle metadata and symbolic links. It extracts the completed ZIP into a clean temporary directory and verifies `base_library.zip`, all bundle links, and the code signature before publishing the package.
