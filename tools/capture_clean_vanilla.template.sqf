[] spawn {
    private _mods = getLoadedModsInfo;
    private _unofficial = _mods select {!(_x select 3)};
    if ((count _unofficial) > 0) exitWith {
        hint "Clean capture refused: disable all community/Creator DLC mods and restart Arma.";
        diag_log format ["A3BALREF refused non-official mods: %1", _unofficial];
    };
    private _manifest = "__MANIFEST_SHA256__";
    private _requests = __REQUESTS__;
    private _run = format ["%1_%2", diag_tickTime, floor random 1000000000];
    private _record = 0;
    private _missingClasses = [];
    private _emit = {
        params ["_payload"];
        _record = _record + 1;
        private _chars = toArray (str _payload);
        private _chunkSize = 96;
        private _parts = ceil ((count _chars) / _chunkSize);
        for "_part" from 0 to (_parts - 1) do {
            diag_log format ["A3BALREF|%1|%2|%3|%4|%5|END", _run, _record, _part + 1, _parts, _chars select [_part * _chunkSize, _chunkSize]];
        };
    };
    private _walk = {
        params ["_entry", "_section", "_name", "_path"];
        if (isClass _entry) exitWith {
            {
                [_x, _section, _name, _path + [configName _x]] call _walk;
            } forEach (configProperties [_entry, "true", true]);
        };
        private _kind = "missing";
        private _value = [];
        if (isNumber _entry) then {_kind = "number"; _value = getNumber _entry;};
        if (isText _entry) then {_kind = "text"; _value = getText _entry;};
        if (isArray _entry) then {_kind = "array"; _value = getArray _entry;};
        [["FIELD", _section, _name, _path, _kind, _value]] call _emit;
    };
    [["BEGIN", 1, _manifest, productVersion, _mods]] call _emit;
    {
        _x params ["_section", "_name", "_fields"];
        private _cfg = configFile >> _section >> _name;
        if !(isClass _cfg) then {
            _missingClasses pushBack [_section, _name];
            [["MISSING_CLASS", _section, _name]] call _emit;
        } else {
            private _ancestry = [];
            private _parent = _cfg;
            while {isClass _parent} do {
                _ancestry pushBack (configName _parent);
                _parent = inheritsFrom _parent;
            };
            [["CLASS", _section, _name, configSourceAddonList _cfg, _ancestry]] call _emit;
            {
                [_cfg >> _x, _section, _name, [_x]] call _walk;
            } forEach _fields;
        };
    } forEach _requests;
    [["END", 1, _manifest, _record + 1, _missingClasses]] call _emit;
    hint format ["Reference capture complete: %1 classes requested, %2 missing. Keep this RPT.", count _requests, count _missingClasses];
};
