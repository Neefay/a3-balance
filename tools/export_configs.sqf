/*
    A3 Balance: full config export (schema ARMA_EQUIPMENT_DUMP 2).

    Run in an Eden preview with the complete modset loaded: paste into the debug console,
    press LOCAL EXEC and leave Arma running until the hint says the export is complete.
    It writes every class of the sections below, with inherited properties, into the RPT as
    A3EQ frames (80 characters each). Read them back with:

        python extract_rpt.py <rpt> data-recovered --salvage

    A large modset writes several GB of RPT and takes a while; free disk space first.
*/
[] spawn {
    if (missionNamespace getVariable ["A3EQ_running", false]) exitWith {hint "Export already running.";};
    missionNamespace setVariable ["A3EQ_running", true];
    private _run = format ["%1_%2", diag_tickTime, floor random 1000000];
    private _record = 0;
    private _emit = {
        params ["_payload"];
        private _chars = toArray (str _payload);
        private _parts = (ceil ((count _chars) / 80)) max 1;
        for "_part" from 0 to (_parts - 1) do {
            diag_log text format ["A3EQ|%1|%2|%3|%4|%5|END", _run, _record, _part, _parts, _chars select [_part * 80, 80]];
        };
        _record = _record + 1;
    };
    // [name, "class", [parent, entries]] | [name, "number"|"text"|"array", value], inherited entries included
    private _entries = {
        params ["_cfg", "_depth"];
        (configProperties [_cfg, "true", true]) apply {
            if (isClass _x) then {
                private _children = if (_depth < 32) then {[_x, _depth + 1] call _entries} else {[]};
                [configName _x, "class", [configName (inheritsFrom _x), _children]]
            } else {
                if (isNumber _x) then {[configName _x, "number", getNumber _x]} else {
                    if (isText _x) then {[configName _x, "text", getText _x]} else {[configName _x, "array", getArray _x]}
                }
            }
        }
    };
    private _ancestry = {
        params ["_cfg"];
        private _names = [];
        while {isClass _cfg && {count _names < 128}} do {
            _names pushBack (configName _cfg);
            _cfg = inheritsFrom _cfg;
        };
        _names
    };
    [["BEGIN", "ARMA_EQUIPMENT_DUMP", 2, productVersion, getLoadedModsInfo]] call _emit;
    private _counts = [];
    {
        private _section = _x;
        private _classes = configProperties [configFile >> _section, "isClass _x", true];
        {
            [[_section, configName _x, [_x] call _ancestry, configSourceAddonList _x, [_x, 0] call _entries]] call _emit;
            if (_forEachIndex mod 100 == 0) then {
                hintSilent format ["Config export: %1 %2 / %3. Keep Arma running.", _section, _forEachIndex + 1, count _classes];
                sleep 0.001;
            };
        } forEach _classes;
        _counts pushBack [_section, count _classes];
    } forEach ["CfgWeapons", "CfgMagazines", "CfgAmmo", "CfgMagazineWells", "CfgGlasses", "CfgPatches", "CfgVehicles"];
    [["END", _counts, _record]] call _emit;
    missionNamespace setVariable ["A3EQ_running", false];
    hint format ["Config export complete: %1 records. Save the RPT before restarting Arma.", _record];
};
