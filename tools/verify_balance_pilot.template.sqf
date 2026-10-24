[] spawn {
    private _buildId = "__BUILD_ID__";
    private _part = __PART__;
    private _parts = __PARTS__;
    private _patch = configFile >> "CfgPatches" >> "a3bal_pilot";
    if (!isClass _patch || {getText (_patch >> "buildId") != _buildId}) exitWith {
        A3BAL_verify_done = -1;
        hint "Balance pilot missing or wrong build. Enable the supplied local mod with the original full preset and restart.";
    };
    if (isClass (configFile >> "CfgPatches" >> "a3bal_helmets_pilot")) exitWith {
        A3BAL_verify_done = -1;
        diag_log format ["A3BALPILOT_PREFLIGHT_REFUSED|%1|OLD_HELMET_PILOT_LOADED", _buildId];
        hint "Check refused: the old helmet pilot is also loaded. Remove it from the launcher, keep only A3 Balance Pilot, and restart.";
    };
    private _missingAddons = (getArray (_patch >> "requiredAddons")) select {
        !(isClass (configFile >> "CfgPatches" >> _x))
    };
    if (count _missingAddons > 0) exitWith {
        A3BAL_verify_done = -1;
        {diag_log format ["A3BALPILOT_PREFLIGHT_REFUSED|%1|MISSING_ADDON|%2", _buildId, _x];} forEach _missingAddons;
        hint format ["Check refused: %1 required addons missing. Restore the ORIGINAL FULL preset with the balance pilot enabled and restart.", count _missingAddons];
    };
    private _checks = __CHECKS__;
    private _run = format ["%1_%2", diag_tickTime, floor random 1000000000];
    private _marker = format ["A3BALP%1", _part];
    private _record = 0;
    private _failed = 0;
    private _reported = 0;
    private _checkedFields = 0;
    private _emit = {
        params ["_payload"];
        _record = _record + 1;
        private _chars = toArray (str _payload);
        private _chunkSize = 96;
        private _count = ceil ((count _chars) / _chunkSize);
        for "_chunk" from 0 to (_count - 1) do {
            diag_log format ["%1|%2|%3|%4|%5|%6|END", _marker, _run, _record, _chunk + 1, _count, _chars select [_chunk * _chunkSize, _chunkSize]];
        };
    };
    private _same = {
        params ["_actual", "_expected"];
        if (_expected isEqualType 0) exitWith {
            (_actual isEqualType 0) && {abs (_actual - _expected) <= (0.000001 max ((abs _expected) * 0.000001))}
        };
        if (_expected isEqualType []) exitWith {
            if (!(_actual isEqualType []) || {count _actual != count _expected}) exitWith {false};
            private _ok = true;
            {if !([_actual select _forEachIndex, _x] call _same) then {_ok = false;};} forEach _expected;
            _ok
        };
        _actual isEqualTo _expected
    };
    private _failure = {
        params ["_name", "_path", "_expected", "_actual"];
        _failed = _failed + 1;
        if (_reported < 100) then {
            [["FAILURE", _name, _path, _expected, _actual]] call _emit;
            _reported = _reported + 1;
        };
    };
    // Expected entries are a tree: [name, kind, value]; a class's value is its child entries.
    private _walk = {
        params ["_cfg", "_nodes", "_name", "_path"];
        {
            _x params ["_key", "_kind", "_expected"];
            private _entry = _cfg >> _key;
            private _here = _path + [_key];
            private _type = "missing";
            private _actual = [];
            if (isClass _entry) then {_type = "class";};
            if (isNumber _entry) then {_type = "number"; _actual = getNumber _entry;};
            if (isText _entry) then {_type = "text"; _actual = getText _entry;};
            if (isArray _entry) then {_type = "array"; _actual = getArray _entry;};
            _checkedFields = _checkedFields + 1;
            if (_kind == "class") then {
                if (_type != "class") then {
                    [_name, _here, _kind, _type] call _failure;
                } else {
                    [_entry, _expected, _name, _here] call _walk;
                };
            } else {
                if (_type != _kind || {!([_actual, _expected] call _same)}) then {
                    [_name, _here, [_kind, _expected], [_type, _actual]] call _failure;
                };
            };
        } forEach _nodes;
    };
    [["BEGIN_PILOT", 2, _buildId, _part, _parts, count _checks, productVersion, getLoadedModsInfo]] call _emit;
    {
        _x params ["_section", "_name", "_ancestry", "_nodes"];
        private _cfg = configFile >> _section >> _name;
        private _actualAncestry = [];
        private _parent = _cfg;
        while {isClass _parent} do {
            _actualAncestry pushBack (configName _parent);
            _parent = inheritsFrom _parent;
        };
        if !((_actualAncestry apply {toLower _x}) isEqualTo (_ancestry apply {toLower _x})) then {
            [_name, ["$ancestry"], _ancestry, _actualAncestry] call _failure;
        };
        [_cfg, _nodes, _name, []] call _walk;
    } forEach _checks;
    [["END_PILOT", 2, _buildId, _part, _record + 1, count _checks, _checkedFields, _failed, _reported]] call _emit;
    A3BAL_verify_done = _part;
    hint format ["Balance pilot part %1 of %2: %3 classes, %4 fields, %5 failures. Run the next part, or close Arma after the last one.", _part, _parts, count _checks, _checkedFields, _failed];
};
