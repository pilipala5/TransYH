# TransYH v0.2.4 整合与发布前验收

本轮日期：2026-10-31（Asia/Shanghai）。开发基础为 PR #5 的 `codex/transyh-responses-v024`，完整纳入 PR #6 的两次召回优化提交。只交付 v0.2.4；不修改 main，不在 GitHub 合并 PR，不创建 Release，PR #6 保留等待最终审查。

## 整合结果

- 保留 v0.2.4 默认流式 Responses、显式 Chat Completions 兼容选项、`store: false`、完整完成状态校验和 Token 统计。组内渠道切换仍由服务端现有 Responses 路由执行，插件没有改写渠道顺序或额度规则。
- 保留翻译与 AI 标注 1–10 并发、中文原件直接阅读、阅读器进度/取消/标注按钮、原件保护、普通缓存、重译恢复及中文/EN 切换。`engine/worker.py`、`engine/api_client.py`、阅读器、存储与重译代码均保持 PR #5 的实现。
- 纳入中文/自定义章节、隐藏分隔符和小字号表格标签修复；每批发送标题、摘要、章节背景和待判断段落。放开按章节及固定关键词决定学术价值的硬过滤，更新三档重要性标准。
- 保留精确连续引用、数字匹配、关键限定条件及紧邻的指代性限制、防重叠与 PDF 几何/文本/图片/批注检查。无固定页数、最低条数或比例配额。
- 使用 `transyh-ai-highlights-v3-contextual-recall` 和独立 `candidate_batches_v3`，隔离旧候选；保留完整候选池及提取、发送、返回、拒绝、缓存、密度选择等分阶段计数。诊断工具为 `scripts/diagnose-highlights.py`。

唯一 Git 内容冲突在 `engine/highlight_jobs.py` 的导入及请求构造处：保留 PR #6 的 `paper_context`、`section_title`、提取与诊断代码，继续调用 PR #5 的 `api_mode()` / `create_text()` 并解析 `TextResult.text`。标注模块没有直接调用 `client.chat.completions.create()`。`src/engine.ts` 同时保留 v0.2.4 引擎目录、`api_client.py` 提取和诊断事件类型；Mock 合并上下文检查与双协议响应。

未删除测试。`test:engine` 现在包含 worker、highlights、density、recall 和 responses 五个模块；本轮仅执行下列指定范围。

## 本轮实际执行

| 命令/验收 | 本轮结果 | 范围 |
| --- | --- | --- |
| `.venv/bin/python -m pytest tests/test_highlights.py tests/test_highlight_density.py tests/test_highlight_recall.py tests/test_responses.py -q` | **99 passed，12.56 秒** | 标注、章节、v3 缓存隔离、三档密度、限定条件、定位、PDF/批注完整性、双 API 协议、流式中断/错误及不自动回退 |
| `.venv/bin/python -m pytest tests/test_worker.py -q -k 'concurrency or global_request_limit'` | **9 passed，52 deselected，0.34 秒** | 并发 1–10 参数与跨引擎池请求上限；未运行剩余 worker 历史测试 |
| `npm run typecheck` | **通过** | 合并后的 TypeScript 类型检查 |
| `npm run build` | **通过，构建一次最终 XPI** | 包含最新四个关键引擎文件及最终 TypeScript bundle |
| `npm run test:zotero:v024` | **通过，一次隔离原生验收** | 安装上一步实际 XPI，双协议、切换、标注、缓存、进度、工具栏取消与 PDF/批注保护 |
| `node scripts/package.mjs` | **生成最终源码 ZIP** | 加入并核对本轮记录后封装源码；XPI 未重新构建 |
| `python3 scripts/audit-release.py` | **通过** | 文件覆盖、逐字节一致、版本、下载链接、敏感内容与运行数据检查 |

Python 测试有 5 条 PyMuPDF/SWIG 类型弃用警告，不影响测试结果。上述 **108 项 Python 通过结果全部来自本轮**，未计入历史 29 项或 83 项结果。

## Zotero 原生验收证据

本轮客户端：**Zotero 10.0.7 / macOS Apple Silicon**。使用专用 `.test-profile/v024`、`.test-data/v024` 和 loopback Mock；日常 Zotero 资料库未参与。原生验收只运行一次，正常关闭测试客户端；未启动全文翻译或真实模型请求。

- 实际安装并启用 v0.2.4，提取到 Zotero 引擎目录的 `worker.py`、`api_client.py`、`highlight_jobs.py`、`highlight_pdf.py` 与最终源文件逐字节相同。
- 同一份两页合成中文 PDF 分别经 Responses 和 Chat Completions 标注：每种协议 2 批请求、5 个脚本化候选，智能档保留 4 处，1 个 supporting 按密度排除。Mock 强制要求标题、摘要与章节背景，缺失即失败。
- Mock 记录的成功与取消请求分别只进入 `/v1/responses` 或 `/v1/chat/completions`；设置并发为 10，本次两批实测峰值为 2，未做 10 并发压力或容量测试。
- 原生工具栏显示标注进度、百分比和取消入口；实际点击工具栏取消按钮终止在途 worker，中文 PDF 保持原字节，任务与取消控件随后清理。
- 实际工具栏“标注重点”重复执行复用结果，不新增请求或图层；同标签中文/EN 切换、英文 PDF 实例、页码与缩放保留。
- 英文原件、中文附件 ID、原生 Zotero 批注与 PDF 内嵌批注保留，标注前中文备份逐字节一致。随后对两种协议的备份与最终 PDF 执行 `verify_preserved()`，文字、几何、图片及内嵌批注一致，PDF 标注元数据均为 4 处。
- 中文原件直接阅读并返回原附件，API 调用增量为 0，附件数保持 1。
- 已查看本轮两个原生页面画布 PNG，蓝/橙/紫高亮与原文位置相符，数字和限定条件可见。截图为合成样例，不证明真实模型学术判断准确率。

本地原始结果与截图位于 `tests/output/v024/`，不进入提交或发布包。可复现入口 `scripts/zotero-v024-test.mjs`、`tests/zotero-v024.js` 随源码包交付。

## 产物与审计

- `dist/TransYH-0.2.4.xpi`：本轮构建及原生安装验收的同一个 XPI，包含最新标注模块、统一 API 适配层和 worker。
- `dist/TransYH-0.2.4-source.zip`：覆盖最终公开源码、全部测试、诊断/验收工具与本记录，内嵌相同的最终 XPI。
- 审计逐项比较 XPI / build / 引擎源码、源码 ZIP / 最终文件以及内嵌 XPI，不使用额外校验和文件。检查 package、lock、manifest、引擎目录和运行时版本均为 0.2.4；README 下载均指向 v0.2.4。
- XPI 为 17 文件白名单；审计覆盖 103 个公开源文件、104 个源码 ZIP 条目（含内嵌 XPI）。源码包仅包含两份公开合成 PDF fixture，排除个人论文、API Key、虚拟环境、资料库、缓存、运行结果和日志；凭据模式及运行文件检查通过。
- 现有产品 README 结构、Logo、品牌与真实论文演示素材保留；演示素材仍明确注明其历史版本和验证边界。

## 尚未验证

未重新翻译或重新标注真实 38 页论文，未调用真实模型，因此不保证该论文最终标注数或语义召回率。Mock 候选仅验证上下文能够进入判断、旧硬过滤不再误删及安全写入流程。

未重跑完整历史 `test:engine`、全文 BabelDOC 翻译、重译端到端/重启恢复长回归及其他系统客户端；上述代码保留，不能把历史通过结果算成本轮通过。未向线上组内服务发起请求，未实测额度耗尽后的渠道自动切换。Windows、Linux、Intel macOS、Zotero 9.x 等未在本轮验收。
