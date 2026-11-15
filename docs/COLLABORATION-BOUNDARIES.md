# Daylight native and prototype collaboration boundaries

`prototypes/daylight-web/` is an intentional, actively reviewed design and interaction
reference for the native iOS/watchOS product. It is not a shipping Web, Android or
desktop product. Native-only product scope does not prohibit maintaining this prototype.
Any recommendation to stop maintaining or ignore its entire source directory is withdrawn.

- Native functionality work belongs in the existing iOS/watchOS project and SharedCore.
- The parallel UI implementation task is restricted to `prototypes/daylight-web/` and
  must not modify native Swift files or native business logic.
- Do not delete, relocate, stop, overwrite or refactor the prototype or its development
  setup as part of a native task. If work genuinely overlaps, explain the specific
  overlap to the user before modifying it.
- Do not add the prototype source directory to `.gitignore` or remove it from Git
  tracking without explicit user approval. Dependencies, build outputs and local
  tools may remain ignored.
- Treat unfamiliar working-tree changes as potentially belonging to the parallel
  task. Inspect them and preserve them. Do not use broad cleanup, reset or restore
  operations that could affect another task's work.
- If a native commit is later explicitly authorized, stage only the relevant named
  files. Do not broadly stage prototype changes into a native-functionality commit.
  This document does not authorize any commit or push.
- Prototype values and interactions may be simulated. The native implementation
  remains authoritative for business rules and persistence.
- Visual decisions are still under review. Do not automatically port prototype
  behavior or redesign native screens. Coordinate with the user before implementing
  an approved design in native code.

A dedicated design commit/PR, continued maintenance, eventual archival or removal of
the prototype are separate decisions for the user. Exclusion from a native simulator
acceptance gate is not an instruction to stop prototype development or user review.
