# How it works

## The idea

Every mod invents its own armor numbers. Before this patch, a BromA helmet
stopped more than a vanilla Special Combat Helmet, S&S wrote protection as the
word `"true"`, and RHS rounds penetrated so little that mod plate carriers
shrugged off 12 or more point-blank rifle shots.

The patch uses **vanilla Arma as the only reference**. Each item is identified as
a type (steel helmet, flak vest, plate carrier, AP round and so on) and takes the
exact values of the vanilla item of that type. Vanilla already has a ladder of
tiers, so the mods keep their variety: a light carrier still protects less than
a heavy plate.

Only protection and terminal-ballistics values change. Mass, carrying capacity,
models, camouflage and scripts are untouched, and so are ACE and KAT medical.

## Helmets

Helmets are identified by name, model and stats. The rule picks the vanilla
helmet whose head armor and pass-through they take.

| Rule | Armor / pass-through | Vanilla item | Examples |
|---|---|---|---|
| Light (steel) | 4 / 0.5 | Light Combat Helmet | M1, SSh-60/68, M40, vz. 53 |
| Combat (composite) | 6 / 0.5 | Combat Helmet | ACH, MICH, FAST, Ops-Core, PASGT, LWH, 6B7, 6B47, 6B27 |
| Crew | 8 / 0.5 | Crew Helmet | CVC, 6B48 |
| Heavy visored | 10 / 0.5 | Enhanced Combat Helmet | Altyn, Maska |
| Helicopter aircrew | 6 / 0.5 | Heli Pilot/Crew Helmet | HGU-56/P, SPH-4, IHADSS |
| Jet pilot | 8 / 0.5 | Pilot Helmet | ZSh-7A, HGU-55/P |
| Racing | 4 / 0.5 | Racing Helmet | motorcycle helmets |
| Hard hat | 2 / 0.5 | Hard hat | Pro-Tec and other sport shells |

A helmet built on a vanilla model takes that helmet's values. A helmet nobody
could identify is capped at vanilla's strongest ordinary helmet, so nothing
unknown can beat vanilla's best. Caps, berets, boonies, liners, EOD helmets and
anything named "enhanced" or "heavy" are left alone.

The steel rule is a gameplay call: vanilla has no steel helmet, so steel takes
the lightest vanilla helmet.

## Vests

Vests take the vanilla tier for their role. The comparison is chest protection,
but every region a vest already has is set from the same vanilla vest. Regions
that vanilla's vest doesn't have get no protection (armor 0, pass-through 1).
No region is added.

| Tier | Chest armor / pass-through | Vanilla item | Examples |
|---|---|---|---|
| Load-bearing | 0 / 1 | Chest Rig, Bandolier | belts, rigs, webbing |
| Soft | 8 / 0.5 | Tactical Vest | soft vests |
| Flak | 12 / 0.4 | Tactical Vest (Police) | PASGT, M1952/55/69, 6B2, aircrew survival vests |
| Light carrier | 16 / 0.3 | Carrier Lite | MBAV, Plateframe, MBSS |
| Plate | 20 / 0.2 | Carrier Rig | identified plate carriers (the default), KKZ10, Eagle, M-99 |
| Heavy plate | 24 / 0.1 | Carrier Special Rig | IOTV, IBA, MTV, Osprey, 6B13, 6B43, 6B45 |

A vest identified as carrying plates defaults to Plate. An unidentified vest is
capped at Heavy plate. Explosive-specialist and diving vests keep their own
values. Some mods write armor as a sum such as `"22+ 3"`; the game reads that as
25, and so does the pipeline.

These are gameplay tiers, not plate-material ratings.

## Uniforms

In Arma, uniform protection lives on the soldier unit the uniform is linked to,
not on the uniform item. The patch sets the body hit points of 753 soldier units
from vanilla: military uniforms (517) take the combat uniform soldier
(`B_Soldier_F`), civilian clothing (236) takes the civilian (`C_man_polo_1_F`).
Both have the same body values in vanilla:

| Hit point | Before (S&S) | After (vanilla) |
|---|---:|---:|
| Arms, hands, legs: armor | 5 | 3 |
| Arms, hands, legs: explosion shielding | 0.3 | 1 |
| Body, chest, diaphragm: explosion shielding | 2.4 | 6 |
| Pass-through | `"true"` | 1 |

Two groups are held unchanged: 65 civilian uniform-level fields
(`armorStructural`, `explosionShielding`) and 39 legacy item-level armor fields.
The in-game test showed the held civilian values make no difference under ACE.

## Rifle ammunition

Each cartridge follows its vanilla ball round. Ball takes the vanilla round's
three terminal values:

| Cartridge | Vanilla round | Damage (`hit`) | Penetration (`caliber`) | Reference speed |
|---|---|---:|---:|---:|
| 5.56x45 | `B_556x45_Ball` | 9 | 0.87 | 920 |
| 5.45x39 | `B_545x39_Ball_F` | 8 | 0.6 | 880 |
| 7.62x39 | `B_762x39_Ball_F` | 11 | 1.2 | 730 |
| 7.62x51 | `B_762x51_Ball` | 11.6 | 1.6 | 800 |
| 7.62x54R | `B_762x54_Ball` | 11.6 | 1.8 | 835 |

Other rounds of the same cartridge move with it, on a ladder:

- **Penetration** is the vanilla ball's times a multiplier: 1.0 for ball and
  match, 1.2 for enhanced, 1.5 for AP. The AP multiplier is the median of the
  ACE and BWA3 AP rounds, which are already on the vanilla scale.
- **Damage** keeps the round's own ratio to its mod's ball, limited to between
  0.75 and 1.5 times vanilla ball.
- **Reference speed** is the vanilla ball's.
- Subsonic rounds keep their own values.

Rounds are recognized by name, including GRAU codes (7N22/7N24/7BZ3 AP;
7N10/7N13/7N26 enhanced; 7N1/7N14 match; 7N6 ball). A cartridge changes only
when every one of its rounds is identified. Vehicle machine guns (PKT, M240,
L7A2) fire the same rounds as infantry and change with them. Blanks, training
rounds and miniguns are left alone.

7.62x54R uses reference speed 835 rather than clean vanilla's 800, because ACE
ballistics sets 835 in the modset and that is the round players actually fire.

## What players notice

- Rifles defeat armor. 7.62 gets through a plate in 2 to 3 shots; 5.56 needs
  about 9. Against 5.56, a soft vest lasts 2 shots, a plate 9, a heavy plate 11.
- Light carriers protect like vanilla's Carrier Lite: barely more than a soft
  vest against rifles.
- AP is strong: 7BZ3 drops a heavy-plate wearer in 1 shot (ball takes 3).
- M80A1 EPR keeps RHS's lower damage, so it takes 2 shots through a soft vest
  where M80 ball takes 1.
- The Tigr no longer stops rifle rounds from reaching its driver. BTR-80, BMP-2,
  M113 and vanilla's APC still protect their crew.

## How the config is written

The patch is plain config. For every changed class it writes the complete
protection block (the helmet's or vest's `ItemInfo`, the unit's `HitPoints`),
with the observed values copied next to the changed ones. That is why the config
is about 257,000 lines for 20,013 changes. Writing the whole block protects
against inheritance surprises: a child class can't silently lose a value its
parent used to give it, and every class the change reaches is checked in game.

Unchanged parent classes are declared with their parents, so the inheritance
tree matches the modset. The `CfgPatches` entry requires every addon whose
classes are touched, so the patch always loads after them.

For auditing, [reference/change_ledger.csv](../reference/change_ledger.csv) lists
each changed value with its class, path, old value, new value and rule.
