if (!isNil "A3BAL_range_running") exitWith {hint "A range test is already running in this preview. Restart the preview to run it again.";};
A3BAL_range_running = true;
[] spawn {
    private _suiteId = "__SUITE_ID__";
    // [cartridge, projectile class]
    private _rounds = __ROUNDS__;
    // [aim, wearable class or "" for none]; aim is "chest" (vest) or "head" (helmet)
    private _targets = __TARGETS__;
    private _trials = __TRIALS__;
    private _maxShots = __MAX_SHOTS__;
    private _gap = __SHOT_GAP__;
    // Light-armor check: vehicle classes; each round is fired at the driver through the left side.
    private _vehicles = __VEHICLES__;
    private _vehicleTrials = __VEHICLE_TRIALS__;
    private _vehicleShots = __VEHICLE_SHOTS__;
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
            diag_log format ["A3BALRANGE|%1|%2|%3|%4|%5|END", _run, _record, _part + 1, _parts, _chars select [_part * _chunkSize, _chunkSize]];
        };
    };
    private _missing = [];
    {if (!isClass (configFile >> "CfgAmmo" >> (_x select 1))) then {_missing pushBackUnique (_x select 1);};} forEach _rounds;
    {if ((_x select 1) != "" && {!isClass (configFile >> "CfgWeapons" >> (_x select 1))}) then {_missing pushBackUnique (_x select 1);};} forEach _targets;
    {if (!isClass (configFile >> "CfgVehicles" >> _x)) then {_missing pushBackUnique _x;};} forEach _vehicles;
    // Damage outcomes depend on these ACE settings; they are logged with the results.
    private _settings = ["ace_medical_AIDamageThreshold", "ace_medical_playerDamageThreshold", "ace_medical_fatalDamageSource",
        "ace_medical_statemachine_AIUnconsciousness", "ace_medical_statemachine_fatalInjuriesAI", "ace_medical_deathChance",
        "ace_medical_painUnconsciousChance", "ace_medical_engine_damagePassThroughEffect", "ace_vehicle_damage_enabled"] apply {[_x, str (missionNamespace getVariable [_x, "unset"])]};
    [["BEGIN_RANGE", 2, _suiteId, count _rounds, count _targets, _trials, _maxShots, _gap, productVersion, getLoadedModsInfo,
        _settings, _missing, isClass (configFile >> "CfgPatches" >> "ace_medical"), count _vehicles, _vehicleTrials, _vehicleShots]] call _emit;

    private _origin = player modelToWorld [60, 0, 0];
    _origin set [2, 0];
    private _group = createGroup [independent, true];
    private _shooter = _group createUnit ["B_Soldier_F", _origin vectorAdd [0, -40, 0], [], 0, "CAN_COLLIDE"];
    _shooter allowDamage false;
    _shooter disableAI "ALL";
    _shooter hideObject true;
    private _total = count _rounds * (count _targets + count _vehicles);
    private _done = 0;
    {
        _x params ["_cartridge", "_ammo"];
        private _cfg = configFile >> "CfgAmmo" >> _ammo;
        // Impact at the round's own typicalSpeed: the damage the config defines, without range falloff.
        private _speed = getNumber (_cfg >> "typicalSpeed");
        private _values = [getNumber (_cfg >> "hit"), getNumber (_cfg >> "caliber"), _speed];
        {
            _x params ["_aim", "_gear"];
            _done = _done + 1;
            hintSilent format ["Range test %1/%2\n%3\n%4 %5", _done, _total, _ammo, _aim, _gear];
            if (!(_ammo in _missing) && {!(_gear in _missing)}) then {
                for "_trial" from 1 to _trials do {
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
                    if (_gear != "") then {
                        if (_aim == "chest") then {_unit addVest _gear;} else {_unit addHeadgear _gear;};
                    };
                    sleep 1;
                    private _wearing = [headgear _unit, vest _unit] select (_aim == "chest");
                    private _hitpoint = ["HitHead", "HitChest"] select (_aim == "chest");
                    private _selection = ["head", "spine3"] select (_aim == "chest");
                    private _shots = 0;
                    private _down = false;
                    private _first = -1;
                    while {!_down && {_shots < _maxShots}} do {
                        private _local = _unit selectionPosition [_selection, "HitPoints"];
                        private _target = if (_local isEqualTo [0, 0, 0]) then {
                            [eyePos _unit, aimPos _unit] select (_aim == "chest")
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
        } forEach _targets;
    } forEach _rounds;

    private _vehicleOrigin = player modelToWorld [60, 40, 0];
    _vehicleOrigin set [2, 0];
    {
        _x params ["_cartridge", "_ammo"];
        private _cfg = configFile >> "CfgAmmo" >> _ammo;
        private _speed = getNumber (_cfg >> "typicalSpeed");
        private _values = [getNumber (_cfg >> "hit"), getNumber (_cfg >> "caliber"), _speed];
        {
            private _class = _x;
            _done = _done + 1;
            hintSilent format ["Range test %1/%2\n%3\nvehicle %4", _done, _total, _ammo, _class];
            if (!(_ammo in _missing) && {!(_class in _missing)}) then {
                for "_trial" from 1 to _vehicleTrials do {
                    private _vehicle = createVehicle [_class, _vehicleOrigin, [], 0, "CAN_COLLIDE"];
                    _vehicle setDir 0;
                    _vehicle setPosATL _vehicleOrigin;
                    _vehicle setFuel 0;
                    private _crew = _group createUnit ["B_Soldier_F", _vehicleOrigin vectorAdd [8, 0, 0], [], 0, "CAN_COLLIDE"];
                    _crew disableAI "ALL";
                    _crew moveInDriver _vehicle;
                    sleep 1.5;
                    private _seated = vehicle _crew == _vehicle;
                    private _box = boundingBoxReal _vehicle;
                    private _half = (abs ((_box select 0) select 0)) max (abs ((_box select 1) select 0));
                    private _firstHurt = -1;
                    for "_shot" from 1 to _vehicleShots do {
                        // The driver if seated, else the hull centre; fired from 3 m outside the left side.
                        private _target = if (_seated && {alive _crew}) then {aimPos _crew} else {_vehicle modelToWorldVisualWorld [0, 0, 1]};
                        private _side = vectorNormalized ((vectorDir _vehicle) vectorCrossProduct (vectorUp _vehicle));
                        private _start = _target vectorAdd (_side vectorMultiply -(_half + 3));
                        private _bullet = createVehicle [_ammo, [0, 0, 1000], [], 0, "CAN_COLLIDE"];
                        _bullet setPosASL _start;
                        _bullet setVectorDir _side;
                        _bullet setVelocity (_side vectorMultiply _speed);
                        _bullet setShotParents [_shooter, _shooter];
                        sleep _gap;
                        private _parts = _crew getVariable ["ace_medical_bodyPartDamage", [0, 0, 0, 0, 0, 0]];
                        private _hurt = !alive _crew || {damage _crew > 0} || {(_parts findIf {_x > 0}) >= 0};
                        if (_hurt && {_firstHurt < 0}) then {_firstHurt = _shot;};
                    };
                    private _state = "unhurt";
                    if (_firstHurt > 0) then {_state = "hurt";};
                    if (_crew getVariable ["ACE_isUnconscious", false]) then {_state = "unconscious";};
                    if (!alive _crew) then {_state = "dead";};
                    [["VEHICLE_RESULT", _ammo, _class, _trial, _firstHurt, _state, damage _vehicle, _seated, _values]] call _emit;
                    _results = _results + 1;
                    deleteVehicle _crew;
                    deleteVehicle _vehicle;
                    sleep 0.5;
                };
            };
        } forEach _vehicles;
    } forEach _rounds;
    deleteVehicle _shooter;
    [["END_RANGE", 2, _suiteId, _record + 1, _results]] call _emit;
    A3BAL_range_running = nil;
    hint format ["Range test complete: %1 trials. Close Arma and keep this RPT.", _results];
};
