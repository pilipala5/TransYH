# 全文翻译与 AI 标注性能诊断

## 使用范围

本分支从 main `ab12275462c611cb1a4a75ecc5875d0e195afed4` 开始，增加本地数字指标和一个阅读器完成阶段的修复。Python 依赖沿用 BabelDOC 0.6.4、OpenAI SDK 3.40.0。

正常 `translate` 和 `highlight` worker 会在各自 outputDir 写入 `performance.json` 和 `performance.md`。`performanceDir` 可指定单独目录。Zotero 的任务目录另有 `task-performance.json`，记录 worker、附件导入、自动标注、原子提交及阅读器刷新阶段。标注安装阶段使用独立的 `installation-performance` 子目录。

记录仅含时间、计数、固定阶段代码、HTTP 状态码及 Token 数量。请求正文、论文文字、模型文本、服务地址、密钥和异常消息均排除在性能记录之外。PDF、原有缓存和安装事务继续使用原有本地存储路径。

## 一次性完整基准

从匿名标准输入传入现有 worker 配置。使用用户已经授权的服务、模型、密钥和 HTTP 地址授权，包含 `input`、全新的 `outputDir`、现有标注 `cacheDir`、`concurrency`、`apiMode` 和 `highlightDensity`。密钥应从现有凭据存储在内存中加入配置，禁止放到命令行、脚本源码或配置文件。

```text
.venv/bin/python scripts/benchmark-performance.py
```

脚本依次执行正式 worker 的全文翻译、AI 标注和备份式原子提交。生成的译文和提交目标位于独立基准目录。运行使用现有段落缓存和标注缓存。目录中的 `benchmark-started` 标记通过排他创建避免意外重复运行。失败后保留记录，由操作者检查原因和预算再决定后续操作。

该基准覆盖 Python 引擎流水线。Zotero 附件数据库、阅读器切换和 UI 结束状态由正常入口的 `task-performance.json` 单独记录。缓存命中的翻译无法提供真实翻译请求时延，需在结论中明确。

## 指标口径

- 总时间及阶段表使用互斥墙钟时间。BabelDOC 原始子阶段采用进度事件接收时间，其范围可包含多个内部步骤。页布局阶段的 items 可能包含多轮计算。
- 请求从 SDK 调用入口计时，到完整文本解析及流关闭后结束。实际并发是客户端在途调用数。服务端推理并发需要服务端证据。
- Responses 分别记录首个已解析事件、首个文本 delta、`response.completed`、最近事件和最大事件间隔。首个事件之前的网络、网关排队及模型准备耗时暂无法分开。
- 延迟统计覆盖完成的尝试，另提供成功请求统计。P50 和 P95 使用线性插值。Token 仅累计服务实际返回的 usage，并提供收到 usage 的请求数。cached_input 属于服务端输入 Token 缓存，段落及标注缓存有独立计数。
- `attempts_per_request_window_second` 的分母为首个请求开始至最后一个请求结束。`successes_per_total_second` 的分母为整个任务时间。不同分母应分别解读。
- 信号量、QPS、线程池排队和 SQLite 读写等待分别记录。多个线程的等待时间相加可能大于总时长，应同时查看 `union_wall_s`。`without_active_api_s` 仅表示等待期间客户端没有在途 API 的墙钟时长，不能直接视为可消除的关键路径时间。
- `translation_retries` 是 TransYH 传输层额外尝试数。BabelDOC 的逐段质量回退计入 `babel_fallback_paragraphs`，额外网络调用仍计入请求总数。AI 标注失败批次另行统计，API 成功后结构校验失败也会进入该计数。
- 每 5 秒保存一次数值快照。进程被终止时，最后快照可能仍显示 running，需要结合进程状态判断。快照时刻为 started_at_utc 加 elapsed_s，禁止把读取文件时的时间继续累加为处理耗时。

## QPS 与并发的实际作用

BabelDOC `BaseTranslator.translate` 和 `llm_translate` 先查缓存，未命中才进入全局 `RateLimiter.wait`。2 QPS 对应放行间隔约 0.5 秒，锁内等待会让其他线程排队。之后 TransYH 的信号量控制 API 在途数量。传输重试重新申请信号量，但直接调用适配器，不再次经过 BabelDOC 的 QPS 放行步骤。

`TranslationConfig.qps` 在未指定 `pool_max_workers` 时提供线程池默认值。本项目明确传入 `pool_max_workers=concurrency`。翻译使用多个优先级线程池，因此合计并发由 TransYH 的单个信号量控制。

AI 标注使用独立的有界线程池，当前路径没有 BabelDOC QPS 限制。缓存会减少网络请求数，完整高亮图层相同还可直接复用。标注缓存身份包含生成 PDF 的内容标识，重新生成 PDF 后即使正文相同，也可能产生全部批次未命中。

## 完成阶段循环等待的最小修复

首次点击“中文”且启用自动标注时存在下面的等待链。

```text
ReadingSession.switchTo
  -> performSwitch awaits translate
  -> translate awaits highlightAttachment
  -> highlightAttachment awaits readers.pdfUpdated
  -> ReadingSession.pdfUpdated awaits this.switching
```

此时新中文 PDF 已生成并保存，目标阅读器尚未创建。`pdfUpdated` 先检查本 session 是否已经加载目标附件，只有已加载的 pane 才进入等待与重载流程。首次切换将在任务返回后直接加载已保存的中文 PDF。

针对性测试在上述 main 上复现失败，在修复后通过。已有 pane 仍验证串行刷新及阅读位置恢复。进度增加高亮生成、安全提交及阅读器刷新阶段，便于定位 Python 已结束后的等待。

取消仍通过 worker 进程终止执行，已完成缓存可供后续复用。原子提交按原有事务规则完成或恢复。当前已挂起的旧版会话需要应用更新后重新进入阅读流程。

## 超时及后续诊断

Responses 只有收到完整终止结果才返回文本，failed、incomplete 和未收到 completed 的断流会报错。已有实现会在 completed 时结束遍历，性能记录可检查终止事件到调用返回的差值。[OpenAI Responses 流事件](https://developers.openai.com/api/reference/resources/responses/streaming-events)

HTTPX 的 read timeout 限制两次读取数据之间的等待时间。持续收到心跳的未结束流可能超过配置的 120 秒总时长。后续可增加可配置的总时长或无语义进展上限，并将超时作为整次请求失败处理，保留完整输出要求。本轮保留现有超时语义，新增首事件和终止事件记录用于取证。[HTTPX 超时定义](https://www.python-httpx.org/advanced/timeouts/)

BabelDOC 的 finish 事件在部分清理流程之前发出，本项目已有收到 finish 后退出进度迭代的处理。默认 executor 的收尾仍应结合进程、CPU、API 活动和阶段记录判断。原生 PDF reload 的 destroy 等待尚缺总时长上限，需要在实际出现该阶段阻塞时单独取证。

## 相关验证

```text
.venv/bin/python -m pytest tests/test_performance.py tests/test_responses.py tests/test_worker.py tests/test_highlights.py -q
node --import tsx --test tests/reader-completion.test.ts
npm run typecheck
```

这些协议及调度测试使用本地夹具，只验证计数、隐私、终止处理、回退与事务安全。真实 API 时延来自单独授权的真实运行。个人论文、基准输出和运行记录保留在被 Git 忽略的本地目录。
