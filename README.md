# TransYH

为 Zotero 9–10 开发的科研 PDF 全文英译中插件。使用本机 BabelDOC 排版引擎和你自己的 OpenAI 兼容 API，只生成一份中文 PDF，以独立附件保存；英文原件始终保留。

**0.2.0 新增 AI 科研重点标注**：已有中文 PDF 可直接标注蓝色核心发现、橙色关键数据和紫色方法创新，保持同标签“中文 | EN”。自动标注默认关闭；只使用用户自配 API，没有新的商业阅读或 PDF 服务。测试与限制见 [0.2.0 验收记录](V020_TEST_RESULTS.md)。

已包含 0.1.4 的本地 PDF 质量检查和 **重新翻译 · TransYH**，优化阅读状态保存与双 PDF 实例释放。默认 4 个并发段落，保留实际耗时、段落进度和请求状态，可在设置中调整为 1–8；此前速度修复见 [记录](PERFORMANCE_FIX_20261029.md)。该阶段改动及验证见 [版本记录](CHANGELOG.md) 和 [0.1.4 测试记录](V014_TEST_RESULTS.md)。0.1.1 已增加单个远程 HTTP 服务的明确授权、安全的 macOS 一次性配置导入，并统一连接测试和翻译使用的 API 客户端。已通过用户自配服务的 `gpt-6.1-sol` 真实三页翻译验证，见 [真实 API 测试记录](REAL_API_TEST_20261029.md)。此版本不在代码或 XPI 中预设任何人的地址、模型或 Key。

阅读器工具栏提供 **中文 | EN**。同一个 Zotero 标签中保留两个原生阅读实例，通过显隐切换，保持页码、缩放模式和 PDF 页面坐标。首次打开某一语言需要加载 PDF，之后切换复用内存中的实例。中文视图只读，英文视图保留 Zotero 原生批注功能。

## 安装

1. 下载 [TransYH-0.2.0.xpi](dist/TransYH-0.2.0.xpi) 或 [完整源码包](dist/TransYH-0.2.0-source.zip)，也可运行 `npm ci && npm run build` 自行构建。
2. Zotero → 工具 → 插件 → 右上角齿轮 → **Install Add-on From File / 从文件安装插件**，选择 XPI。
3. 安装本地引擎。macOS / Linux 需要 [uv](https://docs.astral.sh/uv/getting-started/installation/)；使用 Homebrew 可先运行 `brew install uv`。然后在项目目录运行：

   ```bash
   chmod +x install-engine.command
   ./install-engine.command
   ```

   macOS 也可直接双击该文件。脚本由 uv 管理 Python 3.12 和独立虚拟环境，固定 BabelDOC 0.6.4 及必要的兼容依赖。Apple Silicon 使用完整依赖锁定文件。

   Windows 安装 uv 后，在项目目录的 PowerShell 运行 `./install-engine.ps1`。Windows 路径及脚本已实现，尚未在 Windows 客户端验证。
4. Zotero → 设置 → **TransYH**，点击 **检测本地引擎**。

引擎自动检测目录：

| 系统 | Python |
| --- | --- |
| macOS | `~/Library/Application Support/TransYH/engine/bin/python` |
| Windows | `%LOCALAPPDATA%\TransYH\engine\Scripts\python.exe` |
| Linux | `~/.local/share/TransYH/engine/bin/python` |

也可在插件设置中填写其他虚拟环境的 Python **可执行文件完整路径**。应使用 `engine/requirements.txt` 中的固定版本。仅安装到系统 Python、但不填写其路径，不会被插件误识别为已配置引擎。

首次翻译由 BabelDOC 自动下载开源版式检测模型及字体，下载资源约数百 MB；本次 macOS 安装的 Python 依赖约 670 MB，模型与字体约 250 MB。需要网络、约 1 GB 以上可用空间和额外的 PDF 临时处理空间。首次模型编译可能比后续任务慢。没有商业翻译平台账号要求。

## API 配置

填写你自己的 **API Base URL、API Key、Model**，点击 **保存设置**，再点 **测试连接**。不预选任何供应商或模型。测试连接会发送一次很小的真实模型请求，费用由你的 API 服务商计收。

支持以下地址形式：

```text
https://provider.example           → https://provider.example/v1
https://provider.example/v1/       → https://provider.example/v1
https://provider.example/v1/chat/completions → https://provider.example/v1
https://gateway.example/api/openai/v1       → 保留自定义路径
http://localhost:8000/v1                    → 支持本机服务
```

插件在规范化后的地址追加 `/chat/completions`。远程地址默认使用 HTTPS；内网或组内服务只有在设置中明确勾选“允许此地址使用 HTTP”后才可使用 HTTP，授权仅适用于当前保存的完整服务地址。本机 localhost、127.0.0.1 和 ::1 可直接使用 HTTP。不接受地址内的密码、查询参数或锚点。模型名称直接使用服务商提供的标识；本机无鉴权接口可留空 Key。

Key 使用 Zotero/Gecko 登录凭据管理器加密保存于 Zotero 配置文件中，**不写入普通偏好设置**。这不是独立的 macOS Keychain 条目。与 Zotero 配置文件一起备份或迁移时，应妥善保管该配置文件。插件只通过匿名标准输入管道将 Key 交给本地 Python，命令行中不包含 Key，也不记录 API 原始错误响应。

如果已为这台 Mac 准备了一次性配置，插件安装/启用时会从 macOS Keychain 读取预先安全保存的 Key，再写入 Zotero 的加密凭据库。一次性 JSON 只包含地址、模型及 HTTP 授权，成功应用后会删除；Keychain 本身保留加密凭据。普通安装不触发这项引导，也不会自动读取其他服务的凭据。

## 使用

1. 选中文献条目或 PDF 附件，右键 → **翻译全文 · TransYH**。文献有多个 PDF 时使用 Zotero 的最佳 PDF 附件。
2. 进度提示显示当前阶段、段落计数、已耗时和等待模型的请求数。可右键 → **查看翻译进度 · TransYH** 重新显示；需要停止时选择 **取消全文翻译 · TransYH**。
3. 完成后同一文献条目下出现 `… · 中文 (TransYH)` 附件，自动在阅读器中显示中文。
4. 已有译文但希望使用当前 API/模型更新时，右键 → **重新翻译 · TransYH**。首次建立独立缓存命名空间；失败、取消或中断后，同一原文和配置下再次执行会尽可能复用已完成段落。成功导入后再次主动重译会建立全新任务，并重新产生模型费用；不清空其他文献的缓存。成功后同标签显示新版中文，失败或取消保留旧版本。旧附件及其批注保留，可在文献列表中自行管理；插件不自动删除旧附件。
5. 点击顶部 **中文 | EN** 切换。已有阅读标签会直接复用；从文献列表开始且尚无阅读标签时，会创建一个原文阅读标签，再在该标签内显示中文。

没有译文时点击 **中文** 也可直接启动全文翻译。首次阅读默认英文；已有本地阅读记录时恢复上次语言和进度。直接打开中文附件时也可切回英文。

失败或取消后再次执行同一入口即可重试。普通翻译会直接复用已生成且源文件未变化的中文附件，不再调用 API；已有旧译文时，恢复失败的主动重译应再次选择 **重新翻译 · TransYH**。普通段落缓存仍区分模型、API 地址和语言，Key 变化不改变普通缓存；重译任务额外隔离原文内容、来源附件、模型、服务和凭据变化。并发数调整不会破坏任务恢复。

重译状态只保存在本机 Zotero 数据目录的 `transyh/retranslation/refresh-tasks.sqlite3`，只含不透明任务身份、UUID、版本、状态和时间。身份由原文内容及配置生成，凭据仅在内存中作为 HMAC 密钥参与匹配；数据库不保存原文、文件路径、模型/服务地址或 API Key。事务写入支持异常中断恢复；如果任务记录损坏，插件报错并保留旧记录和缓存，不自动清空。安全导入附件后才标记完成；若在导入成功与确认完成之间中断，下次重译会核对已导入的版本并开启新任务。跨设备迁移或引擎自行淘汰的缓存不保证恢复。

译文附件带有 `TransYH:source:<原文key>` 和源文件大小/修改时间标记。0.1.4 新增 `TransYH:version:<时间与随机版本标识>`，普通翻译和切换优先选择当前源文件对应的最新可用附件；兼容没有版本标记的 0.1.3 附件。版本标签不包含模型服务地址、API Key 或令牌。重启后通过这些标记识别译文，原附件不被覆盖。请勿删除这些标记；它们也可随 Zotero 附件同步。本地阅读状态位于 Zotero 数据目录的 `transyh/reading.json`，不随附件同步。

## AI 科研重点标注

已有中文译文：选择原文、文献条目或已关联的中文附件，右键 → **AI 标注重点**，处理当前最新中文附件，不重新翻译。设置中的 **翻译完成后自动标注重点** 默认关闭，开启后对后续新生成的中文 PDF 自动执行；已有译文可使用手动入口。标注失败仍交付并保留中文译文。

| 颜色 | 内容 |
| --- | --- |
| 蓝色 | 作者实际报告的核心发现、关键结论 |
| 橙色 | 包含指标、单位或比较对象的重要定量结果 |
| 紫色 | 作者明确提出且有创新依据的方法 |

每页最多两处，短句优先，可完全不标；另有字符密度和重叠限制。背景、常规方法、文献综述及参考文献不按数字或英文数量标记。模型自报 confidence 只用于候选过滤，不是事实可靠性证明；标注不是独立证据，仍需核对论文。

本机从现有中文 PDF 提取字符、位置和段落 ID，识别可确认的章节，只将合适的中文段落发送给当前 API。原论文中的文字作为待分析数据处理，不执行其中的提示指令。模型必须返回输入中的精确连续片段；本地严格匹配，歧义、改写、错误数字、丢弃关键限定条件、无法定位或超出密度限制的候选被跳过。没有可靠的中英文段落对齐时不拼接猜测英文对应关系；当前模块依据中文译文识别，无法纠正既有译文的事实错误。

使用半透明、可选内容的 PDF 图形层，不生成新正文、不移动图表或公式，不向 Zotero 批注表插入 AI 批注。同一中文附件 ID 保持不变，原有 Zotero 批注和 PDF 内嵌批注保留。源英文还会按实际文件身份检查，符号链接或硬链接指回英文原件也拒绝写入。仅支持本地、可编辑的已导入中文附件；链接附件、签名、加密或损坏文件不进行更新。

修改前在数据目录 `transyh/highlights/backups/` 生成原 PDF 的完整备份，先核验暂存结果，再同目录原子替换；`transyh/highlights/transactions/` 记录备份与目标的对应关系。启动时未确认的事务自动回退到原文件；检测到外部修改时保留文件和备份，停止覆盖。已确认的更新保留新版和原备份，不新增第二个中文附件。短暂的安全保存阶段完成后再结束任务；模型识别阶段可用现有取消菜单停止。

重复同一 PDF/模型/服务/提示词与规则版本的标注不会再次调用 API，也不会叠加高亮。部分成功的识别结果可以在失败、取消后的重试中复用；尚未返回或未写入缓存的请求不能保证复用。缓存只含不透明身份、段落 ID、字符偏移量及类别，不含正文或 Key；位于 `transyh/highlights/cache/`，不与普通翻译缓存混用，不清空其他论文缓存。更换模型、服务或提示词/规则版本会重新识别并替换本插件的图形层，原有用户批注仍保留。备份与结果缓存均只在本机保存；PDF 本身若由 Zotero 同步，标注图形会随该 PDF 一起同步。

当前为保守文本标注：旋转页、竖排、不可识别字形和缺乏明确章节/作者结果线索的片段会跳过；不读取嵌图文字，不做 OCR，不从图像推断数据，不验证跨文献的新颖性，也不证明因果性或数学语义。外部 PDF 编辑器重写标注层记录时会拒绝猜测更新。历史备份与退休的 PDF 图形对象不会自动清理，更换配置多次标注可能增加磁盘占用。Windows、Linux、Zotero 9.x 及云端同步冲突尚未实测。

人工确认的六项合成参照见 [参考集](tests/fixtures/highlight-gold.json)，典型页面的实际原生渲染前后对照见 [截图说明](docs/highlights/README.md)。`tests/evaluate_highlights.py` 默认使用脚本化 Mock 计分；明确指定 `--live` 时才从 stdin 读取 API 配置并产生真实调用。本轮不运行 live，不以 Mock 计分宣称真实模型准确率。

## 本地质量检查

BabelDOC 完成排版后检查段落跟踪记录和最终 PDF，不额外调用 AI。结果分为 **通过**、**存在疑似问题**、**结构性错误，无法交付**。

- 段落规则检查有失败记录且仍保留英文的正文、空译文、异常缩短和大量未改动英文正文。只对具备句子特征的较长正文判断；专名、缩写、变量、代码、DOI 和识别到的参考文献不按英文字符数量判错。恢复成功的回退不会仅因先前一次失败被报错。
- PDF 规则检查页数/页面几何、文本越界、严重行重叠、提取异常、替代字符，比较页面中实际显示的图片区域与部分可提取公式。公式检查使用 BabelDOC 占位符和有限语法的公式片段，合并同一行的 PDF 文本对象，容忍空白、上下标和常见符号变化；英文句子正常译成中文不会单独触发告警。图片内部对象个数、xref 或编码不同不单独触发丢失判定。
- 普通疑似问题仅显示简短提醒，允许导入阅读。PDF 损坏、加密、页数或页面几何不匹配会阻止导入，保留已有附件。没有取得段落跟踪数据时也会明确标为疑似，不能宣称完整检查通过。

报告位于 Zotero **数据目录**的 `transyh/jobs/<资料库ID>-<原附件key>/<版本>/quality-report.json`，只含状态、问题代码、页码及计数，不含论文段落、API 地址或凭据，不上传 GitHub。引擎本身的段落缓存仍在本机 BabelDOC 缓存目录。每次任务目录独立，避免重新翻译覆盖之前的生成文件。

“通过”只表示这些规则未发现异常，不保证语言准确、所有公式正确或逐页视觉无误。无法可靠提取的公式不作缺失判断；同左端的公式排版变化、图形公式及数学语义变化可能漏检，不属于数学等价性校验。字体映射、复杂表格、跨页段落、参考文献分区识别和图像转矢量可能误报或漏报；乱码检查限可识别的替代字符/未映射字符，无法自动识别所有看似正常的错字。请核对重要术语、公式与图表。

## 构建与测试

需要 Node.js 22+ 和 Python 3（构建脚本使用 Python 标准库；翻译引擎独立使用 Python 3.12）。

```bash
npm ci
npm run typecheck
npm run build
npm test
npm run test:engine
npm run test:zotero
npm run package
python3 scripts/audit-release.py
```

引擎开发及 API 错误测试：

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r engine/requirements.txt pytest reportlab
npm run test:engine
```

`npm run test:zotero` 在 macOS 的独立 Zotero 配置和资料库中运行安装、工具栏、单标签切换、进度保存和翻译集成测试。测试资料位于 `.test-profile/`、`.test-data/`、`.test-runtime/`，不会读取现有文献或使用真实 Key。详细结果和可复现步骤见 [TEST_RESULTS.md](TEST_RESULTS.md)。Mock 只替代 API 响应；PDF 的解析、版式识别、公式保护及写出使用真实 BabelDOC。

## 兼容性与限制

- 本机实际运行验证为 **Zotero 10.0.6 / macOS Apple Silicon**。开发时曾检测到运行中的 9.0.6 及其源码接口，之后新启动客户端为 10.0.6。9.x 通过版本与接口探测支持，尚未完成 9.x 独立运行回归；Windows、Intel macOS 和 Linux 也尚未实测。
- 工具栏和 PDF 实例/位置同步需要未公开接口。所有访问集中于 `src/reader-compat.ts`，升级 Zotero 大版本可能需要适配。只支持原生 **PDF** 阅读模式；不支持 Zotero 10 的重排文本阅读模式、EPUB、外部阅读器或独立阅读窗口。
- 没有修改任何 Zotero 核心文件。切换不会调用打开另一个译文标签的 API。两份 PDF 同时驻留会增加内存占用；关闭标签或禁用插件会销毁额外实例和 PDF.js 加载任务。尚未对大型论文的峰值内存作出保证。阅读状态按变化去重、合并写入，并在关闭时保存。
- 中文视图只读，原文与译文批注不互相复制。中文实例有自己的原生查找、页码和缩放工具；Zotero 主菜单和右侧上下文仍关联该标签原始附件，涉及附件修改/导出时请使用文献列表中的相应附件。
- 页码同步依赖译文页数不变；若引擎输出页数不同，将拒绝导入。页面坐标同步是几何映射，不能保证两种语言中同一语句在相同垂直坐标。
- 不保证所有论文无排版问题。复杂跨页表格、文字嵌入图像、特殊字体、密集公式可能仍需核对；图片内部文字保留原图，专名、代码、数字、参考文献可能保留英文。
- 第一版不包含 OCR；纯扫描、加密或损坏 PDF 会给出错误。长文献成本和耗时由论文长度、模型、网络及服务商限流决定。
- 插件只将论文文字发往你配置的 API；BabelDOC 在本机解析、识别版式并排版。不提供聊天、总结、侧边栏、双语分屏或拼接 PDF。
- 第一版使用保留域名 `transyh.invalid` 作为 Zotero 要求的更新 URL，不提供自动更新。更新时手动安装新的 XPI。

## 源码结构

```text
addon/                 Zotero manifest、启动及设置片段
src/reader-compat.ts   原生阅读器私有接口兼容层
src/readers.ts         同标签显隐切换和状态保存
src/storage.ts         附件识别、凭据和本地阅读记录
src/engine.ts          Python 子进程与进度协议
src/index.ts           右键菜单、设置、任务调度
engine/worker.py       BabelDOC 与 OpenAI-compatible 适配
engine/quality.py      本地段落与 PDF 质量检查
engine/refresh_tasks.py 本地重译任务身份与事务状态
engine/highlight_pdf.py 精确字符定位、密度筛选及独立图形层
engine/highlight_jobs.py 自配 API 识别与本地偏移缓存
engine/highlight_install.py 完整备份、原子替换及事务恢复
scripts/               构建和隔离 Zotero 测试入口
tests/                 Mock API、原创测试 PDF 和行为测试
```

开源项目版本、许可证及使用方式见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。本项目以 **AGPL-3.0-or-later** 发布，完整许可证见 [LICENSE](LICENSE)。
