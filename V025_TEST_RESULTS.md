# TransYH v0.2.5 发布与原生收尾验收

日期为 2026-11-05，时区为 Asia/Shanghai。开发分支为 `codex/transyh-performance-diagnostics`，基础提交为 `d1d571324c0a8d6f5c77c350772ceba8a969857d`。交付对应现有 Draft PR #7。

## 发布内容

- 保留既有 `ReadingSession.pdfUpdated()` 最小修复。目标附件尚未加载到任何 pane 时立即返回，随后首次中文切换加载新译文。目标已有 pane 时仍等待当前切换、重新加载 PDF 并恢复阅读位置。
- package、lock、manifest、运行时引擎目录、自动配置版本和 README 下载链接统一为 0.2.5，运行时使用 `engine-0.2.5`。
- XPI 构建及运行时提取已有的 `performance.py` 继续保留，补入发布审计白名单和源码 ZIP 必需文件检查。审计增加编译结果中提前返回条件先于 `await this.switching` 的检查。
- 本轮产品代码改动仅涉及版本标识。API、翻译与标注提示词、密度、缓存身份及安全提交逻辑继续沿用基础提交。
- 最终安装包为 `dist/TransYH-0.2.5.xpi`，源码包为 `dist/TransYH-0.2.5-source.zip`。XPI 构建一次，之后原生验收及交付复用该文件。历史 v0.2.4 产物在本轮 Git 差异中无变更。

## 最终原生验收

客户端为 Zotero 10.0.7 / macOS Apple Silicon。最终完整执行使用 `.test-profile/v025-3`、`.test-data/v025-3`、`.test-runtime/v025-3` 与 `tests/output/v025-3`。材料是本仓库现场生成的一页英文合成论文，API 只指向 loopback Mock，调用实际 BabelDOC 0.6.4 和最终 XPI 内的引擎。

| 用户操作或断言 | 最终实际结果 |
| --- | --- |
| 安装最终 XPI | 0.2.5 已安装且启用，9 个提取的 Python 文件与源码逐字节相同，包含 performance.py |
| 开启自动标注，打开全新英文附件 | 点击前只有一个英文附件，英文视图已加载，中文 pane 尚未创建 |
| 实际点击阅读器顶部「中文」 | 触发生产 `switchTo()` 和 `translate()`，通过实际 worker 翻译并导入一个中文附件 |
| 自动 AI 标注 | 翻译任务及首次切换仍在等待时启动实际 highlight worker，完成备份、原子提交与附件保存 |
| 重现原等待顺序 | 首次 `pdfUpdated()` 入口实测 `switching=true`、目标 `loaded=false`，提前返回并让调用链继续 |
| 中文切换完整结束 | 同一阅读标签进入中文，首次操作到切换 Promise 完成为 **14.552 秒**，属于本地 Mock 验收耗时 |
| 任务进度 | 观察真实原生进度条主行，翻译和标注均达到 **100%**，两种运行中状态均出现 |
| 任务结束与控件 | `translationStatus()` 清空、切换 Promise 释放、进度按钮和取消按钮隐藏 |
| 已加载中文再次标注 | 通过原生「标注重点」按钮使用 Chat Completions，`pdfUpdated()` 实测目标 loaded=true，中文 PDF 实例刷新，英文实例保留 |
| 缓存复用 | 再次执行返回 unchanged、requests=0，Mock 调用数增量为零，PDF 字节相同 |
| 失败保护 | Mock 401 经实际 worker 返回，中文 PDF 字节、附件和批注保留，任务与控件清理 |
| 取消保护 | 延迟 Mock 请求在途时点击原生取消按钮，worker 退出，中文 PDF 字节、附件和批注保留，任务与控件清理 |
| 中文 / EN 再次切换 | 原生按钮切换成功，英文原件逐字节相同，中文附件 ID 与两侧 Zotero 批注保留 |
| 关闭标签 | session 从管理表移除，secondary pane 销毁，pane 清理表清空，阅读状态写入完成 |
| 最终 PDF | 一页、3 处蓝/橙/紫重点，`verify_preserved()` 通过文字、几何及图形检查，原生画布已目视检查 |
| 测试客户端退出 | 测试资料库客户端正常退出，最终结果 isolatedShutdown=true |

最终 Mock 共 6 次请求。首次 Responses 路径包括 2 次翻译和 1 次自动标注，全部成功并收到完整结束事件。Chat Completions 包括 1 次重新标注、1 次受控 401 和 1 次取消场景。缓存复用没有新增调用。数字来自 Mock 统计和实际 worker 的本地性能 JSON。

两个首次任务的 `task-performance.json` 实际记录如下，取自结束后读取的文件。

| 任务 | status | currentPhase | 阶段耗时 |
| --- | --- | --- | --- |
| 翻译 | completed | cleanup | translation_worker 12494 ms，attachment_import 77 ms，automatic_highlights 1566 ms |
| 自动标注 | completed | cleanup | highlight_worker 1275 ms，highlight_install 290 ms，attachment_save 0 ms，reader_refresh 1 ms |

首次切换 Promise 完成、实际中文视图加载及控件清理也分别经过断言，任务完成的判断覆盖 PDF 保存之后的阅读器收尾。

## 验收脚本修正与执行次数

XPI 全程复用同一个文件。准备最终验收时发生两处脚本观察错误，诊断保留在本地。

1. `v025` 尝试把已进入 highlight map 的任务仍断言为 translation，观察器异常被产品的标注失败保护捕获。修正为只记录调用顺序，结束后统一断言。
2. `v025-2` 中完整首次切换已在 13.856 秒结束，两个任务均达到 100%，随后通过跨窗口 PDF 对象读取文本的方法受到 Gecko 包装限制。改用原生文本层检查，并对既有附件续接验证其余保护。续接时也等待了 XPI 启动完成。该次合成 Mock 的精确引用补充支持实际 BabelDOC 布局分隔符，返回引文仍逐字对应 PDF。
3. 使用修正后的最终公开脚本，在全新 `v025-3` profile 完成一次从安装、首次点击到资源释放的连续验收，所有断言通过。该次完整结果用于上面的验收表。没有重复执行历史全量 Zotero 测试套件。

可复现入口为 `TRANSYH_V025_ATTEMPT=3 npm run test:zotero:v025`。每次要求新的独立资料库，已有目录会被拒绝；复现时选择未使用的正整数。第一段完整用户链超时为 120 秒，外层命令超时为 180 秒，单项操作通常为 20 秒。失败时保留诊断，退出受限于已验证的专用 profile 与本次启动的子进程。

脚本只对原生进度对象与方法调用做透明观察，实际切换、worker、附件导入、自动标注、安全提交和 PDF 刷新均执行发布 XPI 内的代码。

## 本轮相关测试

| 执行范围 | 结果 |
| --- | --- |
| `npm run typecheck` | 通过 |
| `node --import tsx --test tests/reader-completion.test.ts` | 3 passed |
| performance 与高亮安全提交、原件保护、强制中断恢复的定向 Python 用例 | 16 passed，35 deselected，4.48 秒 |
| Mock 连接、worker 协议及候选缓存复用的 3 项现有用例 | 3 passed，1.72 秒 |
| 最终 `TRANSYH_V025_ATTEMPT=3 npm run test:zotero:v025` | 通过，实际安装相同最终 XPI，连续完成全部原生断言与 PDF 核验 |
| `node scripts/package.mjs` | 生成最终源码 ZIP，内嵌同一 XPI |
| `python3 scripts/audit-release.py` | 通过，113 个公开源文件、18 个 XPI/build 文件、114 个源码 ZIP 条目，文件覆盖、逐字节一致、版本、修复编译结果及敏感内容检查均通过 |

本轮累计 19 项相关 Python 测试，3 项阅读器测试及类型检查通过。Python 仅有现有 PyMuPDF/SWIG 弃用警告。此前 128 项 Python、3 项阅读器测试的历史诊断仍保留在基础提交，未计入本轮 19 项。

## 性能诊断与验证范围

基础提交中的轻量性能诊断、数值 JSON / Markdown、请求计数与阶段等待记录继续随 XPI 和源码包交付。此前 19 页基准的翻译包含 94 次缓存命中，16 次真实 AI 标注请求，Python 流水线为 122.90 秒，AI 识别为 103.86 秒。该历史基准与本轮合成 Mock 收尾验收分别保留其范围。

本轮真实付费模型调用为零，日常 Zotero 资料库和已有用户缓存未参与测试。14.552 秒仅说明合成 Mock 链路完整结束，真实模型速度、真实论文准确性、冷缓存 30–40 页总耗时仍需单独验证。Windows、Linux、其他 Zotero 版本以及翻译进行中的关闭标签行为未在本轮原生流程复测。失败和取消的原生用例覆盖已加载译文上的 AI 标注，首次翻译中的取消沿用既有实现与历史测试。

本地原始结果、受控错误诊断、资料库与画布位于 `tests/output/v025*`、`.test-profile/v025*`、`.test-data/v025*`、`.test-runtime/v025*`，全部排除在提交和发布包之外。公开报告和测试材料只包含作者合成内容及阶段、计数等信息。
