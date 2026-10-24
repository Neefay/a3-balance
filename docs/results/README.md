# Test results

In-game results for the released patch, modset as of 2026-10-24.

- [SESSION_2026-10-24.md](SESSION_2026-10-24.md): the one-session check of the
  final build. Config check passed (3,700 classes, 193,002 entries, 0 failures);
  110 of 110 damage checks within one shot of vanilla. Raw summary:
  [session-report.json](session-report.json).
- [RANGE_TEST_2026-10-24.md](RANGE_TEST_2026-10-24.md): the earlier
  before/after range test, 1,420 trials. It shows how many shots each vest and
  helmet took with the mods' own values and with the vanilla ladder, and which
  light vehicles protect their driver.

All cells are median shots of 5 or 6 trials until an AI target goes unconscious
or dies under ACE medical, fired point-blank at each round's reference speed.
They measure config outcomes, not range falloff or player damage.
