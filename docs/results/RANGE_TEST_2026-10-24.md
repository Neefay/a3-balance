# Range test results

Suite `b8ac9b6ac22f`, 6 trials per cell, cap 12 shots, impact at each round's typicalSpeed from 3 m. Cells are median shots until unconscious or dead (ACE medical).

ACE settings during the run: `ace_medical_AIDamageThreshold=1`, `ace_medical_playerDamageThreshold=1`, `ace_medical_fatalDamageSource=2`, `ace_medical_statemachine_AIUnconsciousness=true`, `ace_medical_statemachine_fatalInjuriesAI=0`, `ace_medical_deathChance=1`, `ace_medical_painUnconsciousChance=0.1`, `ace_medical_engine_damagePassThroughEffect="unset"`, `ace_vehicle_damage_enabled=false`

## Chest shots by vest

| Wearable | Role | Armor / pass | 5.45x39 after | 5.45x39 before | 5.56x45 after | 5.56x45 before | 7.62x39 after | 7.62x39 before | 7.62x51 after | 7.62x51 before | 7.62x54R after | 7.62x54R before |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `V_TacVest_khk` | after soft | 8 / 0.5 | 2 | 3 | 2 | 2 | 1 | 2 | 1 | 1 | 1 | 2 |
| `V_TacVest_blk_POLICE` | after flak | 12 / 0.4 | 3 | >12 | 2 | 3 | 1.5 | 7 | 1 | 3 | 1 | 7 |
| `V_PlateCarrier1_rgr` | after light carrier | 16 / 0.3 | 8 | >12 | 2 | 8 | 2 | 9 | 1 | 7.5 | 1 | 10 |
| `V_PlateCarrier2_rgr` | after plate | 20 / 0.2 | >12 | >12 | 9 | >12 | 5 | >12 | 2 | >12 | 2 | >12 |
| `V_PlateCarrierSpec_rgr` | after heavy | 24 / 0.1 | >12 | >12 | 11.5 | >12 | 8.5 | >12 | 3 | >12 | 3 | >12 |
| `(none)` | baseline no vest | 0 / None | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| `V_Simc_flak_55` | before vanilla_vest_role_tier | 12.0 / 0.5 | 3.5 | >12 | 2 | 3 | 2 | 7 | 1 | 3 | 1 | 7 |
| `rhs_6b3` | before vanilla_vest_role_tier | 22.0 / 0.3 | >12 | >12 | 9.5 | >12 | 8 | >12 | 3 | >12 | 3 | >12 |
| `rhsusf_plateframe_sapi` | before vanilla_vest_role_tier | 22.0 / 0.2 | >12 | >12 | 10 | >12 | 8 | >12 | 3 | >12 | 3 | >12 |
| `rhs_6b5` | before vanilla_vest_role_tier | 25.0 / 0.2 | >12 | >12 | 11 | >12 | 8.5 | >12 | 3 | >12 | 3 | >12 |
| `rhsusf_spc` | before vanilla_vest_role_tier | 28.0 / 0.1 | >12 | >12 | 11 | >12 | 8 | >12 | 3 | >12 | 3 | >12 |

## Head shots by helmet

| Wearable | Role | Armor / pass | 5.45x39 after | 5.45x39 before | 5.56x45 after | 5.56x45 before | 7.62x39 after | 7.62x39 before | 7.62x51 after | 7.62x51 before | 7.62x54R after | 7.62x54R before |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `H_HelmetB_light` | after steel (light) | 4 / 0.5 | 1 | 2 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| `H_HelmetB` | after composite | 6 / 0.5 | 2 | 3 | 1 | 2 | 1 | 2 | 1 | 2 | 1 | 2 |
| `H_HelmetCrew_I` | after crew | 8 / 0.5 | 2 | 4 | 1 | 2 | 1 | 3 | 1 | 2 | 1 | 3 |
| `H_HelmetSpecB` | after heavy visored | 10 / 0.5 | 4 | 7 | 2 | 4 | 2 | 4 | 1 | 4 | 1 | 3.5 |
| `(none)` | baseline no helmet | 0 / None | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| `rhs_ssh60` | before derived_steel_light_vanilla | 2.0 / 0.5 | 1 | 2 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| `rhsusf_cvc_ess` | before vanilla_crew_helmet | 6.0 / 0.5 | 2 | 4 | 1 | 2 | 1 | 3 | 1 | 2 | 1 | 3 |
| `H_Simc_M1_g0` | before derived_steel_light_vanilla | 8.0 / 2.0 | 1 | 2 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| `UK3CB_H_Crew_Helmet` | before vanilla_heli_aircrew | 8.0 / 0.5 | 2 | 3 | 1 | 2 | 1 | 2 | 1 | 2 | 1 | 2 |
| `BRM_6B7_UN` | before ordinary_composite | 10.0 / 0.5 | 2 | 3 | 1 | 2 | 1 | 2 | 1 | 2 | 1 | 2 |

## Side shots at a vehicle's driver

Each cell: trials in which the driver was hurt, of 2, after 8 shots through the left side from 3 m; the first hurting shot in brackets.

| Vehicle | 5.45x39 after | 5.45x39 before | 5.56x45 after | 5.56x45 before | 7.62x39 after | 7.62x39 before | 7.62x51 after | 7.62x51 before | 7.62x54R after | 7.62x54R before |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `C_Offroad_01_F` | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) |
| `O_APC_Wheeled_02_rcws_v2_F` | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 |
| `UK3CB_TKA_O_Hilux_Dshkm` | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) |
| `rhs_bmp2_msv` | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 |
| `rhs_btr80_msv` | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 |
| `rhs_tigr_msv` | 2/2 (1) | 0/2 | 2/2 (1) | 0/2 | 2/2 (1) | 0/2 | 2/2 (1) | 0/2 | 2/2 (1) | 0/2 |
| `rhsusf_m1025_w` | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) | 2/2 (1) |
| `rhsusf_m113_usarmy` | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 |

`before` rows carry today's mod values; `after` rows are the vanilla rung each maps to.
Compare a before row with the after row of its target rung (see the manifest's proposed values).
These are config outcomes on AI targets at point-blank range; they are not range falloff or player-damage measurements.
