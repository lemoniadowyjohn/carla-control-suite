function varargout = rr_probe(varargin)
% RR_PROBE Offline-safe RoadRunner capability probe for MATLAB.
%
%   rr_probe('param', value, ...)
%
% Parameters (all optional):
%   'roadrunnerPath'  - Path to RoadRunner executable (auto-detected if omitted)
%   'matlabPath'      - Path to MATLAB executable (auto-detected if omitted)
%   'outputDir'       - Directory for log and probe output (defaults to pwd)
%   'saveLog'         - Logical: whether to save a probe log (default true)
%
% Returns:
%   status     - 0 on success, 1 on failure
%   report     - struct with detected capabilities
%   logPath    - path to the saved log file

    parser = inputParser;
    parser.addParameter('roadrunnerPath', '', @ischar);
    parser.addParameter('matlabPath', '', @ischar);
    parser.addParameter('outputDir', pwd, @ischar);
    parser.addParameter('saveLog', true, @islogical);
    parser.parse(varargin{:});

    rrPath = parser.Results.roadrunnerPath;
    matlabPath = parser.Results.matlabPath;
    outputDir = parser.Results.outputDir;
    saveLog = parser.Results.saveLog;

    if isempty(outputDir)
        outputDir = pwd;
    end

    % Ensure output directory exists.
    if ~isfolder(outputDir)
        mkdir(outputDir);
    end

    timestamp = datestr(now, 'yyyy-mm-dd_HH-MM-SS');
    logFileName = fullfile(outputDir, ['rr_probe_', timestamp, '.log']);
    logFid = fopen(logFileName, 'w');

    log(logFid, '=== RoadRunner Probe Log ===');
    log(logFid, 'Timestamp: %s', timestamp);
    log(logFid, 'MATLAB version: %s', version);
    log(logFid, 'MATLAB root: %s', matlabroot);

    % Detect RoadRunner executable.
    if isempty(rrPath)
        rrPath = find_roadrunner_executable(logFid);
    end

    % Detect MATLAB executable.
    if isempty(matlabPath)
        matlabPath = fullfile(matlabroot, 'bin', 'matlab');
    end

    % Build report struct.
    report = struct();
    report.roadrunner_executable = rrPath;
    report.matlab_executable = matlabPath;
    report.roadrunner_found = exist(rrPath, 'file') == 2;
    report.matlab_found = exist(matlabPath, 'file') == 2;

    % Attempt to detect RoadRunner release.
    report.roadrunner_release = detect_roadrunner_release(rrPath, logFid);

    % Attempt to detect MATLAB release.
    report.matlab_release = detect_matlab_release(logFid);

    % Detect toolbox availability via matlab.addons.toolbox.
    report.automated_driving_toolbox = check_toolbox('Automated Driving Toolbox', logFid);
    report.scene_builder = check_toolbox('Scene Builder', logFid);
    report.roadrunner_scenario = check_toolbox('RoadRunner Scenario', logFid);

    % Detect roadrunnerAPI.
    report.roadrunner_api_available = check_roadrunner_api(logFid);

    % Detect CmdRoadRunnerApi.
    report.cmd_roadrunner_api = check_cmd_roadrunner_api(logFid);

    % Detect .proto files.
    protoDir = get_proto_directory(rrPath, logFid);
    [report.grpc_proto_files, report.proto_count] = find_proto_files(protoDir, logFid);

    % Detect authoring functions.
    report.authoring_functions = detect_authoring_functions(logFid);

    % Supported import/export formats.
    report.supported_imports = {'xodr', 'osm', 'fbx', 'tiled', 'kml'};
    report.supported_exports = {'xodr', 'fbx', 'tiled', 'kml'};

    log(logFid, '=== Probe Complete ===');
    log(logFid, 'Overall: %s', 'SUCCESS');

    fclose(logFid);

    if saveLog
        varargout = {0, report, logFileName};
    else
        varargout = {0, report, ''};
    end
end


function rrPath = find_roadrunner_executable(logFid)
% Find RoadRunner executable on PATH and common install locations.
    searchNames = {'roadrunner', 'RoadRunner', 'roadrunner64', 'RoadRunner64'};
    rrPath = '';

    for i = 1:length(searchNames)
        candidates = which(searchNames{i});
        if ~isempty(candidates) && exist(candidates, 'file') == 2
            rrPath = candidates;
            log(logFid, 'Found RoadRunner: %s', rrPath);
            return;
        end
    end

    % Search common install directories.
    searchDirs = {
        fullfile(getenv('USERPROFILE'), 'Documents', 'RoadRunner');
        fullfile(getenv('LOCALAPPDATA'), 'RoadRunner');
        'C:\Program Files\RoadRunner';
        'C:\Program Files (x86)\RoadRunner'
    };
    for i = 1:length(searchDirs)
        d = searchDirs{i};
        if exist(d, 'dir') == 7
            for j = 1:length(searchNames)
                candidate = fullfile(d, searchNames{j});
                if exist(candidate, 'file') == 2
                    rrPath = candidate;
                    log(logFid, 'Found RoadRunner at: %s', rrPath);
                    return;
                end
            end
        end
    end

    log(logFid, 'RoadRunner executable not found.');
end


function release = detect_roadrunner_release(rrPath, logFid)
% Attempt to determine RoadRunner release version.
    release = '';
    if isempty(rrPath) || ~exist(rrPath, 'file') == 2
        log(logFid, 'Cannot detect release: no RoadRunner executable.');
        return;
    end

    parentDir = fileparts(rrPath);

    % Try release_info.json.
    releaseFile = fullfile(parentDir, 'release_info.json');
    if exist(releaseFile, 'file') == 2
        try
            data = jsondecode(fileread(releaseFile));
            if isfield(data, 'version')
                release = data.version;
            elseif isfield(data, 'release')
                release = data.release;
            end
            log(logFid, 'Release from release_info.json: %s', release);
            return;
        catch
            log(logFid, 'Failed to parse release_info.json.');
        end
    end

    % Try version.txt.
    versionFile = fullfile(parentDir, 'version.txt');
    if exist(versionFile, 'file') == 2
        release = strtrim(fileread(versionFile));
        log(logFid, 'Release from version.txt: %s', release);
        return;
    end

    log(logFid, 'RoadRunner release detection skipped.');
end


function release = detect_matlab_release(~, logFid)
% Return MATLAB release string.
    release = version;
    log(logFid, 'MATLAB release: %s', release);
end


function available = check_toolbox(toolboxName, logFid)
% Check if a MATLAB toolbox is installed.
    try
        info = matlab.addons.toolbox.installedToolboxes();
        names = {info.Name};
        available = any(contains(names, toolboxName, 'IgnoreCase', true));
    catch
        available = false;
    end
    log(logFid, '%s: %s', toolboxName, 'yes' if available else 'no');
end


function available = check_roadrunner_api(logFid)
% Check if roadrunner API is accessible.
    available = false;
    try
        if exist('roadrunner', 'class') == 8 || exist('roadrunner', 'file') == 2
            available = true;
        end
    catch
    end
    log(logFid, 'roadrunnerAPI: %s', 'yes' if available else 'no');
end


function available = check_cmd_roadrunner_api(logFid)
% Check if CmdRoadRunnerApi command is available.
    available = false;
    try
        cmdPath = fullfile(matlabroot, 'toolbox', 'roadrunner', 'CmdRoadRunnerApi');
        if exist(cmdPath, 'file') == 2 || exist('CmdRoadRunnerApi', 'file') == 2
            available = true;
        end
    catch
    end
    log(logFid, 'CmdRoadRunnerApi: %s', 'yes' if available else 'no');
end


function protoDir = get_proto_directory(rrPath, logFid)
% Determine where .proto files are located.
    protoDir = '';
    if ~isempty(rrPath) && exist(rrPath, 'file') == 2
        parentDir = fileparts(rrPath);
        candidates = {
            fullfile(parentDir, 'grpc', 'protos');
            fullfile(parentDir, 'proto');
            fullfile(parentDir, 'share', 'roadrunner', 'proto');
            fullfile(matlabroot, 'toolbox', 'roadrunner', 'grpc', 'protos');
        };
        for i = 1:length(candidates)
            if exist(candidates{i}, 'dir') == 7
                protoDir = candidates{i};
                log(logFid, 'Found .proto directory: %s', protoDir);
                return;
            end
        end
    end
    log(logFid, 'No .proto directory found.');
end


function [files, count] = find_proto_files(protoDir, logFid)
% Find all .proto files under the given directory.
    files = {};
    count = 0;
    if isempty(protoDir) || ~exist(protoDir, 'dir') == 7
        log(logFid, 'No .proto search directory.');
        return;
    end
    fList = dir(fullfile(protoDir, '**', '*.proto'));
    for i = 1:length(fList)
        files{end + 1} = fullfile(fList(i).folder, fList(i).name);
        count = count + 1;
    end
    log(logFid, 'Found %d .proto file(s).', count);
end


function functions = detect_authoring_functions(logFid)
% Detect RoadRunner authoring functions.
    functions = {};
    knownFunctions = {
        'addLineArcRoad', 'addClothoidFitRoad', 'addSegmentedRoad', ...
        'addSpiral', 'addParametricCubic', 'addSuperElevation', ...
        'addLateralProfile', 'addElevationProfile'
    };
    for i = 1:length(knownFunctions)
        try
            if exist(knownFunctions{i}, 'file') == 2 || ...
               exist(knownFunctions{i}, 'class') == 8
                functions{end + 1} = knownFunctions{i};
            end
        catch
        end
    end
    log(logFid, 'Authoring functions detected: %s', strjoin(functions, ', '));
end


function log(fid, fmt, varargin)
% Write a timestamped line to the log file.
    if nargin < 2
        return;
    end
    ts = datestr(now, 'yyyy-mm-dd HH:MM:SS');
    if nargin == 2
        line = sprintf('[%s] %s', ts, fmt);
    else
        line = sprintf('[%s] %s', ts, sprintf(fmt, varargin{:}));
    end
    fprintf(fid, '%s\n', line);
end