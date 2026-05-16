# Build Errors and Resolutions

## Resolved: Snap layout validation failure (cv-inference, 2026-05-15)

The original `cv-inference` snap attempted to use a `layout` declaration for
`/var/snap/cv-inference/common/config`. This path is under `/var/snap/` which
snapd manages directly - layouts cannot reference paths in this area.

**Error:**
```
Cannot pack snap: error: cannot validate snap "cv-inference": layout "/var/snap/cv-inference/common/config" in an off-limits area
```

**Resolution:** Removed the layout declaration entirely. `$SNAP_COMMON` is
inherently writable to the snap without needing a layout. The replacement
`ovms-engine` snap uses `$SNAP_COMMON/config` and `$SNAP_COMMON/models`
directly, exposed to the Greengrass snap via content interface slots.

**Lesson:** Never use snap layouts for paths under `/var/snap/`. Use
`$SNAP_COMMON` (writable, persists across refreshes) or `$SNAP_DATA`
(writable, per-revision) directly. For cross-snap access, use content
interface slots with `write:` directives.
