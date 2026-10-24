if (!isNil "A3BAL_accept_running") exitWith {hint "An acceptance test is already running in this preview. Restart the preview to run it again.";};
A3BAL_accept_running = true;
[] spawn {
    private _suiteId = "__SUITE_ID__";
    // [cartridge, projectile class, aim, wearable class or ""]; aim is "chest" (vest), "head" (helmet) or "uniform"
    private _cells = __CELLS__;
    // Uniform classes ("" keeps the soldier's vanilla uniform) for the grenade check.
    private _blast = __BLAST__;
    private _trials = __TRIALS__;
    private _maxShots = __MAX_SHOTS__;
    private _gap = __SHOT_GAP__;
    private _blastTrials = __BLAST_TRIALS__;
    private _blastDistance = __BLAST_DISTANCE__;
    private _blastAmmo = __BLAST_AMMO__;
    private _run = format ["%1_%2", diag_tickTime, floor random 1000000000];
    private _record = 0;
    private _results = 0;
    private _emit = {
        params ["_payload"];
        _record = _record + 1;
        private _chars = toArray (str _payload);
        private _chunkSize = 96;
        private _parts = ceil ((count _chars) / _chunkSize);
        for "_part" from 0 to (_parts - 1) do {
            diag_log format ["A3BALACCEPT|%1|%2|%3|%4|%5|END", _run, _record, _part + 1, _parts, _chars select [_part * _chunkSize, _chunkSize]];
        };
    };
    private _missing = [];
    {
        _x params ["", "_ammo", "", "_gear"];
        if (!isClass (configFile >> "CfgAmmo" >> _ammo)) then {_missing pushBackUnique _ammo;};
        if (_gear != "" && {!isClass (configFile >> "CfgWeapons" >> _gear)}) then {_missing pushBackUnique _gear;};
    } forEach _cells;
    {if (_x != "" && {!isClass (configFile >> "CfgWeapons" >> _x)}) then {_missing pushBackUnique _x;};} forEach _blast;
    private _settings = ["ace_medical_AIDamageThreshold", "ace_medical_playerDamageThreshold", "ace_medical_fatalDamageSource",
        "ace_medical_statemachine_AIUnconsciousness", "ace_medical_statemachine_fatalInjuriesAI", "ace_medical_deathChance",
        "ace_medical_painUnconsciousChance", "ace_medical_engine_damagePassThroughEffect"] apply {[_x, str (missionNamespace getVariable [_x, "unset"])]};
    private _pilot = getText (configFile >> "CfgPatches" >> "a3bal_tests" >> "buildId");
    [["BEGIN_ACCEPT", 1, _suiteId, count _cells, count _blast, _trials, _blastTrials, productVersion, getLoadedModsInfo,
        _settings, _missing, isClass (configFile >> "CfgPatches" >> "ace_medical"), _pilot]] call _emit;

    private _origin = player modelToWorld [60, 0, 0];
    _origin set [2, 0];
    private _group = createGroup [independent, true];
    private _shooter = _group createUnit ["B_Soldier_F", _origin vectorAdd [0, -40, 0], [], 0, "CAN_COLLIDE"];
    _shooter allowDamage false;
    _shooter disableAI "ALL";
    _shooter hideObject true;
    private _spawn = {
        params ["_uniform"];
        private _unit = _group createUnit ["B_Soldier_F", _origin, [], 0, "CAN_COLLIDE"];
        _unit disableAI "ALL";
        _unit setDir 0;
        _unit setPosATL _origin;
        removeAllWeapons _unit;
        removeAllItems _unit;
        removeAllAssignedItems _unit;
        removeVest _unit;
        removeHeadgear _unit;
        removeGoggles _unit;
        removeBackpack _unit;
        if (_uniform != "") then {_unit forceAddUniform _uniform;};
        _unit
    };
    private _total = count _cells + count _blast;
    private _done = 0;
    {
        _x params ["_cartridge", "_ammo", "_aim", "_gear"];
        _done = _done + 1;
        hintSilent format ["Acceptance test %1/%2\n%3\n%4 %5", _done, _total, _ammo, _aim, _gear];
        private _cfg = configFile >> "CfgAmmo" >> _ammo;
        // Impact at the round's own typicalSpeed: the damage the config defines, without range falloff.
        private _speed = getNumber (_cfg >> "typicalSpeed");
        private _values = [getNumber (_cfg >> "hit"), getNumber (_cfg >> "caliber"), _speed];
        if (!(_ammo in _missing) && {!(_gear in _missing)}) then {
            for "_trial" from 1 to _trials do {
                // "uniform" cells wear the uniform with no vest and are shot in the chest.
                private _body = _aim != "head";
                private _unit = [["", _gear] select (_aim == "uniform")] call _spawn;
                if (_gear != "") then {
                    if (_aim == "chest") then {_unit addVest _gear;};
                    if (_aim == "head") then {_unit addHeadgear _gear;};
                };
                sleep 1;
                private _wearing = [headgear _unit, vest _unit, uniform _unit] select (["head", "chest", "uniform"] find _aim);
                private _hitpoint = ["HitHead", "HitChest"] select _body;
                private _selection = ["head", "spine3"] select _body;
                private _shots = 0;
                private _down = false;
                private _first = -1;
                while {!_down && {_shots < _maxShots}} do {
                    private _local = _unit selectionPosition [_selection, "HitPoints"];
                    private _target = if (_local isEqualTo [0, 0, 0]) then {
                        [eyePos _unit, aimPos _unit] select _body
                    } else {
                        _unit modelToWorldVisualWorld _local
                    };
                    // Fired from 3 m in front of the target, which faces north.
                    private _start = _target vectorAdd [0, 3, 0];
                    private _dir = vectorNormalized (_target vectorDiff _start);
                    private _bullet = createVehicle [_ammo, [0, 0, 1000], [], 0, "CAN_COLLIDE"];
                    _bullet setPosASL _start;
                    _bullet setVectorDir _dir;
                    _bullet setVelocity (_dir vectorMultiply _speed);
                    _bullet setShotParents [_shooter, _shooter];
                    _shots = _shots + 1;
                    sleep _gap;
                    if (_first < 0) then {_first = _unit getHitPointDamage _hitpoint;};
                    _down = !alive _unit || {_unit getVariable ["ACE_isUnconscious", false]} || {lifeState _unit == "INCAPACITATED"};
                };
                private _state = "standing";
                if (_down) then {_state = ["unconscious", "dead"] select (!alive _unit);};
                [["RESULT", _ammo, _aim, _gear, _trial, [-1, _shots] select _down, _state, _first, _values, _wearing]] call _emit;
                _results = _results + 1;
                deleteVehicle _unit;
                sleep 0.2;
            };
        };
    } forEach _cells;

    // Grenade check: one hand grenade detonated at a fixed distance from a soldier in each uniform.
    {
        private _uniform = _x;
        _done = _done + 1;
        hintSilent format ["Acceptance test %1/%2\ngrenade, uniform %3", _done, _total, [_uniform, "vanilla"] select (_uniform == "")];
        if (!(_uniform in _missing)) then {
            for "_trial" from 1 to _blastTrials do {
                private _unit = [_uniform] call _spawn;
                sleep 1;
                private _worn = uniform _unit;
                private _grenade = createVehicle [_blastAmmo, [0, 0, 1000], [], 0, "CAN_COLLIDE"];
                _grenade setPosATL (_origin vectorAdd [_blastDistance, 0, 0.1]);
                _grenade setVelocity [0, 0, 0];
                _grenade setShotParents [_shooter, _shooter];
                sleep 0.1;
                triggerAmmo _grenade;
                // Long enough for the grenade's own fuse too, should triggerAmmo not detonate it.
                sleep 7;
                private _parts = _unit getVariable ["ace_medical_bodyPartDamage", [0, 0, 0, 0, 0, 0]];
                private _sum = 0;
                {_sum = _sum + _x;} forEach _parts;
                private _state = "standing";
                if (_unit getVariable ["ACE_isUnconscious", false] || {lifeState _unit == "INCAPACITATED"}) then {_state = "unconscious";};
                if (!alive _unit) then {_state = "dead";};
                [["BLAST", _uniform, _trial, _state, _sum, _parts, damage _unit, _worn]] call _emit;
                _results = _results + 1;
                deleteVehicle _unit;
                sleep 0.5;
            };
        };
    } forEach _blast;
    deleteVehicle _shooter;
    [["END_ACCEPT", 1, _suiteId, _record + 1, _results]] call _emit;
    A3BAL_accept_running = nil;
    A3BAL_accept_done = true;
    hint format ["Balance pilot session complete: %1 trials. Close Arma and keep this RPT.", _results];
};
