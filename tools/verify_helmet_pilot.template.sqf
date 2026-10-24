[] spawn {
    private _buildId = "__BUILD_ID__";
    private _patch = configFile >> "CfgPatches" >> "a3bal_helmets_pilot";
    if (!isClass _patch || {getText (_patch >> "buildId") != _buildId}) exitWith {
        hint "Helmet pilot missing or wrong build. Enable the supplied local mod with the original full preset and restart.";
    };
    private _checks = __CHECKS__;
    private _run = format ["%1_%2", diag_tickTime, floor random 1000000000];
    private _record = 0;
    private _failed = 0;
    private _reported = 0;
    private _checkedFields = 0;
    private _emit = {
        params ["_payload"];
        _record = _record + 1;
        private _chars = toArray (str _payload);
        private _chunkSize = 96;
        private _parts = ceil ((count _chars) / _chunkSize);
        for "_part" from 0 to (_parts - 1) do {
            diag_log format ["A3BALPILOT|%1|%2|%3|%4|%5|END", _run, _record, _part + 1, _parts, _chars select [_part * _chunkSize, _chunkSize]];
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
    [["BEGIN_PILOT", 1, _buildId, count _checks, productVersion, getLoadedModsInfo]] call _emit;
    {
        _x params ["_name", "_ancestry", "_fields"];
        private _cfg = configFile >> "CfgWeapons" >> _name;
        private _actualAncestry = [];
        private _parent = _cfg;
        while {isClass _parent} do {
            _actualAncestry pushBack (configName _parent);
            _parent = inheritsFrom _parent;
        };
        if !((_actualAncestry apply {toLower _x}) isEqualTo (_ancestry apply {toLower _x})) then {
            [_name, ["$ancestry"], _ancestry, _actualAncestry] call _failure;
        };
        {
            _x params ["_path", "_kind", "_expected"];
            private _entry = _cfg;
            {_entry = _entry >> _x;} forEach _path;
            private _type = "missing";
            private _actual = [];
            if (isClass _entry) then {_type = "class"; _actual = [];};
            if (isNumber _entry) then {_type = "number"; _actual = getNumber _entry;};
            if (isText _entry) then {_type = "text"; _actual = getText _entry;};
            if (isArray _entry) then {_type = "array"; _actual = getArray _entry;};
            _checkedFields = _checkedFields + 1;
            if (_type != _kind || {!([_actual, _expected] call _same)}) then {
                [_name, _path, [_kind, _expected], [_type, _actual]] call _failure;
            };
        } forEach _fields;
    } forEach _checks;
    [["END_PILOT", 1, _buildId, _record + 1, count _checks, _checkedFields, _failed, _reported]] call _emit;
    hint format ["Helmet pilot: %1 classes, %2 fields, %3 failures. Keep this RPT.", count _checks, _checkedFields, _failed];
};
