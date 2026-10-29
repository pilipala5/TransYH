# TransYH v0.2.0 发布审查材料

日期：2026-10-29（Asia/Shanghai）。分支 `feature/ai-highlights-v0.2.0`，验收起点 `b227c4bfa327281157d1c1c9d1730c1d4b4f0334`。保持 0.2.0，不修改 main，不合并、不强制推送或删除分支。本文件汇总本轮真实证据，历史结果不计作本轮通过。

## 修改范围

| 文件 | 变化 |
| --- | --- |
| `README.md` | 重排项目首页：真实截图、最短安装流程、XPI/引擎区分、API 费用、三档密度与限制 |
| `docs/USAGE.md` | 保留原 README 的完整技术细节，修正迁移后的相对链接 |
| `docs/demo/README.md`、`verification.json`、`accepted-highlights.json` | 真实来源、版权、原生截图方法、真实 API 界限、5 处源文核对 |
| `docs/demo/*.png` | 六个真实阅读器截图文件，其中标注前与中文图为相同原始字节 |
| `V020_TEST_RESULTS.md`、`CHANGELOG.md`、本文件 | 当前测试与交付说明，区别历史 Mock/旧验收 |
| `THIRD_PARTY_NOTICES.md` | 增加真实论文及衍生截图的 CC BY 署名 |
| `dist/TransYH-0.2.0.xpi`、`dist/TransYH-0.2.0-source.zip` | 最终统一打包，版本不变 |

没有修改核心翻译、缓存、阅读器或密度算法；无依赖变化，不运行 npm ci。

## 论文、许可及实际页码

Guo J-X, Wu Y, Zhang T-D, Lv F-L, Gong Y-F (2025), *Dual niche modeling with GEE and SHAP for predicting habitat shifts of Haloxylon ammodendron and Cistanche deserticola under climate change*. PLOS ONE 20(12): e0338809.

[DOI](https://doi.org/10.1371/journal.pone.0338809) · [PLOS 官方页面](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0338809) · [官方 PDF](https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0338809&type=printable) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) · [PLOS 复用政策](https://journals.plos.org/plosone/s/licenses-and-copyright)。

原 PDF 23 页，只翻译第 **7、9、13 页**，对应节选 1、2、3 页，页脚保留原始页码。第 7 页为方法/SHAP 文字，第 9 页为 Results、模型性能及表 1/2，第 13 页为生态分布图 3/4。公式主体位于未选取的第 8 页，本次未验证其真实中文翻译，未为补截图追加翻译。

文章及图表 © 2025 Guo et al., CC BY 4.0；截图保留图号、来源图注和 DOI。中文翻译、节选与 AI 标记属于 TransYH 衍生展示，不代表原作者、PLOS 或 Zotero 认可。图 3/4 的原图图注说明 GEE Data Catalog 来源，未见单独版权例外；本轮只引用已发表图，不重新分发底层地图数据，也不声称 GEE 全目录统一授权。完整许可核对见[演示说明](demo/README.md)。

## GitHub 展示素材

README 使用相对路径，当前开发分支及未来 main 均可解析；没有使用本机路径或临时图片地址。下列链接指向开发分支：

| GitHub 可访问文件 | 来源与状态 |
| --- | --- |
| [reader-english.png](https://github.com/pilipala5/TransYH/blob/feature/ai-highlights-v0.2.0/docs/demo/reader-english.png) | 官方原文第 9 页，真实 Zotero 的 EN 状态 |
| [reader-chinese.png](https://github.com/pilipala5/TransYH/blob/feature/ai-highlights-v0.2.0/docs/demo/reader-chinese.png) | 第 9 页真实模型译文，标注前 |
| [highlights-before.png](https://github.com/pilipala5/TransYH/blob/feature/ai-highlights-v0.2.0/docs/demo/highlights-before.png) | 同页同尺度的标注前对照，与上一图字节相同 |
| [highlights-after.png](https://github.com/pilipala5/TransYH/blob/feature/ai-highlights-v0.2.0/docs/demo/highlights-after.png) | 第 9 页真实 AI 结果：4 橙色数据、1 蓝色发现 |
| [reader-methods.png](https://github.com/pilipala5/TransYH/blob/feature/ai-highlights-v0.2.0/docs/demo/reader-methods.png) | 第 7 页真实中文方法说明，没有凑紫色标记 |
| [reader-map.png](https://github.com/pilipala5/TransYH/blob/feature/ai-highlights-v0.2.0/docs/demo/reader-map.png) | 第 13 页生态分布图，配色是原图，不是 AI 高亮 |

均为 1120×1047 的原生阅读器区域截图，工具栏及中文/EN 按钮真实存在；通过 Gecko drawWindow 捕获实际运行的 Zotero 标签，没有从 PDF 图像合成软件界面。公开文件与本机原始捕获字节一致，无后期修图、补画或隐藏状态改写。已查看所有最终 PNG，未见私人条目、账户、Key 或个人配置。

本目录使用**真实模型**，无 Mock 论文内容或 Mock 标注。旧 `docs/highlights/` 是明确标记的合成测试样例，保留用于回归；不能作为真实论文识别效果证据。

## 模型、数据与标注复核

使用已有授权的个人 OpenAI-compatible 配置，模型 **gpt-6.1-sol**，无其他付费服务；Key 只在已有凭据库及进程管道中使用，未写入本记录。三页只翻译一次，约 **106.8 秒**；跟踪 67 个段落记录，质量报告 pass、无问题、2 次翻译缓存命中。翻译最终请求总数未保留，未推算费用。

智能密度标注：**2 次真实请求、5 处接受、3 处过滤、24.4 秒**；再次执行 **0 请求、5 处不重画**。同标签数 3→3，英文 PDFDocument 实例保留，英文文件逐字节不变，只有一份当前中文附件。公开[运行摘要](demo/verification.json)及[精确接受片段](demo/accepted-highlights.json)不含服务地址、凭据、资料库路径或私人论文。

5 处均对照官方原文第 9 页正文及表 1/2：

- 气候/梭梭：AUC 0.9559±0.0089、TSS 0.8168±0.0319、precision 0.8534±0.0363；保留近最优或最高。
- 气候/肉苁蓉：AUC 0.9199±0.0298、TSS 0.7596±0.0578、Boyce 0.9143±0.0520。
- 集成模型结论：限定为本文两个物种的气候生态位建模，没有扩展为所有情境或因果结论。
- 土壤/梭梭：AUC 0.9704±0.0093、TSS 0.9027±0.0287；保留接近或超过单模型。
- 土壤/肉苁蓉：AUC 0.9158±0.0290、TSS 0.7026±0.0707、sensitivity 0.9412±0.0807；保留总体指标略低于梭梭。

± 的统计含义未擅自扩展。以上为代理源文核对，不是独立专家盲评。未建立真实论文完整应标集合，不报告总体准确率或漏标率。提取文本存在 U+0003 样式分隔符和局部小数空格，视觉数值一致；仍可能影响搜索或严格匹配。

## 最终测试与发布审计

本轮统一执行以下流程；不重复开发阶段测试，不执行无关大型压力测试。依赖与 TypeScript 源码均未修改，未重复 npm ci 或 typecheck。

| 命令 | 本轮实际结果 |
| --- | --- |
| `npm test` | 9 项通过，0 失败 |
| `npm run test:engine` | 112 项通过，约 10.96 秒，5 条既有 SWIG 弃用警告 |
| `npm run test:zotero` | 完整通过，独立 Zotero 10.0.6，PID 90541→98992，仅套件要求的一次退出/重启 |
| `npm run package` | 通过；执行一次，XPI 仅构建一次，版本 0.2.0 |
| `python3 scripts/audit-release.py` | 通过；执行一次：80 个源码文件、16 个 XPI/build 文件、81 个源码 ZIP 条目，未发现凭据或本地运行资料 |

本轮原生回归覆盖设置与凭据、实际右键菜单、普通翻译复用、真实 BabelDOC+Mock、主动重译新版本、质量报告、旧附件兼容、状态恢复、快速切换、关闭释放、标注取消/失败/恢复/自动集成及重启。这里只替代模型响应，PDF 处理与 Zotero 客户端实际运行。

- AI 标注：首次 3 请求/3 处，重复 0 请求；取消后命中 1 批缓存，只补 2 请求；源文件、既有批注、附件数量不变，旧中文 PDF 加载任务释放，位置及缩放保留，重启后 0 请求复用。
- 可恢复重译：部分成功 3 段后失败（4 次请求），恢复命中 3 段，仅补 6 次；完成后再次主动重译新任务为 9 次、0 缓存。取消后恢复命中 2 段、补 7 次；导入后未确认任务的中断也完成核对。3 份旧附件、1 条批注保留。
- 同标签页码/缩放/位置一致；原有 20 次快速切换用例只保留 1 个辅助浏览器。关闭 5 个标签释放 5 个 PDF 任务，关闭后会话为 0；空闲 5.5 秒无额外状态写入。
- 0/1/3/5 处渲染、重开、重复标注及三档缓存用例包含在这次 112 项引擎测试中，没有另跑开发阶段测试。

正式审计后将实际结果写入本文及测试记录，只刷新源码 ZIP 以收录记录，不再次构建 XPI；最终 ZIP 再核对条目、源文件字节一致性及凭据/运行资料排除。公开截图和 README 使用相对路径，下载文件在推送后另做可访问性核对。

## 剩余风险与审查边界

- 三页展示不等于整篇翻译验收、独立语义准确率评测或全面术语校对；原文第 8 页公式未作真实中文验证。
- 第 7 页节选缺少总章节标题，当前章节规则未将其纳入 AI 请求；真实模型识别仅覆盖节选第 2、3 页，未验证该方法页的创新识别。
- 没有可靠作者创新候选就不产生紫色；模型及本地规则仍可能误标或漏标，作者报告不等于独立证明。
- Windows、Linux、Intel macOS、Zotero 9.x、云同步冲突及真实断电仍未在本轮环境验证。
- 原生阅读器使用部分私有接口，未来 Zotero 大版本升级仍需回归；图形备份和退休对象会增加磁盘占用。
- 本轮不会创建正式 GitHub Release 或合并 main，交由 ChatGPT 复查后决定。

## 提交与下载

- [开发分支](https://github.com/pilipala5/TransYH/tree/feature/ai-highlights-v0.2.0) / [最终提交记录](https://github.com/pilipala5/TransYH/commits/feature/ai-highlights-v0.2.0)。本文件与最终产物同批提交；完整最终 Commit SHA 在交付答复中提供。检出后可用 `git log -1 --format=%H -- docs/RELEASE_REVIEW_V020.md` 取得本文所属提交，不在提交自身内容中伪造自引用 SHA。
- [XPI](../dist/TransYH-0.2.0.xpi?raw=true) / [完整源码 ZIP](../dist/TransYH-0.2.0-source.zip?raw=true) / [README](../README.md) / [本轮测试记录](../V020_TEST_RESULTS.md)。相对下载路径可随分支合并保留；交付答复另附最终提交的固定下载链接。
