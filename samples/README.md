# samples

Files bundled for the **public** try-before-signup demo (`/try`). Everything
in here ships on a public surface, so it must contain **no real people** —
`demo-meet-results.pdf` is a synthetic meet (fictional swimmers, fictional
clubs) generated deterministically by `scripts/make_demo_sample.py`. See
`docs/compliance/CHILDRENS_CODE_PASS.md`.

Real-world results files used by the parser's regression tests live in
`sample_data/` and `samples/learning_corpus/` instead — they are engineering
fixtures for parser accuracy, never served to visitors.
