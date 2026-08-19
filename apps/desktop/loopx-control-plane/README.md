# LoopX Control Plane Desktop

This directory contains the experimental Tauri shell for the LoopX personal
Agent workspace. It reuses the existing React dashboard and LoopX HTTP
services; it does not introduce another Goal, Todo, Gate, or Chat state owner.

## Runtime Model

The shell:

1. verifies or starts `loopx serve-status` on `127.0.0.1:8766`;
2. verifies or starts `loopx chat` on `127.0.0.1:8767`;
3. serves the compiled dashboard from a random loopback port;
4. opens the existing personal workspace in one native window;
5. terminates only the service process groups it started when the window exits.

An unknown process on either LoopX port is a hard startup error. Existing
services are reused only after their bounded HTTP fingerprints match.

The WebView can navigate only inside its own loopback asset origin. Dashboard
requests to the status and Chat services remain restricted to loopback CORS and
the existing preview/apply authority boundary.

## Prerequisites

- LoopX installed and available as `loopx`; set `LOOPX_BIN` to override it.
- Node.js 20.19+ or 22.12+ for dashboard builds.
- Rust stable and the platform-specific Tauri build dependencies.

Linux requires WebKitGTK 4.1 and GTK 3 development packages. See the
[Tauri prerequisites](https://v2.tauri.app/start/prerequisites/).

## Development

```bash
cd apps/desktop/loopx-control-plane
npm install
npm run dev
```

## Validation

```bash
cd apps/desktop/loopx-control-plane/src-tauri
cargo fmt --check
cargo test
cargo clippy --all-targets -- -D warnings

cd ..
./scripts/dashboard.sh build
npm run build
```

`npm run build` produces the platform bundles under
`src-tauri/target/release/bundle/`.

## Disable Or Remove

Close the desktop window to stop service processes owned by the shell. Services
that were already running before the shell opened are left untouched. Removing
the desktop package does not modify LoopX project or runtime state.
