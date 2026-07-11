# ADR-0004 — App form: local web app served by the CLI, stdlib-only

**Status:** Accepted (best-judgment call under the 2026-07-10 run
authorization — review welcome; the alternatives below remain open)
**Date:** 2026-07-10

## Context

ADR-0003 made the app the primary interface and deferred its concrete form.
Candidates: local web app, TUI (textual), desktop shell (tauri/electron).
Constraints: local-first (PRD §15.3), WSL-friendly (the daily driver runs in
WSL2 with Fusion on Windows), minimal dependencies (repo convention:
requests-only core), single user.

## Decision

`hendley app` starts a **local web server bound to 127.0.0.1** and the user
opens it in a browser (on WSL2, the Windows browser reaches WSL localhost
directly). The server is Python **stdlib only** (`http.server`) — no Flask,
no `[app]` extra, zero new dependencies. The page is a single self-contained
HTML/vanilla-JS document served by the package; every action is a JSON API
call that maps 1:1 onto a library function. The API exchanges exactly the
versioned documents from ADR-0003 (Requirements BOM, resolution, approval
queue, snapshot).

Rationale:

- Zero-install, cross-platform, WSL-native — no packaging step at all.
- A single-user localhost JSON API over library calls is well within
  stdlib `http.server`; a framework buys nothing at this scale.
- The JSON documents were already the contract; the app is a renderer.

Trade-offs accepted:

- No hot frameworks/components — the UI is deliberately plain.
- If the app outgrows stdlib (websockets, streaming progress), promoting to
  FastAPI/uvicorn inside an `[app]` extra is a contained change: the API
  surface and documents stay, only the transport layer moves.

## Consequences

- `src/hendley/app/` holds the server + embedded page; `hendley app` gains
  `--port`, `--db`, `--outdir`, `--no-browser`.
- Bound to 127.0.0.1, no auth: same trust model as the CLI on the same
  machine (multi-user/remote access is explicitly out of v1 scope).
- Live JLC access is constructed lazily per request; the app starts and
  browses the knowledge base fine with no `.keys` present.
