[] spawn {
    if (missionNamespace getVariable ["A3BAL_batch_running", false]) exitWith {hint "Balance capture already running.";};
    private _mode = "__MODE__";
    private _suite = "__SUITE_ID__";
    private _mods = getLoadedModsInfo;
    if (_mode == "clean" && {count (_mods select {!(_x select 3)}) > 0}) exitWith {
        hint "Clean capture refused: disable all community and Creator DLC mods, then restart.";
    };
    missionNamespace setVariable ["A3BAL_batch_running", true];
    private _run = format ["%1_%2", diag_tickTime, floor random 1000000000];
    private _record = 0;
    private _issues = 0;
    private _counts = [];
    private _emit = {
        params ["_payload"];
        _record = _record + 1;
        private _chars = toArray (str _payload);
        private _parts = ceil ((count _chars) / 96);
        for "_part" from 0 to (_parts - 1) do {
            diag_log format ["A3BALBATCH|%1|%2|%3|%4|%5|END", _run, _record, _part + 1, _parts, _chars select [_part * 96, 96]];
        };
    };
    private _tree = {
        params ["_entry", ["_depth", 0]];
        if (_depth > 40) exitWith {
            _issues = _issues + 1;
            ["limit", []]
        };
        if (isClass _entry) exitWith {
            private _direct = (configProperties [_entry, "true", false]) apply {configName _x};
            private _children = (configProperties [_entry, "true", true]) apply {
                [configName _x, [_x, _depth + 1] call _tree]
            };
            ["class", configName (inheritsFrom _entry), _direct, _children]
        };
        if (isNumber _entry) exitWith {["number", getNumber _entry]};
        if (isText _entry) exitWith {["text", getText _entry]};
        if (isArray _entry) exitWith {["array", getArray _entry]};
        ["missing", []]
    };
    private _selected = {
        params ["_cfg", "_names"];
        _names apply {[_x, [_cfg >> _x] call _tree]}
    };
    private _ancestry = {
        params ["_cfg"];
        private _names = [];
        private _parent = _cfg;
        while {isClass _parent && {count _names < 128}} do {
            _names pushBack (configName _parent);
            _parent = inheritsFrom _parent;
        };
        if (isClass _parent) then {_issues = _issues + 1;};
        _names
    };
    private _mounts = {
        params ["_vehicle", "_cfg", "_path", ["_depth", 0]];
        if (_depth > 32) exitWith {_issues = _issues + 1;};
        [["MOUNT", _vehicle, _path, getArray (_cfg >> "weapons"), getArray (_cfg >> "magazines")]] call _emit;
        {
            [_vehicle, _x, _path + ["Turrets", configName _x], _depth + 1] call _mounts;
        } forEach (configProperties [_cfg >> "Turrets", "isClass _x", true]);
    };
    [["BEGIN_SUITE", 1, _suite, _mode, productVersion, _mods, worldName]] call _emit;
    private _pilot = ["not_requested"];
    __PILOT_BLOCK__
    {
        private _section = _x;
        private _classes = configProperties [configFile >> _section, "isClass _x", true];
        private _names = _classes apply {configName _x};
        [["INVENTORY", _section, _names]] call _emit;
        _counts pushBack [_section, count _classes];
        {
            private _cfg = _x;
            private _name = configName _cfg;
            private _fields = [];
            switch (_section) do {
                case "CfgWeapons": {
                    _fields = [_cfg, __WEAPON_FIELDS__] call _selected;
                };
                case "CfgVehicles": {
                    _fields = [_cfg, __VEHICLE_FIELDS__] call _selected;
                    if (_name isKindOf "CAManBase") then {
                        _fields pushBack ["HitPoints", [_cfg >> "HitPoints"] call _tree];
                    };
                    _fields pushBack ["TransportPylonsComponent", [_cfg >> "Components" >> "TransportPylonsComponent"] call _tree];
                };
                case "CfgPatches": {
                    _fields = [_cfg, ["requiredAddons", "requiredVersion", "weapons", "units", "magazines", "ammo"]] call _selected;
                };
                case "CfgGlasses": {
                    _fields = [_cfg, ["displayName", "scope", "model", "mass", "armor", "passThrough", "HitpointsProtectionInfo"]] call _selected;
                };
                default {
                    _fields = (configProperties [_cfg, "!isClass _x", true]) apply {[configName _x, [_x] call _tree]};
                    if (_section == "CfgMagazineWells") then {
                        _fields = (configProperties [_cfg, "true", true]) apply {[configName _x, [_x] call _tree]};
                    };
                };
            };
            private _direct = (configProperties [_cfg, "true", false]) apply {configName _x};
            [["CONFIG", _section, _name, configSourceAddonList _cfg, [_cfg] call _ancestry, _direct, _fields]] call _emit;
            if (_section == "CfgWeapons") then {
                private _muzzles = getArray (_cfg >> "muzzles");
                if (count _muzzles == 0) then {_muzzles = ["this"];};
                private _hasFeed = false;
                {
                    private _muzzle = _x;
                    private _m = if (toLower _muzzle == "this") then {_cfg} else {_cfg >> _muzzle};
                    private _mags = getArray (_m >> "magazines");
                    private _wells = getArray (_m >> "magazineWell");
                    if (count _mags > 0 || {count _wells > 0}) then {
                        _hasFeed = true;
                        [["MUZZLE", _name, _muzzle, _mags, _wells, compatibleMagazines [_name, _muzzle]]] call _emit;
                    };
                } forEach _muzzles;
                if (_hasFeed) then {
                    [["WEAPON_COMPAT", _name, compatibleMagazines _name]] call _emit;
                };
            };
            if (_section == "CfgVehicles" && {!(_name isKindOf "Man")}) then {
                [_name, _cfg, []] call _mounts;
            };
            if (_forEachIndex mod 25 == 0) then {
                hintSilent format ["Balance capture (%1): %2 %3 / %4. Keep Arma running.", _mode, _section, _forEachIndex + 1, count _classes];
                sleep 0.001;
            };
        } forEach _classes;
    } forEach ["CfgWeapons", "CfgMagazines", "CfgMagazineWells", "CfgAmmo", "CfgVehicles", "CfgGlasses", "CfgPatches"];
    {
        _x params ["_section", "_name", "_path"];
        private _entry = configFile >> _section >> _name;
        {_entry = _entry >> _x;} forEach _path;
        [["PROBE", _section, _name, _path, [_entry] call _tree]] call _emit;
    } forEach __PROBES__;
    [["END_SUITE", 1, _suite, _mode, _record + 1, _counts, _issues, _pilot]] call _emit;
    missionNamespace setVariable ["A3BAL_batch_running", false];
    hint format ["Balance batch complete (%1): %2 records, %3 limits encountered. Save this RPT. Pilot: %4", _mode, _record, _issues, _pilot];
};
