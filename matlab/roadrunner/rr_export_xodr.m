function varargout = rr_export_xodr(varargin)
% RR_EXPORT_XODR Export a RoadRunner scene to XODR.
%
%   [status, exportPath, logPath] = rr_export_xodr('param', value, ...)
%
% Parameters (required unless noted):
%   'roadrunnerPath' - Path to the RoadRunner executable
%   'scenePath'      - Path to the RoadRunner scene (.rrscene or project dir)
%   'outputDir'      - Directory for export output (unique subdir created)
%   'workDirectory'  - Working directory (default: temp dir)
%   'logDir'         - Directory for log files (default: outputDir/logs)
%   'timeoutSeconds' - Maximum time to wait (default 300)
%   'saveLog'        - Logical: whether to save a log file (default true)
%   'preserveSource' - Logical: preserve original scene files (default true)

    parser = inputParser;
    parser.addParameter('roadrunnerPath', '', @ischar);
    parser.addParameter('scenePath', '', @(x) ischar(x) && exist(x, 'file') == 2);
    parser.addParameter('outputDir', '', @ischar);
    parser.addParameter('workDirectory', '', @ischar);
    parser.addParameter('logDir', '', @ischar);
    parser.addParameter('timeoutSeconds', 300.0, @(x) isnumeric(x) && x > 0);
    parser.addParameter('saveLog', true, @islogical);
    parser.addParameter('preserveSource', true, @islogical);
    parser.parse(varargin{:});

    rrPath = parser.Results.roadrunnerPath;
    scenePath = parser.Results.scenePath;
    outputDir = parser.Results.outputDir;
    workDir = parser.Results.workDirectory;
    logDir = parser.Results.logDir;
    timeoutSeconds = parser.Results.timeoutSeconds;
    saveLog = parser.Results.saveLog;
    preserveSource = parser.Results.preserveSource;

    % Validate scene path.
    if isempty(scenePath) || ~exist(scenePath, 'file') == 2
        error('rr_export_xodr:SceneNotFound', ...
            'Scene file not found or not specified.');
    end

    % Resolve RoadRunner path.
    if isempty(rrPath) || ~exist(rrPath, 'file') == 2
        rrPath = find_roadrunner_executable();
    end
    if isempty(rrPath) || ~exist(rrPath, 'file') == 2
        error('rr_export_xodr:RoadRunnerNotFound', ...
            'RoadRunner executable not found.');
    end

    % Resolve working directory.
    if isempty(workDir) || ~exist(workDir, 'dir') == 7
        workDir = fullfile(tempdir, 'rr_export');
    end
    if ~exist(workDir, 'dir') == 7
        mkdir(workDir);
    end

    % Create unique output directory.
    if isempty(outputDir)
        timestamp = datestr(now, 'yyyymmdd_HHMMSS');
        uid = datestr(now, 'HHMMSSFFF');
        outputDir = fullfile(workDir, ['export_xodr_', timestamp, '_', uid]);
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
    logFileName = fullfile(logDir, ['export_', timestamp, '.log']);
    logFid = fopen(logFileName, 'w');

    log(logFid, '=== XODR Export Log ===');
    log(logFid, 'roadrunnerPath: %s', rrPath);
    log(logFid, 'scenePath: %s', scenePath);
    log(logFid, 'outputDir: %s', outputDir);

    % Preserve source scene.
    if preserveSource
        sourceDir = fullfile(outputDir, 'source_preserved');
        if ~exist(sourceDir, 'dir') == 7
            mkdir(sourceDir);
        end
        destScene = fullfile(sourceDir, fullfile(scenePath));
        if ~exist(destScene, 'file') == 2
            copyfile(scenePath, destScene);
            log(logFid, 'Source scene preserved to: %s', destScene);
        end
    end

    % Build export command.
    exportCmd = sprintf( ...
        'rrExport(''%s'', ''%s'', ''xodr'', ''%s'');', ...
        rrPath, scenePath, outputDir);

    log(logFid, 'Running export command...');
    log(logFid, 'Command: %s', exportCmd);

    % Execute.
    try
        [status, ~] = system(exportCmd);
    catch ME
        status = 1;
        log(logFid, 'ERROR: %s', ME.message);
    end

    log(logFid, '=== Export Complete ===');
    if status == 0
        log(logFid, 'Status: SUCCESS');
    else
        log(logFid, 'Status: FAILED (exit code %d)', status);
    end

    fclose(logFid);

    if status ~= 0
        error('rr_export_xodr:ExportFailed', ...
            'RoadRunner export failed with exit code %d.', status);
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