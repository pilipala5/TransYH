# TransYH 品牌与产品展示素材

面向 v0.2.3 文档的品牌系统。所有产品画面取自 [v0.2.0 真实演示](../demo/README.md)，没有运行新版客户端、重译论文、调用模型或修改 XPI。

## 设计

标识用两枚交错的阅读页角表达“同页双语”，中间的一行文字表达阅读重点。使用单一深色底、白色轮廓与品牌蓝，保持小尺寸可识别；不是插件已安装图标的修改。

| 用途 | 颜色 |
| --- | --- |
| 主色与标识底色 | 深海军蓝 `#17243D` |
| 品牌、核心发现 | 蓝 `#4378D8` |
| 关键数据 | 橙 `#EF8A48` |
| 有依据的方法创新 | 紫 `#8B65CF` |
| 浅底 | `#F3F5F8`、白色 |

品牌色与真实 AI 类别一致；不按品牌色重新绘制产品标记。真实演示没有紫色创新，不补画。文字标签同时表达颜色语义。

README 使用原生 Markdown、居中段落与 SVG 标识，无自定义 CSS、脚本或框架。图片以相对路径引用，在 GitHub 容器内按宽度缩放；所有对照上下排布，移动端自然纵向阅读。深色 Hero 和带独立浅色底的截图在 GitHub Light / Dark 下保持原样，无需明暗两套素材。关键产品说明、安装前提和颜色语义保留为可选择的正文。

## 交付文件

| 文件 | 尺寸 | 内容与来源 |
| --- | --- | --- |
| [logo.svg](logo.svg) / [logo.png](logo.png) | 96×96 视图 / 512×512 透明 PNG | 可编辑矢量标识及预览 |
| [hero.png](hero.png) | 1600×920 | `highlights-after.png` 两段完整正文 + 明确分隔的同页表格局部 + 独立原生控件细节 |
| [comparison.png](comparison.png) | 1440×1176 | `reader-english.png`、`reader-chinese.png` 同页段落，上下排列 |
| [switching.png](switching.png) | 1440×410 | 两份原始阅读器顶部右侧控件的连续局部，各自保持完整按钮 |
| [highlights.png](highlights.png) | 1440×658 | `highlights-before.png`、`highlights-after.png` 同一段落前后对照 |
| [social-cover.png](social-cover.png) | 1200×630 | 品牌文案 + 真实中文标注画面 |
| [generate.py](generate.py) | — | 生成全部素材；集中记录原截图坐标、文案、排版和颜色 |

源文件在 `docs/demo/`，保持原文件不变。只进行矩形裁切、等比缩放、外部版面组合和 PNG 导出压缩，不改正文、数值、结论、控件或标记。Hero 和社媒封面的正文、表格是明确分隔的独立裁切，跳过中间段落，不暗示原论文中两者相邻；所示两个正文段落与表 1 均完整保留。对照排布并非产品分屏；Hero 的语言控件是单独注明的放大细节，没有拼装成虚构的新版阅读器。

## 重新输出

在已有 Pillow 的 Python 环境运行：

```bash
python3 docs/brand/generate.py
```

脚本无网络请求，不读取个人文献、凭据或 API 配置，不改插件文件。默认字体为 macOS 黑体简体与 Avenir Next；Linux / Windows 可通过 `TRANSYH_FONT_REGULAR`、`TRANSYH_FONT_BOLD`、`TRANSYH_FONT_INDEX`、`TRANSYH_FONT_LATIN` 指定已有的中文和西文字体。字体仅用于导出，未打包字体文件。PNG 使用 256 色无抖动编码，控制截图放大后的下载体积。

未来换图时，先保存来自实际客户端的新截图，再修改脚本中 `crop()` 的文件名和像素坐标；同步更新版本、来源和许可说明。不要用绘图控件或补画标记代替真实截图。

## 原论文署名与改编说明

Guo J-X, Wu Y, Zhang T-D, Lv F-L, Gong Y-F (2025). *Dual niche modeling with GEE and SHAP for predicting habitat shifts of Haloxylon ammodendron and Cistanche deserticola under climate change*. PLOS ONE 20(12): e0338809. [DOI: 10.1371/journal.pone.0338809](https://doi.org/10.1371/journal.pone.0338809).

原文与图表 © 2025 Guo et al., [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。中文翻译、AI 高亮、截图节选及排版组合是 TransYH 的衍生展示，不代表原作者、PLOS 或 Zotero 认可。涉及原论文的素材继续受 CC BY 4.0 署名与改编说明约束，不改用项目的 AGPL 许可；品牌原创矢量和生成脚本随仓库 AGPL-3.0-or-later 提供。

本演示仅翻译原第 7、9、13 页，没有公式主体所在的第 8 页。三页展示不代表整篇论文准确率、公式翻译质量或模型性能验证。图中数值属于原论文的生态位模型结果，不是 TransYH 的质量指标。来源、请求范围、接受的 4 橙 + 1 蓝标记及核对边界均见[演示记录](../demo/README.md)。
