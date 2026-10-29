# TransYH third-party notices

TransYH is licensed under AGPL-3.0-or-later. No cloud translation platform or membership is required.

Research snapshot: 2026-10-28, confirmed from upstream release endpoints and source licenses.

| Project | Current release inspected | License | Use in TransYH |
| --- | --- | --- | --- |
| [BabelDOC](https://github.com/funstory-ai/BabelDOC/releases/tag/v0.6.4) | 0.6.4 | AGPL-3.0 | Separately installed local Python library; PDF layout, formula protection and monolingual output |
| [PDFMathTranslate Next](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next/releases/tag/v2.9.0) | 2.9.0 | AGPL-3.0 | Studied API/configuration; not bundled or required |
| [Z-Transplit](https://github.com/Liozhang/z-transplit/releases/tag/v1.13.1) | 1.13.1 | AGPL-3.0 | Studied single-tab native reader construction and realm boundaries; no source files copied |
| [Zotero Plugin Toolkit](https://github.com/windingwind/zotero-plugin-toolkit/releases/tag/v6.0.0) | 6.0.0 | MIT | ProgressWindowHelper bundled by esbuild; MIT notice included below |
| [Zotero](https://github.com/zotero/zotero) | Installed 9.0.6 | AGPL-3.0 | Native host/runtime reader APIs; no Zotero code bundled or patched |

BabelDOC downloads its own layout model and fonts on first use. Those assets retain their upstream licenses. They are not included in this XPI. See BabelDOC's asset metadata for their notices. TransYH's installer does not bundle or redistribute those assets.

## Zotero Plugin Toolkit MIT license

Copyright (c) 2022 windingwind

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
# Published demonstration article

The screenshots under `docs/demo/` reproduce excerpts of Guo J-X, Wu Y, Zhang T-D, Lv F-L, Gong Y-F (2025), *Dual niche modeling with GEE and SHAP for predicting habitat shifts of Haloxylon ammodendron and Cistanche deserticola under climate change*, PLOS ONE 20(12): e0338809, https://doi.org/10.1371/journal.pone.0338809.

Article text and figures © 2025 Guo et al., licensed under Creative Commons Attribution 4.0 International: https://creativecommons.org/licenses/by/4.0/. Chinese translation, page selection and AI highlights are adaptations produced for the TransYH demonstration and do not imply author, publisher or Zotero endorsement. Figure captions and their source attribution are retained. See `docs/demo/README.md` for the official sources, exact pages and verification boundary. The article content remains under CC BY 4.0; the project's AGPL-3.0-or-later license does not replace that license.
