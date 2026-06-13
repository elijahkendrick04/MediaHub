"""MediaHub publishing layer.

Pluggable integrations that take an approved content card and queue it
for posting on an external platform. The user must connect an account
on /settings and then explicitly click Schedule on a card — there is no
autopost path through this module.

Currently supported:
    - scheduler: the "auto scheduling" provider for queueing posts across
      the user's connected social channels (Instagram, Twitter/X, Facebook,
      LinkedIn, etc.). The upstream relay is Buffer, Inc.'s API v1 (the only
      place that real third-party name remains, for the GDPR sub-processor
      record in web.legal).
"""
