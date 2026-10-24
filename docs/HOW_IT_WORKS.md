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

The patch is a set of small compat addons, one per mod (`a3bal_rhs_afrf`,
`a3bal_broma`, `a3bal_sns` and so on), about 130 KB built in total. Each is an
ordinary config patch:

- **It writes only the numbers that change.** Mod gear usually inherits its
  protection from a shared base class, so the value is changed once, where it is
  defined, and inheritance carries it to every item below. A class only gets its
  own line when it must differ from what it inherits: a target that differs from
  its siblings, or a non-target that keeps its old value. 20,013 changed values
  take 2,113 lines this way.
- **It reopens classes, it doesn't replace them.** Every class keeps the parent
  it already has, and everything the patch doesn't name stays as the mod defined
  it. When the mod's author changes something the patch doesn't touch, that
  change still comes through.
- **It depends only on its own mod.** Each addon requires that mod's addons (RHS's
  load-order addons, for example) and sets `skipWhenMissingDependencies = 1`, so a
  modset without BromA simply doesn't load the BromA patch.

Hidden base classes (`scope` 0 or 1) that no player or uniform uses may take the
new value along with their children. Vanilla classes are never written.

### Parent classes

In Arma, a class's parent is looked up through the declarations in the file that
declares it, and the engine logs any change as `Updating base class` in the RPT.
Patches that redeclare a class carelessly can change parents without anyone
noticing: the first build of this patch did, on 18 classes. So the build checks
it three ways:

1. A model of the whole loaded config, rebuilt from the full-modset capture,
   must reproduce all 965,798 captured protection and ammunition values. It
   records which class each nested class actually inherits from. In this modset
   one S&S base unit's hit points inherit from a class further up than its
   nearest parent, which the model infers from the captured values.
2. Each file's own lookups are simulated and must find exactly the parents the
   engine bound. Classes that would conflict within one file go to a second
   file, which is why some mods have two or three addons.
3. A separate reader parses the finished config text and predicts every
   `Updating base class` the engine would log. On the first build it predicted
   all 18 that the engine reported; on this build it predicts none. The in-game
   check then reads the RPT and fails if any appear.

The patch is also re-simulated as if the engine re-resolved every parent after
loading. Every target and every kept value comes out the same either way.

For auditing, [reference/change_ledger.csv](../reference/change_ledger.csv) lists
each changed value with its class, path, old value, new value and rule.
