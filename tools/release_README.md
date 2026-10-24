# A3 Balance

A config-only patch for our mod preset. It puts mod helmets, vests, uniforms and
rifle ammunition on vanilla Arma's protection and damage ladder, so a 6B3 and a
vanilla carrier rig protect the same way, and a PKM and an M240 round hit like
vanilla's. Items keep their own tier: a light carrier is still lighter than a
heavy plate.

## Install

- **Everyone loads it**: every player, the server and any headless client. Damage
  is worked out where the hit unit is local, so a player without the patch would
  take different damage.
- It is one small addon per mod (`a3bal_rhs_afrf.pbo`, `a3bal_broma.pbo` and so
  on). Each loads after its mod and skips itself when that mod isn't loaded.
- **Mod updates:** the values were drafted against the mod versions it was built
  for. After RHS, 3CB, BromA, S&S, RoN or ACE update, rebuild the patch and rerun
  its check before playing.
- It is unsigned. If the server checks signatures, sign it with your own key
  (Arma 3 Tools' DSSignFile, or HEMTT) and put the `.bikey` on the server.
- To revert, unload the mod. It changes no saves or missions.

## What changes

| Category | Items | Vanilla tier they take |
|---|---:|---|
| Helmets | 1,026 | Light steel 418, composite 527, crew 25, heavy visored 7, pilot/aircrew 25, hard hat 24 |
| Vests | 1,656 | Plate 1,023, light carrier 242, heavy plate 216, flak 102, load-bearing 73 |
| Uniforms | 753 | Vanilla combat uniform (517) or civilian clothing (236) body values |
| Rifle rounds | 104 | 5.45x39, 5.56x45, 7.62x39, 7.62x51 and 7.62x54R: ball takes vanilla's values; AP, enhanced and match rounds keep their order above or around ball |

Only protection values (armor, pass-through, explosion shielding) and terminal
ballistics (damage, penetration, reference speed) change. Mass, capacity, models,
camouflage, ACE and KAT medical are untouched.

## What you will notice

- **Rifle rounds now defeat armor.** Today's RHS rounds penetrate so little that
  plate carriers stop 12+ point-blank shots. Now, 7.62 gets through a plate in 2
  to 3 shots and 5.56 in 9 to 11. Plates still matter: against 5.56, a soft vest
  lasts about 2 shots, a plate 9 and a heavy plate 11 or 12.
- **Light carriers** (MBAV, Plateframe, MBSS) protect like vanilla's light
  carrier: barely better than a soft vest against rifles.
- **Vehicle MGs** (PKT, M240, L7A2, the Offroad's M249) fire the same rounds as
  infantry. The Tigr no longer stops rifle rounds from reaching its driver.
  BTR-80, BMP-2 and M113 still protect their crew.
- **Pro-Tec helmets** are treated as non-ballistic (hard hat); **ZSh-7A jet
  helmets** are raised to vanilla's pilot helmet.

Built and checked by the balance project; see its README for the evidence.
