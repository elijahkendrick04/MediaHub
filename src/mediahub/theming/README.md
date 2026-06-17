# theming

The colour science. It takes a club's main colours and works out a full,
good-looking palette for the designs (so text stays readable and on-brand). This is
careful maths, not guesswork.

If a club gives more than one colour (say navy *and* gold *and* red), the engine
decides which colour should be the main one, which is the second, and which is the
accent — and it checks that text will still be easy to read on each. A club with just
one colour gets exactly the same palette as before. See `roles.assign_brand_roles`
and `palette.derive_palette_multi`, and section 14 of `docs/THEMING.md`.
