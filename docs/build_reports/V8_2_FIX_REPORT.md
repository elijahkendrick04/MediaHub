# V8.2 — Six-issue fix pass

**Live at https://mediahub.pplx.app** · 346 unit tests passing · live verification PNG at `/tmp/v82_verification.png`

## All six issues fixed

### 1. ZIP files not reading correctly — FIXED
Root cause: `interpreter/hytek_parser.py::_parse_c1` used `_safe_str(line, 7, 45)` which slurped the team_name AND its short-code together. Fixed by using width 30 for team_name and adding a separate 8-char short_name field. Verified: Garioch ZIP now produces 26 clean club names ("Aberdeen ASC", "Cults Otters", etc.) and 1188 swims with clean swimmer names ("Emma Assady", "Cameron Jupp", etc.).

### 2. Caption quality — FIXED (downstream of #1)
The "wrong / extra name" issue was a downstream effect of the C1 width bug — clubs were being parsed as `"Aberdeen ASC                  Aberdeen"` and getting injected into captions. With the C1 fix in place, captions now render clean: "Cameron Jupp wins gold medal (1st) in 400m Individual Medley (SC) — 5:15.37 at Garioch PreSNAGS Meet". No extra names, no smushed text.

### 3. Upload page shows ONLY file input — FIXED (verified live)
The `/upload` form now contains a single `<input type="file" name="file">` plus a Continue button. All branding/club-picking moved to the configure page. Verified live: form fields = `[{tag:INPUT, type:file, name:file}]`.

### 4. Configure dropdown only shows clubs from THIS file — FIXED (verified live)
Verified live with Garioch ZIP: dropdown lists exactly the 26 clubs that attended (Aberdeen ASC, Aberdeen Dolphin, Alford Otters, Arbroath St Thomas, Banchory, Bon Accord, Bridge of Don, Broch, Cults Otters, ...) with no random/cached clubs leaking in.

### 5. "Club profiles" tool removed — FIXED
- All `/profiles` routes deleted (grep confirms `@app.route.*profiles` returns 0 hits)
- `seed_default_profiles()` removed from boot
- Branding is now a required step on the configure page (logo OR colours must be filled in; an inline error fires otherwise)
- Per-run brand kits at `data/brand_kits/<run_id>.json` remain (this is correct — they're per-run, not per-profile)

### 6. Logo + photos library wired into graphic generation — FIXED (verified live)
- Configure page has BOTH a logo file input AND a multi-file `club_photos` input
- Submit saves photos to `runs_v4/<run_id>/media/` AND registers them in the V8 media library so the selector picks them
- The selector now prefers user-uploaded photos when picking the primary photo for a graphic
- The logo extraction works: verified live with a synthetic green Cults Otters logo, the rendered graphic uses dark green as the dominant background

## Live verification (real flow, not synthetic)

Picked a meet I hadn't role-played before (Garioch PreSNAGS) and a club not yet used (Cults Otters):

1. `/upload` → only file input, no club fields
2. Uploaded `samples/learning_corpus/level2/2025_03_garioch_pre_snags/results.zip`
3. Redirected to `/upload/configure?run_id=...`
4. Dropdown showed 26 Garioch clubs only
5. Picked **Cults Otters**, uploaded synthetic green logo, ticked "Use logo colours"
6. Pipeline ran in ~30s → recognition page populated for Cults Otters swimmers
7. First card: "Cameron Jupp · 400m Individual Medley (SC) · 5:15.37 GOLD" (clean — no extra names)
8. Clicked "✦ Create graphic" → real PNG returned in 15s, 1080×1350
9. Rendered graphic shows: extracted dark-green colour scheme, "CAMERON" name + "JUPP" surname watermark, "400m Individual Medley (SC)", "GOLD 1ST · 5:15.37", "CO" logo monogram + "Cults Otters · Garioch PreSNAGS Meet" footer

PNG saved to `/tmp/v82_verification.png` (968 KB).

## Tests
346/346 passing (excluding slow corpus + smoke tests).
