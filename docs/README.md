# docs

The detailed manual for engineers — how the system is built, how an upload flows
through it, and how to deploy it.

New here and not a coder? Read `../START_HERE.md` and `../GLOSSARY.md` first; they
explain the project in plain English.

- **Compliance (data protection / GDPR):** the legal ground truth, open legal
  questions, and (as the programme progresses) the data map, ROPA, gap
  analysis and DPIA live under [`compliance/`](compliance/) — start with
  [`compliance/README.md`](compliance/README.md).
- **Security (threat model / hardening evidence):** the threat model,
  TLS/at-rest/backup posture, and the ASVS L2 report with the residual-risk
  register live under [`security/`](security/) — start with
  [`security/README.md`](security/README.md).
- **Autotest (autonomous tester + fixer):** the harness lives in `../autotest/`
  (`../autotest/README.md`). Its trust + coverage benchmark, the implementation spec,
  and the change log are under [`autotest/`](autotest/) —
  [`AUTOTEST_BENCHMARK_AND_GAPS.md`](autotest/AUTOTEST_BENCHMARK_AND_GAPS.md),
  [`IMPLEMENTATION_PROMPT.md`](autotest/IMPLEMENTATION_PROMPT.md),
  [`AUTOTEST_CHANGES.md`](autotest/AUTOTEST_CHANGES.md).
