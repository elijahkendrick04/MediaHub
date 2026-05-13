"""MediaHub publishing layer.

Pluggable integrations that take an approved content card and queue it
for posting on an external platform. The user must connect an account
on /settings and then explicitly click Schedule on a card — there is no
autopost path through this module.

Currently supported:
    - buffer: Buffer (https://buffer.com) for queueing posts across the
      user's connected social channels (Instagram, Twitter/X, Facebook,
      LinkedIn, etc.) via the Buffer API v1.
"""
