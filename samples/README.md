# samples

Files bundled for two zero-setup paths that need a meet results file on hand
with **no real people** in it:

- the **public** try-before-signup demo (`/try`), which ships on a public
  surface; and
- the signed-in **first-run sample pack** (U.4) — `POST /onboarding/sample`
  runs the real pipeline on this same file, stamped to the user's own org so
  the cards come out in their brand, as the fast "see it work end-to-end"
  onboarding path.

Because both surface it, `demo-meet-results.pdf` must contain no real people:
it is a synthetic meet (fictional swimmers, fictional clubs) generated
deterministically by `scripts/make_demo_sample.py`. See
`docs/compliance/CHILDRENS_CODE_PASS.md`.

Real-world results files used by the parser's regression tests live in
`sample_data/` and `samples/learning_corpus/` instead — they are engineering
fixtures for parser accuracy, never served to visitors.
