# Conventions for coding agents

- Never put Discord, SQLite, or clock calls inside `core/`. If a rule needs the time, it takes `now` as a parameter.
- Money is `int`. Time is `float` epoch seconds. No `float` currency, no naive datetimes.
- Every behavior change in `core/rules.py` needs a test, and any new invariant goes in `test_properties.py`.
- Never commit the bot token; read it from the environment only. Fail fast with a clear message if it's missing.
- Don't name any package or module `discord`.
- Keep dependencies minimal; ask before adding any.
- Run `pytest` before declaring a milestone done.
