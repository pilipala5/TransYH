# TransYH 0.1.0 测试记录

当前 0.1.4 的质量检测、重新翻译、状态写入与资源释放回归见 [0.1.4 测试记录](V014_TEST_RESULTS.md)。本文件原有记录保留。

后续真实组内服务验证与问题定位见 [0.1.1 记录](REAL_API_TEST_20261029.md)；并发与进度修复、0.1.3 测试及真实 26 页论文结果见 [速度修复记录](PERFORMANCE_FIX_20261029.md)。下文保留 0.1.0 当日的 Mock 测试边界。

测试日期：2026-10-28（Asia/Shanghai）。所有 PDF 均为本项目原创合成样本，使用本机 Mock API，没有使用真实第三方 Key 或用户现有论文。

## 环境与边界

- 实际启动并执行测试的客户端：Zotero **10.0.6**，macOS Apple Silicon。
- 初始检测到运行中的旧客户端为 9.0.6；应用磁盘版本随后为 10.0.6。本次运行结论适用于 10.0.6，不把 9.x 的源码检查视为运行通过。
- 独立资料库 `.test-data/`，独立配置 `.test-profile/`。没有读取或修改原有文献资料库，没有修改 Zotero 核心文件。
- 本地引擎：Python 3.12.13、BabelDOC 0.6.4、PyMuPDF 1.26.7、bitstring 4.3.1、OpenAI Python SDK 3.40.0。Apple Silicon 环境依赖记录在 `engine/requirements-macos.lock`。
- Mock 仅替代 OpenAI Chat Completions 的模型输出。实际运行 BabelDOC 的版式模型、PDF 解析、公式保护、字体写入、排版和 PDF 生成。
- UI 运行验证由隔离测试扩展在实际 Zotero 进程内执行，验证真实阅读器对象、PDF 数据、DOM 按钮及附件数据库。系统辅助功能截图接口在本机超时，没有以 GUI 截图替代行为验证。

## 已执行且通过

| 检查 | 结果与证据 |
| --- | --- |
| TypeScript 类型检查与 XPI 构建 | `npm run typecheck`、`npm run build` 成功；使用 Zotero AddonManager 实际安装 XPI |
| URL 与错误处理 | 4 个 Node 测试通过：根地址、版本路径、网关路径、完整接口、非法地址、状态码和页码边界 |
| Python API 与凭据错误保护 | 16 个 pytest 用例通过：成功、401/403/404/429/500、超时、空内容、错误 JSON 结构、重定向、错误输出不含测试 Key、依赖检测等 |
| 设置与凭据 | TransYH 设置片段实际加载并初始化；API 请求通过 Gecko Subprocess stdin 执行；Login Manager 保存、读取及重启读取成功 |
| 原生工具栏 | 两个原生 PDF 实例均有“中文 | EN”按钮；文献右键翻译菜单存在 |
| 实际 UI 回调 | 派发右键菜单 command 后同标签切到中文；中文原生右键菜单回调保留；设置页“测试连接”按钮实际报告 429 和连接成功 |
| 同标签切换 | 测试前后阅读标签数量为 4 → 4，标签 ID 不变；原文及译文的 PDFDocument 对象均保持同一对象，未重新打开 PDF |
| 阅读位置与缩放 | 第二页、145% 缩放、PDF 坐标 top=540/left=-141，在 EN → 中文后相同；四次后续切换也保持状态 |
| 缓存切换耗时 | 完整验收轮四次为 **31 / 22 / 16 / 15 ms**；这是该本机合成样本的程序计时，不是所有机器或论文的性能承诺 |
| 取消与重试 | 取消正在运行的本地子进程，显示取消原因；同一源附件随后重试完成 |
| 完整链路 | 原 PDF → 本地 BabelDOC → Mock Chat Completions → 中文 PDF → 同一父条目中文附件 → 原阅读标签显示中文；该轮 Mock API 调用 9 次 |
| 完成附件复用 | 再次执行返回同一中文附件 ID，额外 API 调用 **0 次**；英文原件大小及修改时间保持不变 |
| 段落缓存 | 单独重跑引擎返回 `cachedParagraphs=9`，缓存为 BabelDOC 实际缓存 |
| 真正关闭并重启 Zotero | 进程 PID 改变；恢复中文、第二页、133%、top=555/left=-182；再次翻译仍返回同一附件，额外 API 调用 0 次 |
| 本地引擎安装器 | `install-engine.command` 实际运行成功，安装到标准检测目录；插件通过自动检测使用该路径成功完成翻译 |
| 依赖一致性 | 开发环境及标准引擎环境的 `uv pip check` 均通过 |

pytest 出现 PyMuPDF/SWIG 的弃用警告，未导致用例失败。

## PDF 版式检查

原创样本含三页：单栏正文；公式 E=mc²、位图、图注及三列表格；双栏段落。

- 原文与译文均为 3 页，每页 612 × 792 pt。
- 中文正文可提取；三页分别包含 342、119、847 个中文字符（Mock 固定输出）。
- 第二页图像对象数量为 1 → 1，公式、上标、编号和表格数字保留。
- 将最终 Mock 译文三页渲染为 PNG 并逐页查看：未发现正文跨栏重叠、图表遮盖、方框字或明显截断。图像、公式及表格位置保持。
- Mock 段落采用重复的中文测试句，**不代表对原始英文的忠实翻译，不用于语言质量评估**。真实模型仍可能产生译错、漏译或未翻译内容。

原始机器记录：`tests/output/zotero-results.json`、`tests/output/layout-check.json`。排版证据：`tests/output/translated-page-1.png` 至 `translated-page-3.png`；样本译文：`tests/output/paper-chinese-mock.pdf`。

## 开发中发现并修复

1. Zotero 插件 manifest 必须提供 HTTPS 更新 URL；本地无更新服务，因此使用保留域名 `transyh.invalid` 并采用手动更新。
2. `display:none` 会折叠 PDF.js 视口并使页码暂时回到首页。最终采用保持尺寸的显隐、独立原生实例和显式 PDF.js 位置更新。
3. 隐藏内容文档的 requestAnimationFrame 会被节流到约一秒。最终使用主窗口布局帧和有界等待，复用两份 PDF 对象。
4. 初始化新浏览器会触发原阅读器瞬时重布局。切换使用点击当时的阅读位置，避免把瞬时首页状态误当成用户移动。
5. BabelDOC 0.6.4 宽泛的依赖约束会安装移除 `BitStream` 的 bitstring 5；固定为 4.3.1，同时固定 PyMuPDF 1.26.7。
6. BabelDOC 的异步终止事件存在跨线程时序风险；收到 `finish` 后立即结束消费，避免完成后一直等待。
7. Gecko 新版 Login Manager 使用 `addLoginAsync`。兼容层已适配，并在实际进程中验证凭据往返和重启持久化。
8. Zotero 设置页是片段而非独立 XML 文档；移除 XML 声明并在片段加载后初始化，实际设置页已通过。

## 仍未真实验证

- 用户实际配置的第三方 API、真实模型翻译准确性、真实计费与各种供应商限流策略。
- 用户自己的普通论文、复杂数学论文、跨页长表格或特殊字体论文的逐篇人工校对。
- Zotero 9.x 的完整运行回归、Windows、Intel macOS 和 Linux。
- 大型或数百页 PDF 的内存、初次加载延迟和页面同步长期稳定性。
- 纯扫描 PDF/OCR、加密 PDF、重排文本阅读模式和独立阅读窗口不在本版支持范围内。

## 复现

```bash
npm ci
npm run typecheck
npm run build
npm test
npm run test:engine
npm run test:zotero
npm run package
```

引擎测试前按 README 安装 `.venv` 开发依赖。Zotero 测试默认使用 `/Applications/Zotero.app/Contents/MacOS/zotero`，可通过 `TRANSYH_ZOTERO` 指定另一客户端路径。测试工具只在项目隔离目录中工作；测试用扩展不要安装到日常使用的配置文件。
