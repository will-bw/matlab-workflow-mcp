# Skill 审查报告：matlab-experiment

> 审查日期：2026-08-02
> 审查对象：`.qoder/skills/matlab-experiment/`（SKILL.md + tools-reference.md + 4 个 references + 3 个 templates）
> 审查方法：① 逐行对照 `matlab_mcp_server.py` v3.0 源码与 `config.py` 验证 skill 的事实性声明；② 分析 Paper2 项目（`/Users/will/Desktop/codes/Paper2`）的实际实验工作流与两份 MCP 实践经验报告，检验 skill 与实战的契合度。

---

## 一、总体评价

**结论：结构优秀、架构描述准确，但存在 3 处事实性错误、1 处统计代码 bug、若干与服务器行为的脱节，且最核心的学术日志体系从未在真实项目中落地。**

优点（值得保留）：

- **Progressive disclosure 结构规范**：SKILL.md 主文件 + tools-reference + 4 个按需加载的 references + 3 个 templates，层次清晰。
- **v3.0 架构描述准确**：子进程池（3 并发 / 队列 5）、无持久工作区、自包含代码、Streamable HTTP `/mcp` 端点、/health 字段、Syncthing 出图策略——逐一与源码核对无误。v2 时代的痛点（单线程 Engine 阻塞、任务静默失败、`e.message` bug、无健康检查）在 v3.0 服务器中均已修复，skill 正确反映了新架构。
- **学术实验设计内容与 Paper2 实践高度吻合**：消融增量模式（Baseline/+C1/+C2/Full 对应 Paper2 的 A/B/C/D 组）、n_runs ≥ 15、MRE/Friedman/Wilcoxon/效应量指标体系、56 场景设定，与 Paper2 的实际消融体系一致。
- **元数据 schema 设计完整**：lineage（parent_id/supersedes）支持实验迭代追溯，minimal vs full 分层合理。

---

## 二、P0 问题（事实性错误 / 必然导致失败）

### P0-1. 工具数量错误：是 17 个，不是 18 个

- `tools-reference.md` 第 1 行："**18 tools**"；Paper2 旧版 SKILL.md 同错。
- 源码实测：`grep -c '@mcp.tool()' matlab_mcp_server.py` = **17**。
- 17 个工具清单：run, run_script, submit_task, get_task_status, get_task_output, cancel_task, list_tasks, get_history, experiment, inspect, lint_code, list_files, transfer_file, upload_file, save_figure, diagnose, sync_status。

### P0-2. Friedman 秩计算代码有统计错误（analysis-reporting.md L64-66）

```matlab
% skill 模板（错误）：
[~, ranks] = sort(scenario_means, 1);
friedman_ranks = mean(ranks, 2);
```

`sort` 的第二返回值是**排列索引**（每个名次上是哪个组），不是秩。对其按行求均值得到的是"各名次位置上的平均组编号"，没有统计学意义。

正确做法（Paper2 自己的 `analyzeAblation.m` L132 就是这么做的）：

```matlab
n_groups = size(scenario_means, 1);
rank_mat = zeros(size(scenario_means));
for j = 1:size(scenario_means, 2)
    [~, idx] = sort(scenario_means(:, j));
    rank_mat(idx, j) = 1:n_groups;   % 名次 → 组
end
friedman_ranks = mean(rank_mat, 2);  % 每组的平均秩
```

这是会被直接复制进论文实验分析代码的模板，**必须修**。

### P0-3. `experiment` 工具存在悬空依赖 + 硬编码，skill 未披露

- 服务器 `experiment` 工具的参数化模式生成代码调用 **`mcp_run_experiment(mcpOpts)`**（matlab_mcp_server.py L936）。
- 该 `.m` 文件**只存在于 WinServerBuild 仓库根目录**，Paper2 工作区（本地 Mac 与远端 E:\code\Paper2 同步目录）中**均不存在** → 参数化模式必然报 `Undefined function` 失败，只有 `raw_code` 模式可用。
- 默认参数 `algo="HeteroPSO-KR"`、`models="1:56"` 是 Paper2 硬编码，但 skill 把它当作通用工具呈现，且**未提及任何前置条件**。
- 同时 SKILL.md 的 Intent 决策树和 4 个 Workflow **完全没有引用 `experiment` 工具**（只在 tools-reference.md 里孤立存在）——要么纳入流程并写明依赖，要么从 skill 中移除/标注为项目专用。

### P0-4. 缺少 Paper2 实战验证的两个关键健壮性模式

Paper2 两份经验报告（6,720 次实验沉淀）中最重要的两个代码模式，skill 的 PREPARE 阶段模板完全没有吸收：

1. **增量保存 + 文件级断点续跑**：
   ```matlab
   if exist(fname, 'file'), continue; end  % 跳过已完成
   % ... 计算 ...
   save(fname, '-struct', 'res');           % 每个结果立即落盘
   ```
   v3.0 的超时是**硬杀子进程**，进程被杀时内存中未保存的结果全部丢失。没有增量保存，TIMEOUT 恢复表里写的 "submit only missing" 就无法实现。这是长实验成败的最关键模式。
2. **时间窗口自终止**：
   ```matlab
   t0 = tic;
   % 循环内：if toc(t0) > TIME_LIMIT, return; end  （预留余量给保存与响应）
   ```
   配合分块策略（`RunAblationChunk.m` 按 group×run 分块，正是为避免单进程跑 3360 次评估导致 MATLAB 堆腐坏），与 v3.0 子进程池架构天然契合，应写入 EXECUTE 阶段的分块指引。

### P0-5. 文件级同步验证缺失（skill 规则 5 不可靠）

- SKILL.md 规则 5："Check sync_status before running modified code"，PREPARE 阶段的 pre-flight 也只做 `sync_status()`。
- 但 `sync_status` 工具（源码 L1164）**只报告 Syncthing 设备连接状态**，"设备已连接" ≠ "你刚改的那个文件已同步到位"。Paper2 报告中就出现过代码文件夹未配置同步的情况。
- Paper2 实战验证模式（应写入 skill）：
  ```matlab
  c = fileread('methods/alg_HeteroPSO_KR.m');
  if contains(c, 'UNIQUE_MARKER_STRING'), disp('SYNCED'); else, disp('NOT SYNCED'); end
  ```
  即每次改代码时埋入版本标记字符串，执行前用 `run` 做**内容级**验证。

---

## 三、P1 问题（文档与服务器行为不一致 / 未披露的陷阱）

| # | 问题 | 详情 |
|---|------|------|
| P1-1 | **run_script 固定 600s 超时** | 源码 L740：硬编码 `TASK_TIMEOUT_DEFAULT`，无 timeout 参数。决策树说 "Run a .m script file → run_script" 但无超时警告——长脚本必被杀。应标注 "<10min 的脚本才用 run_script"。 |
| P1-2 | **inspect/lint_code 固定 120s、save_figure 固定 300s** | 均未文档化。大型 .mat 的 `whos` 或复杂出图可能触顶。 |
| P1-3 | **错误码表不完整** | skill 只列 4 个（QUEUE_FULL/TIMEOUT/MATLAB_ERROR/FILE_NOT_FOUND）；源码还有 `PATH_TRANSLATION`、`INVALID_SECTION`、`FILE_TOO_LARGE`；且 transfer_file 等返回的是非结构化的 `[错误] ...` 文本而非错误码，错误处理表与实际不符。 |
| P1-4 | **工作区沙箱未文档化** | `_resolve_workspace_path`（L115）把所有文件类工具（run_script/inspect/lint_code/list_files/transfer_file/upload_file/save_figure）限制在 `MATLAB_WORKING_DIR` 内，越界抛 PermissionError。skill 讲了 "never hardcode paths" 却没提这个硬约束，agent 访问工作区外路径时会困惑。 |
| P1-5 | **run 与 submit_task 共享 3 槽并发池** | skill 正确指出 get_task_status 不占槽，但未说明 run 占槽——3 个后台任务跑满时调用 run 会**排队等待**直至超时。监控期间用 run 收集中间结果的 Workflow D 可能卡死。应提示"分析操作尽量排在批量任务之后，或预留一个槽"。 |
| P1-6 | **内联代码不能含 function 定义** | `_build_wrapped_code` 把用户代码包进 `try ... catch ... end`（L187-205），MATLAB 不允许 try 块内定义 function；含局部函数的代码内联提交必报语法错误。skill 的"自包含代码"章节应注明：带 function 的代码必须写成 .m 文件同步后用 run_script，或 upload_file 上传。 |
| P1-7 | **Syncthing 等待时间偏乐观** | skill 说出图后 "Wait 2-3s"；Paper2 实测同步延迟 2-10s。建议改为"等待并验证本地文件存在（最多重试 N 次）"。 |

---

## 四、P2 问题（设计 / 采用度 / 一致性）

1. **experiment_log 体系零落地（最大采用度风险）**：Paper2 从未创建 `experiment_log/`——实际组织是 `scripts/experiments/`（17 个版本化脚本）+ `results_matlab/` + `docs/` 报告。skill 把 9 步 Logged Experiment 流程作为强制路径（Workflow B），但它在真实项目中从未被验证过。要么在 Paper2 补建该体系试跑一次闭环，要么把日志系统降级为"可选的正式实验档案"。
2. **双副本漂移**：Paper2 的 `.qoder/skills/matlab-experiment/` 是旧版（无学术管理层，且 Figure Export 一节硬编码了 `~/Desktop/codes/Paper2/exports/fig.png`——违反它自己 "never hardcode paths" 的规则）。两个项目各存一份、内容已分叉，需要单一来源（只保留 WinServerBuild 版，Paper2 侧用同步或安装机制分发）。
3. **Paper2 专用知识与通用 skill 的边界模糊**：`computeResultStats`（Paper2 utils 函数，skill 模板直接引用）、`run_%d` 目录约定、56 场景、"HeteroPSO-KR" 默认值散布在各文档中。作为 MCP 服务器项目的配套 skill，应把这些标注为"以 Paper2 为例"，或明确声明这是 Paper2 专用 skill。
4. **description 触发词全是英文**：中文用户说"跑个消融实验"能否稳定触发存疑，建议补中文触发词（消融、出图、远程 MATLAB 等）。
5. **小修正**：
   - `experiment-lifecycle.md` 队列描述 "Max 5 queued + 3 running = 8 total" ✓ 与 config 一致，但 SKILL.md 错误表只说 "QUEUE_FULL max 5"，可对齐表述。
   - `run` 的实际超时语义是 "timeout + 60s 宽限后硬杀"（L643），skill 未提宽限与硬杀行为。
   - `metadata_template.json` 的 `code_hash` 标注 optional，但 directory-structure.md 未说明何时该填。

---

## 五、v2 痛点 → v3.0 修复 → skill 吸收情况对照

Paper2 两份经验报告列出的痛点，逐一核对现状：

| v2 报告痛点 | v3.0 服务器是否修复 | skill 是否吸收 |
|---|---|---|
| 单线程 Engine 前后台冲突致崩溃 | ✅ 子进程池 + 优先级调度 | ✅ 已准确描述 |
| 任务静默失败 / `e.message` bug | ✅ try/catch 包装 + MATLAB_ERROR + stack trace + exit(1) | ⚠️ 错误表有 MATLAB_ERROR 但未提会带 MATLAB 堆栈 |
| 无 /health | ✅ 已实现且免认证 | ✅ 已文档化且字段一致 |
| 长时间 run 传输层超时 | ✅ 30s 心跳保活 | ⚠️ 未说明仍有 600s 默认上限 + 60s 宽限 |
| submit_task 进度不透明（has_output 恒 false） | ✅ output_lines 实时捕获 | ✅ "Real-time readable while running" 属实 |
| 分批 + 断点续跑模式 | ➖ 架构已支持 | ❌ **未吸收**（见 P0-4） |
| 文件级同步验证（fileread marker） | ➖ sync_status 只能看连接 | ❌ **未吸收**（见 P0-5） |
| 代码避免内联带 function | ➖ 仍需 .m 文件 | ❌ 未提示（见 P1-6） |
| 备用客户端 mcp_run.py | （Qoder 客户端问题，非服务器） | 可不写，但建议在 references 中注明客户端层仍有不可恢复卡死风险（50001） |

---

## 六、修改建议清单（按优先级）

**立即修（P0）：**
1. tools-reference.md：18 → 17 tools。
2. analysis-reporting.md：重写 Friedman 秩计算（用本文 P0-2 的正确代码）。
3. tools-reference.md `experiment` 一节：补充前置条件（远端工作区必须存在 `mcp_run_experiment.m`），或将其标注为 Paper2 专用；SKILL.md 决策树要么纳入要么删除该工具。同时应把 `mcp_run_experiment.m` 部署进 Paper2 同步目录，否则工具不可用。
4. experiment-lifecycle.md PREPARE 模板：加入增量保存（`if exist(...), continue`）+ 时间窗口自终止模式。
5. SKILL.md 规则 5 与 PREPARE pre-flight：补充文件级同步验证（fileread + 版本标记）模式，不能只靠 sync_status。

**尽快修（P1）：**
6. tools-reference.md：为 run_script（600s 固定）、inspect/lint_code（120s）、save_figure（300s）标注超时上限。
7. SKILL.md 错误表：补 PATH_TRANSLATION / INVALID_SECTION / FILE_TOO_LARGE，并注明部分错误为非结构化文本。
8. SKILL.md "Discovering Paths" 一节：补充工作区沙箱约束说明。
9. SKILL.md：注明 run 与 submit_task 共享 3 槽池；批量任务跑满时 run 会排队。
10. SKILL.md 自包含代码章节：注明内联代码不能包含 function 定义。
11. 出图流程："Wait 2-3s" 改为"验证本地文件存在，必要时重试"。

**规划改进（P2）：**
12. 在 Paper2 实际跑通一次 experiment_log 完整闭环（DESIGN→REPORT），验证后再决定是否保持强制。
13. 消除双副本漂移：以 WinServerBuild 为唯一来源，同步到 Paper2。
14. 泛化或显式标注 Paper2 专属内容；description 增加中文触发词。
