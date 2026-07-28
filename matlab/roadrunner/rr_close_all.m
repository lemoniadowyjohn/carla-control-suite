function varargout = rr_close_all(varargin)
% RR_CLOSE_ALL Close all RoadRunner instances cleanly.
%
%   [status, report, logPath] = rr_close_all('param', value, ...)
%
% Parameters (all optional):
%   'roadrunnerPath' - Path to the RoadRunner executable
%   'workDirectory'   - Working directory (default: temp dir)
%   'logDir'          - Directory for log files
%   'timeoutSeconds'  - Maximum time to wait per close attempt (default 60)
%   'saveLog'         - Logical: whether to save a log file (default true)
%   'forceKill'       - Logical: force kill if graceful close fails (default false)

    parser = inputParser;
    parser.addParameter('roadrunnerPath', '', @ischar);
    parser.addParameter('workDirectory', '', @ischar);
    parser.addParameter('logDir', '', @ischar);
    parser.addParameter('timeoutSeconds', 60.0, @(x) isnumeric(x) && x > 0);
    parser.addParameter('saveLog', true, @islogical);
    parser.addParameter('forceKill', false, @islogical);
    parser.parse(varargin{:});

    rrPath = parser.Results.roadrunnerPath;
    workDir = parser.Results.workDirectory;
    logDir = parser.Results.logDir;
    timeoutSeconds = parser.Results.timeoutSeconds;
    saveLog = parser.Results.saveLog;
    forceKill = parser.Results.forceKill;

    % Resolve working directory.
    if isempty(workDir) || ~exist(workDir, 'dir') == 7
        workDir = fullfile(tempdir, 'rr_close');
    end
    if ~exist(workDir, 'dir') == 7
        mkdir(workDir);
    end

    % Set up log directory.
    if isempty(logDir)
        logDir = fullfile(workDir, 'logs');
    end
    if ~exist(logDir, 'dir') == 7
        mkdir(logDir);
    end

    timestamp = datestr(now, 'yyyy-mm-dd_HH-MM-SS');
    logFileName = fullfile(logDir, ['close_all_', timestamp, '.log']);
    logFid = fopen(logFileName, 'w');

    log(logFid, '=== Close All RoadRunner Instances Log ===');
    log(logFid, 'roadrunnerPath: %s', rrPath);
    log(logFid, 'forceKill: %s', 'true' if forceKill else 'false');
    log(logFid, 'timeoutSeconds: %f', timeoutSeconds);

    % Try graceful close via RoadRunner API if available.
    status = 0;
    try
        if exist('roadrunner', 'class') == 8
            rr = roadrunner();
            if isvalid(rr)
                log(logFid, 'Calling rr.closeAll()...');
                closeAll(rr);
                log(logFid, 'All instances closed gracefully.');
            end
        end
    catch ME
        log(logFid, 'Graceful close issue: %s', ME.message);
    end

    % If graceful close failed or API not available, try command-line.
    if status == 0
        try
            if isempty(rrPath) || ~exist(rrPath, 'file') == 2
                rrPath = find_roadrunner_executable();
            end
            if ~isempty(rrPath) && exist(rrPath, 'file') == 2
                closeCmd = sprintf('"%s" -batch "rr.closeAll();"', rrPath);
                log(logFid, 'Running close command: %s', closeCmd);
                [status, ~] = system(closeCmd);
            end
        catch ME
            status = 1;
            log(logFid, 'Close command ERROR: %s', ME.message);
        end
    end

    % If still running and forceKill is true, terminate processes.
    if status ~= 0 && forceKill
        log(logFid, 'Force kill enabled: terminating RoadRunner processes...');
        try
            if ispc
                system('taskkill /F /IM RoadRunner.exe /T 2>nul');
                system('taskkill /F /IM roadrunner64.exe /T 2>nul');
            elseif ismac
                system('pkill -f RoadRunner 2>/dev/null');
            else
                system('pkill -f RoadRunner 2>/dev/null');
            end
            log(logFid, 'Force kill completed.');
            status = 0;
        catch ME
            log(logFid, 'Force kill ERROR: %s', ME.message);
            status = 1;
        end
    end

    log(logFid, '=== Close All Complete ===');
    if status == 0
        log(logFid, 'Status: SUCCESS');
    else
        log(logFid, 'Status: FAILED (exit code %d)', status);
    end

    fclose(logFid);

    if saveLog
        varargout = {status, logFileName};
    else
        varargout = {status, ''};
    end
end


function rrPath = find_roadrunner_executable()
% Auto-detect RoadRunner executable.
    searchNames = {'roadrunner', 'RoadRunner', 'roadrunner64', 'RoadRunner64'};
    rrPath = '';
    for i = 1:length(searchNames)
        c = which(searchNames{i});
        if ~isempty(c) && exist(c, 'file') == 2
            rrPath = c;
            return;
        end
    end
    searchDirs = {
        fullfile(getenv('USERPROFILE'), 'Documents', 'RoadRunner');
        fullfile(getenv('LOCALAPPDATA'), 'RoadRunner');
        'C:\Program Files\RoadRunner';
    };
    for i = 1:length(searchDirs)
        if exist(searchDirs{i}, 'dir') == 7
            for j = 1:length(searchNames)
                c = fullfile(searchDirs{i}, searchNames{j});
                if exist(c, 'file') == 2
                    rrPath = c;
                    return;
                end
            end
        end
    end
end


function log(fid, fmt, varargin)
% Write a timestamped line to the log file.
    if nargin < 2
        return;
    end
    ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
    line = sprintf('[%s] %s', ts, sprintf(fmt, varargin{:}));
    fprintf(fid, '%s\n', line);
end