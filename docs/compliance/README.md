# docs/compliance/ — UK legal compliance records

The paper trail for selling MediaHub to UK clubs lawfully.

- **`DPIA.md`** — the Data Protection Impact Assessment draft (ICO structure):
  what data flows where, the risks of processing children's data at scale,
  and the mitigations built into the product. Needs controller sign-off.
- The audit that drives everything: [`../COMPLIANCE_AUDIT.md`](../COMPLIANCE_AUDIT.md).
- What was built and what remains: [`../COMPLIANCE_HANDOVER.md`](../COMPLIANCE_HANDOVER.md).
- The customer-facing legal documents themselves live in code
  (`src/mediahub/web/legal.py`) so they can never drift from the routes that
  serve them (`/terms`, `/privacy`, `/cookies`, `/dpa`).
