# GitHub 实页渲染验收

日期：2026-10-29（Asia/Shanghai）。预览来自 Safari 中实际打开的 [GitHub 文档分支](https://github.com/pilipala5/TransYH/tree/docs/product-visual-v023#readme)，README 与主视觉对应提交 `017225eed92267cef0815214539a7b2d868d816d`；后续提交仅补充素材说明和本目录预览。没有用本地 HTML 模拟 GitHub，也没有重绘或替换页面内容。

| 预览 | 实际内容 |
| --- | --- |
| [readme-preview.png](readme-preview.png) | 桌面 README 起点，品牌区与完整 Hero |
| [readme-narrow.png](readme-narrow.png) | 约 574 px 窄窗口，品牌区、Hero、四个入口和版本来源说明 |
| [features-narrow.png](features-narrow.png) | 窄窗口中的上下中英文对照与原生语言切换细节 |
| [quick-start-narrow.png](quick-start-narrow.png) | 窄窗口中的 AI 标注前后对照、v0.2.3 说明与双组件安装提示 |

原生截图为 2× 屏幕像素。交付图只裁去浏览器工具栏和无关空白，再等比缩小以控制文件体积；没有拼接、着色、补写文字或移动页面元素。截图保留 GitHub 的 README 导航条。窗口尺寸在验收后已恢复。

本轮检查了原生 Markdown 渲染、相对图片路径、入口与下载目标、文件体积、Git diff 和截图可读性。正文可选择与搜索；三个功能图在窄窗口上下排列，没有横向溢出。XPI 和源码包的真实下载地址均返回 HTTP 200；外部 DOI、许可及依赖文档链接也可访问。截图保留旧界面的版本声明，论文署名和衍生说明在首页及品牌文档中可见。

取得的实页截图均为 **Light 模式**；窄窗口不等于手机真机验收。本轮没有取得 Dark 模式实页截图。Dark 适配采用 GitHub 原生正文主题与自带底色的同一套 SVG/PNG，不额外指定 README 正文文字或背景颜色。

未运行 Python/插件测试、Zotero 回归或真实模型，没有重新翻译、重装依赖、修改插件/API/引擎、重建或改写 XPI。`docs/demo/` 原始截图保持不变。
