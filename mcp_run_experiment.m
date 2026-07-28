function mcp_run_experiment(opts)
% MCP_RUN_EXPERIMENT  由 MCP Server 调用的统一实验执行器
%   将原本内嵌在 Python 字符串中的 MATLAB 实验逻辑提取为独立文件，
%   便于 checkcode 检查、diff 追踪和版本管理。
%
% 用法:
%   opts = struct();
%   opts.algo = 'HeteroPSO-KR';
%   opts.models = 1:56;
%   opts.n_runs = 15;
%   opts.output_dir = '../results_matlab/test';
%   opts.seed = 42;
%   opts.maxevals = 15000;
%   opts.particles = 500;
%   mcp_run_experiment(opts);
%
% 必填字段: algo, models, output_dir
% 可选字段: n_runs(1), seed(42), maxevals(15000), particles(500),
%           n(5), extra_opts(struct)

    % 参数校验
    required = {'algo', 'models', 'output_dir'};
    for i = 1:length(required)
        if ~isfield(opts, required{i})
            error('mcp_run_experiment: 缺少必填参数 "%s"', required{i});
        end
    end

    % 默认值
    if ~isfield(opts, 'n_runs'), opts.n_runs = 1; end
    if ~isfield(opts, 'seed'), opts.seed = 42; end
    if ~isfield(opts, 'maxevals'), opts.maxevals = 15000; end
    if ~isfield(opts, 'particles'), opts.particles = 500; end
    if ~isfield(opts, 'n'), opts.n = 5; end
    if ~isfield(opts, 'extra_opts'), opts.extra_opts = struct(); end

    % 确保路径存在
    addpath(fullfile(pwd, 'aux_files'));
    addpath(fullfile(pwd, 'methods'));
    addpath(fullfile(pwd, 'utils'));

    if ~exist(opts.output_dir, 'dir')
        mkdir(opts.output_dir);
    end

    % 加载模型
    load('Model56.mat');

    % 构建算法函数句柄
    algo_func_name = ['alg_', strrep(opts.algo, '-', '_')];
    algo_func = str2func(algo_func_name);

    % 写入实验元数据快照 (manifest.json)
    write_manifest(opts, algo_func_name);

    fprintf('=== MCP 实验开始 ===\n');
    fprintf('算法: %s (函数: %s)\n', opts.algo, algo_func_name);
    fprintf('模型: %s (%d 个)\n', mat2str(opts.models), length(opts.models));
    fprintf('重复: %d 次, 种子: %d\n', opts.n_runs, opts.seed);
    fprintf('输出: %s\n\n', opts.output_dir);

    % 主循环
    total = length(opts.models) * opts.n_runs;
    done = 0;
    failed = 0;

    for m_idx = opts.models
        model = Model{m_idx};
        model.n = opts.n;
        model.J_pen = 1e4;
        if ~isfield(model, 'drone_size'), model.drone_size = 1; end
        if ~isfield(model, 'danger_dist'), model.danger_dist = 10 * model.drone_size; end

        % 构建算法选项
        algo_opts = struct();
        algo_opts.maxevals = opts.maxevals;
        algo_opts.particles = opts.particles;
        algo_opts.n = model.n;
        algo_opts.show_progress = false;
        % 合并额外选项
        extra_fns = fieldnames(opts.extra_opts);
        for fi = 1:length(extra_fns)
            algo_opts.(extra_fns{fi}) = opts.extra_opts.(extra_fns{fi});
        end

        for run_i = 1:opts.n_runs
            % 随机种子管理: 每个 (model, run) 组合有确定性种子
            run_seed = opts.seed * 1000 + m_idx * 10 + run_i;
            rng(run_seed, 'twister');

            if opts.n_runs > 1
                fprintf('模型 %02d run %d/%d (seed=%d): ', m_idx, run_i, opts.n_runs, run_seed);
            else
                fprintf('模型 %02d (seed=%d): ', m_idx, run_seed);
            end

            try
                [cost, sol, history] = algo_func([], algo_opts, model);

                % 保存结果
                result = struct();
                result.cost = cost;
                result.sol = sol;
                result.history = history;
                result.model_idx = m_idx;
                result.algo = opts.algo;
                result.run_idx = run_i;
                result.seed = run_seed;
                result.timestamp = datestr(now, 'yyyy-mm-dd HH:MM:SS');

                if opts.n_runs > 1
                    fname = sprintf('model_%d_run_%d_result.mat', m_idx, run_i);
                else
                    fname = sprintf('model_%d_result.mat', m_idx);
                end
                save(fullfile(opts.output_dir, fname), '-struct', 'result');

                fprintf('cost=%.4f OK\n', cost);
                done = done + 1;
            catch ME
                fprintf('ERROR: %s\n', ME.message);
                failed = failed + 1;
            end
        end
    end

    fprintf('\n=== 实验完成: %d/%d 成功, %d 失败 ===\n', done, total, failed);
end


function write_manifest(opts, algo_func_name)
% 写入实验元数据快照，确保可复现
    manifest = struct();
    manifest.algo = opts.algo;
    manifest.algo_func = algo_func_name;
    manifest.models = opts.models;
    manifest.n_runs = opts.n_runs;
    manifest.seed = opts.seed;
    manifest.maxevals = opts.maxevals;
    manifest.particles = opts.particles;
    manifest.n_waypoints = opts.n;
    manifest.output_dir = opts.output_dir;
    manifest.start_time = datestr(now, 'yyyy-mm-dd HH:MM:SS');
    manifest.matlab_version = version;

    % 尝试获取 git commit
    try
        [~, git_out] = system('git rev-parse --short HEAD');
        manifest.git_commit = strtrim(git_out);
    catch
        manifest.git_commit = 'unknown';
    end

    % P2-B 修复: 安全写入 JSON（转义特殊字符）
    manifest_file = fullfile(opts.output_dir, 'manifest.json');
    fid = fopen(manifest_file, 'w');
    if fid > 0
        fprintf(fid, '{\n');
        fprintf(fid, '  "algo": "%s",\n', json_escape(manifest.algo));
        fprintf(fid, '  "algo_func": "%s",\n', json_escape(manifest.algo_func));
        fprintf(fid, '  "models": "%s",\n', json_escape(mat2str(manifest.models)));
        fprintf(fid, '  "n_runs": %d,\n', manifest.n_runs);
        fprintf(fid, '  "seed": %d,\n', manifest.seed);
        fprintf(fid, '  "maxevals": %d,\n', manifest.maxevals);
        fprintf(fid, '  "particles": %d,\n', manifest.particles);
        fprintf(fid, '  "n_waypoints": %d,\n', manifest.n_waypoints);
        fprintf(fid, '  "start_time": "%s",\n', json_escape(manifest.start_time));
        fprintf(fid, '  "matlab_version": "%s",\n', json_escape(manifest.matlab_version));
        fprintf(fid, '  "git_commit": "%s"\n', json_escape(manifest.git_commit));
        fprintf(fid, '}\n');
        fclose(fid);
        fprintf('元数据已保存: %s\n', manifest_file);
    end
end


function s = json_escape(s)
% 转义 JSON 字符串中的特殊字符
    s = strrep(s, '\', '\\');
    s = strrep(s, '"', '\"');
    s = strrep(s, sprintf('\n'), '\n');
    s = strrep(s, sprintf('\r'), '\r');
    s = strrep(s, sprintf('\t'), '\t');
end
