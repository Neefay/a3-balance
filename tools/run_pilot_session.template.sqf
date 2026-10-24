if (!isNil "A3BAL_session_running") exitWith {hint "The balance pilot session is already running. Restart the preview to run it again.";};
A3BAL_session_running = true;
// One session: every config check part in turn, then the patched-game acceptance test.
[] spawn {
    private _parts = __PARTS__;
    private _refused = false;
    for "_part" from 1 to _parts do {
        A3BAL_verify_done = nil;
        [] execVM format ["\a3bal_pilot\tests\verify_part%1.sqf", _part];
        // A stalled part is logged and skipped after 30 minutes; the importer then reports it missing.
        private _start = diag_tickTime;
        waitUntil {sleep 1; !isNil "A3BAL_verify_done" || {diag_tickTime - _start > 1800}};
        if (isNil "A3BAL_verify_done") then {diag_log format ["A3BALPILOT_SESSION|PART_TIMEOUT|%1", _part];};
        if (!isNil "A3BAL_verify_done" && {A3BAL_verify_done < 0}) exitWith {_refused = true;};
        sleep 3;
    };
    if (_refused) exitWith {A3BAL_session_running = nil;};
    [] execVM "\a3bal_pilot\tests\acceptance_test.sqf";
};
