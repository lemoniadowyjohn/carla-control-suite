function varargout = rr_import_xodr(varargin)
% RR_IMPORT_XODR Import an XODR/OpenDRIVE file into RoadRunner.
%
%   [status, report, logPath] = rr_import_xodr('param', value, ...)
%
% Parameters (all required except where noted):
%   'xodrPath'        - Path to the source XODR file
%   'roadrunnerPath'  - Path to the RoadRunner executable
%   'workDirectory'   - Working directory for the import (default: temp dir)
%   'outputDir'       - Directory for import output (default: unique subdir of workDirectory)
%   'logDir'          - Directory for log files (default: outputDir/logs)
%   'preserveSource'  - Logical: copy source XODR to output (default true)
%   'timeoutSeconds'  - Maximum time to wait (default 300)
%   'saveLog'         - Logical: whether to save a log file (default true)

    parser = inputParser;
    parser.addParameter('xodrPath', '', @(x) ischar(x) && exist(x, 'file') == 2);
    parser.addParameter('roadrunnerPath', '', @ischar);
    parser.addParameter('workDirectory', '', @ischar);
    parser.addParameter('outputDir', '', @ischar);
    parser.addParameter('logDir', '', @ischar);
    parser.addParameter('preserveSource', true, @islogical);
    parser.addParameter('timeoutSeconds', 300.0, @(x) isnumeric(x) && x > 0);
    parser.addParameter('saveLog', true, @islogical);
    parser.parse(varargin{:});

    xodrPath = parser.Results.xodrPath;
    rrPath = parser.Results.roadrunnerPath;
    workDir = parser.Results.workDirectory;
    outputDir = parser.Results.outputDir;
    logDir = parser.Results.logDir;
    preserveSource = parser.Results.preserveSource;
    timeoutSeconds = parser.Results.timeoutSeconds;
    saveLog = parser.Results.saveLog;

    % Validate source XODR.
    if isempty(xodrPath) || ~exist(xodrPath, 'file') == 2
        error('rr_import_xodr:SourceNotFound', ...
            'Source XODR file not found or not specified.');
    end

    % Resolve RoadRunner path.
    if isempty(rrPath) || ~exist(rrPath, 'file') == 2
        rrPath = find_roadrunner_executable();
    end
    if isempty(rrPath) || ~exist(rrPath, 'file') == 2
        error('rr_import_xodr:RoadRunnerNotFound', ...
            'RoadRunner executable not found.');
    end

    % Resolve working directory.
    if isempty(workDir) || ~exist(workDir, 'dir') == 7
        workDir = fullfile(tempdir, 'rr_import');
    end
    if ~exist(workDir, 'dir') == 7
        mkdir(workDir);
    end

    % Create unique output directory.
    if isempty(outputDir)
        timestamp = datestr(now, 'yyyymmdd_HHMMSS');
        outputDir = fullfile(workDir, ['import_', timestamp]);
    end
    if ~exist(outputDir, 'dir') == 7
        mkdir(outputDir);
    end

    % Set up log directory.
    if isempty(logDir)
        logDir = fullfile(outputDir, 'logs');
    end
    if ~exist(logDir, 'dir') == 7
        mkdir(logDir);
    end

    timestamp = datestr(now, 'yyyy-mm-dd_HH-MM-SS');
    logFileName = fullfile(logDir, ['import_', timestamp, '.log']);
    logFid = fopen(logFileName, 'w');

    log(logFid, '=== XODR Import Log ===');
    log(logFid, 'xodrPath: %s', xodrPath);
    log(logFid, 'roadrunnerPath: %s', rrPath);
    log(logFid, 'outputDir: %s', outputDir);
    log(logFid, 'preserveSource: %s', 'true' if preserveSource else 'false');
    log(logFid, 'timeoutSeconds: %f', timeoutSeconds);

    % Preserve source XODR.
    if preserveSource
        sourceDir = fullfile(outputDir, 'source_preserved');
        if ~exist(sourceDir, 'dir') == 7
            mkdir(sourceDir);
        end
        destXodr = fullfile(sourceDir, fullfile(xodrPath));
        if ~exist(destXodr, 'file') == 2
            copyfile(xodrPath, destXodr);
            log(logFid, 'Source XODR preserved to: %s', destXodr);
        end
    end

    % Build import command.
    importCmd = sprintf( ...
        'rrImport(''%s'', ''%s'', ''%s'');', ...
        xodrPath, rrPath, outputDir);

    log(logFid, 'Running import command...');
    log(logFid, 'Command: %s', importCmd);

    % Execute.
    try
        [status, ~] = system(importCmd);
    catch ME
        status = 1;
        log(logFid, 'ERROR: %s', ME.message);
    end

    log(logFid, '=== Import Complete ===');
    if status == 0
        log(logFid, 'Status: SUCCESS');
    else
        log(logFid, 'Status: FAILED (exit code %d)', status);
    end

    fclose(logFid);

    if status ~= 0
        error('rr_import_xodr:ImportFailed', ...
            'RoadRunner import failed with exit code %d.', status);
    end

    if saveLog
        varargout = {status, outputDir, logFileName};
    else
        varargout = {status, outputDir, ''};
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