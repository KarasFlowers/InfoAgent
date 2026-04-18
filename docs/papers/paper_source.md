# 第三十六届“冯如杯”竞赛主赛道参赛论文
# 面向开发者的智能科技资讯聚合与个性化检索增强系统设计与实现
[NOINDENT]（匿名稿）
[NOINDENT]2026年4月

[PAGEBREAK]
# 题名页
[NOINDENT]论文题目：面向开发者的智能科技资讯聚合与个性化检索增强系统设计与实现
[NOINDENT]参赛赛道：第三十六届“冯如杯”竞赛主赛道
[NOINDENT]作品类型：软件系统设计与实现
[NOINDENT]匿名说明：本文不包含作者姓名、学院、专业及指导教师信息。
[NOINDENT]提交日期：2026年4月

[PAGEBREAK]
# 中文摘要
[NOINDENT]在技术资讯获取场景中，开发者面临“信息源分散、摘要质量不稳定、深度问答缺乏上下文、检索结果个性化不足”等问题。针对上述痛点，本文设计并实现了一个面向开发者的智能资讯聚合与检索增强系统 InfoAgent。系统以 FastAPI 为核心框架，构建“多源 RSS 聚合 + 大模型摘要 + RAG 深度问答 + 用户画像重排序”的一体化流程。方法层面，本文提出了三项关键机制：第一，构建“双引擎正文抽取 + 质量自评估”链路，采用 Trafilatura 与 BeautifulSoup 级联策略，并通过文本密度、噪声比例与长度充分性进行质量打分，以降低脏数据进入摘要链路的概率；第二，提出“向量召回 + BM25 召回 + RRF 融合 + Cross-Encoder 精排”的 Hybrid Search 管线，在保证语义相关性的同时增强关键词命中能力；第三，引入显式反馈驱动的用户语义画像，通过点赞/点踩样本构建正负兴趣质心，在重排序阶段进行兴趣加权和噪声惩罚。工程实现中，系统采用 SQLite 与 ChromaDB 的混合存储架构，结合 Redis 缓存和流式输出机制，兼顾响应性能与可维护性。基于项目运行数据（2026-03-17 至 2026-04-08）进行分析，系统累计生成 12 期日报、存储 118 条精选资讯；在具备统计信息的运行日中，原始抓取 50 条新闻可稳定筛选至约 21 条高质量候选并最终推荐约 9 条核心内容。结果表明，该系统能够在可解释、可扩展的工程框架下提升技术资讯消费效率，并为后续“异步预索引、热点聚类、强化个性化”提供可落地基础。
[NOINDENT]关键词：智能资讯聚合，检索增强生成，混合检索，个性化重排序，开发者工具

[PAGEBREAK]
# Abstract
[NOINDENT]Developers are increasingly overwhelmed by fragmented information sources, unstable summary quality, and weak context support in article-level Q and A. To address these issues, this paper presents InfoAgent, an integrated system for AI-powered tech news aggregation and retrieval-augmented exploration. The system is built on FastAPI and combines multi-source RSS ingestion, LLM-based daily summarization, RAG-based deep-dive interaction, and feedback-driven personalization. Three core techniques are implemented. First, a dual-extractor pipeline is introduced for robust content acquisition, where Trafilatura is used as the primary extractor and BeautifulSoup as fallback, followed by a quality assessment module based on text density, noise ratio, and content length. Second, a hybrid retrieval pipeline is designed with semantic recall, BM25 keyword recall, Reciprocal Rank Fusion, and Cross-Encoder reranking, balancing semantic understanding and exact-term matching. Third, an explicit feedback learning mechanism builds positive and negative user-interest centroids, and applies reward-penalty adjustments during reranking to improve personalized relevance. The implementation adopts a mixed storage architecture with SQLite for structured metadata, ChromaDB for vector indexing, and Redis for caching. Streaming responses are used to improve interaction latency. Based on system logs from March 17, 2026 to April 8, 2026, the platform produced 12 daily reports with 118 curated items. On tracked runs, around 50 fetched candidates were filtered into about 21 high-quality items and finally condensed to about 9 recommendations. The results indicate that InfoAgent improves information efficiency for developers while maintaining a practical and extensible engineering design.
[NOINDENT]Keywords: intelligent news aggregation, retrieval-augmented generation, hybrid retrieval, personalized reranking, developer productivity

[PAGEBREAK]
# 目录
[TOC]

[PAGEBREAK]
# 一、绪论
## （一）研究背景
近年来，大模型能力快速迭代，技术社区信息生产速度显著提升。对于开发者而言，单日需处理的技术动态已从“少量高价值新闻”演变为“海量碎片化更新”，信息筛选成本持续升高。传统 RSS 阅读器虽然能够聚合链接，但在内容优先级判断、跨源主题整合、语义检索和个性化推荐方面能力有限，用户仍需投入大量时间完成“阅读前筛选”与“阅读后追问”两个高成本环节。

与此同时，RAG 技术在知识问答、文档助手等场景表现出较高实用价值，但直接应用于新闻类网页仍面临两个挑战：其一，网页结构噪声高，正文抽取质量不稳定；其二，单一召回路径容易在“语义相关”与“术语命中”之间失衡。若无法解决上述问题，系统将出现摘要失真、检索偏移与回答幻觉等工程风险。

## （二）问题定义
本文聚焦“面向开发者的技术资讯消费效率”这一核心问题，定义目标为：在不牺牲信息准确性和可追溯性的前提下，构建一个支持日常资讯摘要、文章级深度问答和个性化排序的轻量化系统。具体包括四个子问题：一是如何在复杂网页环境中稳定提取正文并抑制噪声；二是如何在召回阶段同时兼顾语义理解和关键词匹配；三是如何将用户反馈转化为可计算的个性化信号；四是如何在 Python 服务栈中平衡生成质量、响应时延与系统可维护性。

## （三）研究目标与创新点
围绕上述问题，本文完成如下目标与创新：
第一，提出“抽取-评估-拦截”一体化内容质量控制链路，减少低质量文本进入摘要与向量化流程。
第二，构建 Hybrid Search 双通路召回方案，采用 RRF 融合策略缓解单通路偏置问题，并以 Cross-Encoder 执行精排。
第三，设计显式反馈驱动的用户画像机制，利用正负兴趣质心对候选片段执行奖励与惩罚，实现可解释的个性化重排序。
第四，完成可运行的工程系统，实现聚合、摘要、问答、反馈与存储闭环，并提供日志与数据层面的运行证据。

# 二、需求分析与总体设计
## （一）功能需求
系统面向开发者日常资讯处理任务，核心功能需求如下：其一，支持多源 RSS 并发抓取与统一数据建模；其二，支持对当日资讯执行自动摘要与结构化推荐；其三，支持针对单篇文章进行深度问答与对话历史回溯；其四，支持用户点赞/点踩反馈并在后续排序中体现偏好；其五，支持历史数据保留与周期清理，避免存储持续膨胀。

## （二）非功能需求
系统需要满足四类非功能约束。第一，鲁棒性：当抓取失败、解析失败或模型调用异常时，应返回可解释错误并避免脏数据污染主流程。第二，性能：在单机环境下应具备可接受的交互时延，优先保证“先返回可读内容，再逐步补全细节”的体验。第三，可维护性：模块边界清晰，便于替换模型、扩展数据源和独立调试。第四，安全性：对外部 URL 执行公网可达性校验，降低内网探测与 SSRF 风险。

## （三）总体架构
系统采用前后端分离的服务化架构。后端基于 FastAPI 暴露 REST 与 SSE 接口，主要由五个服务模块组成：RSS 抓取模块、LLM 摘要模块、RAG 检索模块、学习与重排序模块、数据库与缓存模块。数据层采用“SQLite + ChromaDB + Redis”混合方案：SQLite 存储摘要元数据与反馈记录，ChromaDB 存储文章分块向量，Redis 缓存 RSS 抓取结果。前端负责日报展示、文章卡片交互、问答会话与反馈提交。

## （四）业务流程
系统主流程可概括为：多源抓取 -> 原始条目清洗 -> 质量评分与候选过滤 -> 大模型生成日报 -> 用户浏览并触发深度问答 -> 文章抽取与分块向量化 -> Hybrid Search 检索与精排 -> 流式回答返回 -> 用户反馈写入 -> 画像更新并影响后续排序。该流程形成“消费-反馈-学习-再消费”的闭环，使系统具备持续自适应能力。

# 三、关键方法设计
## （一）网页正文抽取与质量评估
在网页正文提取环节，系统优先使用 Trafilatura 执行结构化抽取；若提取失败或有效长度不足，则退化到 BeautifulSoup 清洗策略，通过移除 script、style、nav、header、footer 等噪声标签后抽取段落文本。为避免“看似成功、实际失真”的情况，系统引入质量评估函数，对抽取文本计算三项指标：有效段落密度 D、噪声比例 N、长度充分性 L。综合得分定义为：

Q = 0.45 * D + 0.25 * (1 - N) + 0.30 * L

其中 Q∈[0,1]。当评分较低时，系统在接口层返回“内容解析不全”提示，避免低质量内容参与后续摘要与问答，提升整体可信度。

## （二）Hybrid Search：双通路召回与融合
仅使用向量召回可能遗漏术语精确匹配，仅使用关键词召回又难以理解语义等价表达。针对该矛盾，系统采用双通路召回：通路 A 使用 Bi-Encoder 进行语义向量召回，通路 B 使用 BM25 执行关键词召回。两路候选通过 RRF（Reciprocal Rank Fusion）进行融合，融合得分定义为：

RRF(d) = Σ 1 / (k + rank_i(d))

其中 k 为平滑常数，rank_i(d) 为文档 d 在第 i 条召回通路中的排名。该策略可在无需复杂参数训练的情况下稳定提升候选覆盖率。

## （三）Cross-Encoder 精排与个性化重排序
融合候选进入精排阶段后，系统使用 Cross-Encoder 对“问题-片段”对进行逐对打分，以获得更细粒度相关性。随后引入用户反馈形成的正负兴趣质心 c+ 与 c-，对片段向量 e 施加奖励与惩罚，最终得分定义为：

S_final = S_ce + 3 * max(0, cos(e, c+)) - 2 * max(0, cos(e, c-))

其中 S_ce 为 Cross-Encoder 分值。该机制能够在保证语义相关性的前提下，主动降低用户不偏好主题的排序位置，提高“越用越懂你”的体验。

## （四）流式响应与缓存机制
系统在摘要展示和问答返回中均采用 SSE 流式输出，显著缩短“首字节可见时间”。缓存策略分为两层：Redis 缓存 RSS 抓取结果，减少短时间重复抓取；本地内存缓存正文与概览结果，减少二次打开同一文章的重复计算开销。对于向量索引，系统使用 ChromaDB 持久化存储，并在历史清理任务中执行按 URL 删除，控制索引规模增长。

# 四、系统实现
## （一）后端接口实现
系统后端提供两组核心接口。第一组为摘要接口，包括 /api/v1/summary、/api/v1/history、/api/v1/persona 等，用于日报生成、历史查询与偏好管理。第二组为 RAG 接口，包括 /api/v1/rag/ingest、/api/v1/rag/query、/api/v1/rag/overview、/api/v1/rag/feedback 等，用于文章入库、检索问答与反馈学习。对于需要实时输出的接口，统一采用 StreamingResponse 返回 text/event-stream。

## （二）数据模型与持久化设计
结构化数据采用 SQLModel 映射至 SQLite，关键实体包括 DailySummary、NewsItem、UserFeedback、ChatMessage、UserPersona。DailySummary 与 NewsItem 为一对多关系，支持日报与条目级追踪；UserFeedback 以 article_url 为键记录显式偏好；ChatMessage 用于保存问答历史。非结构化向量数据由 ChromaDB 持久化管理，集合命名与 URL 绑定，便于按文章生命周期回收。

## （三）安全与异常处理机制
系统在 URL 进入抓取链路前执行公网安全校验，拒绝私网地址与受限目标。对于抓取失败、内容过短、参数非法等情形，接口返回 4xx 或 5xx 并携带可读错误信息。为避免并发下重复生成同日摘要，摘要接口引入异步锁保护；在写库阶段通过唯一约束与异常回滚处理并发写冲突，保证数据一致性。

## （四）前端交互与可解释性
前端仪表盘展示每日概览、推荐条目与来源分布，并提供文章级问答入口。RAG 回答过程中，系统可返回重排序元信息（语义分、画像加分、惩罚分、总分及候选来源），帮助用户理解答案依据，增强系统可解释性与信任度。

# 五、实验设计与结果分析
## （一）实验环境与数据范围
实验基于本项目实际运行数据完成。统计窗口为 2026-03-17 至 2026-04-08，共生成 12 期日报并落库 118 条推荐资讯。系统默认配置 10 个技术资讯 RSS 源，模型调用采用 deepseek-chat，向量模型采用 paraphrase-multilingual-MiniLM-L12-v2，精排模型采用 cross-encoder/ms-marco-MiniLM-L-6-v2。存储层为 SQLite + ChromaDB，缓存层为 Redis。

## （二）摘要候选过滤效果
在具备 recommendation_report 的运行日中，系统平均每轮抓取 50 条候选资讯，质量打分后平均保留 21 条高质量候选，排除约 29 条低价值或噪声内容，最终输出约 9 条日报推荐。该结果说明“先打分再摘要”的过滤策略有效降低了噪声输入比例，使摘要阶段更聚焦高信息密度内容。

## （三）个性化排序效果分析
系统已实现点赞/点踩驱动的正负兴趣质心学习。在线查询时，若候选片段与正兴趣质心余弦相似度较高，则排序得分提升；若与负兴趣质心相似度较高，则施加惩罚。实测中，该机制可在同等语义相关度下优先展示用户偏好主题内容。尽管当前反馈样本仍较少，但机制已打通“反馈-画像-排序”的完整链路，为后续扩大样本后的量化评估奠定基础。

## （四）接口可用性与鲁棒性测试
项目集成测试覆盖健康检查、摘要接口、RAG 入库、问答前置约束、会话历史与反馈接口等关键路径。最近一次测试结果显示 7 项用例中 6 项通过，1 项失败源于测试断言仍假定“非法 sentiment 返回 500”，而当前接口已由 Pydantic 校验提前返回 422。该结果表明主流程稳定可用，同时暴露出“测试预期与接口语义演进不同步”的工程问题，后续应通过修订断言提升测试一致性。

## （五）典型案例分析
以单篇技术文章深度问答为例，系统先进行正文抽取与分块，再经双通路召回与 Cross-Encoder 精排选取 Top-3 片段送入生成模型。相较于仅使用向量召回，Hybrid Search 在涉及版本号、库名、接口名等术语问题时表现更稳定，能够减少“语义相关但关键词错位”的回答偏差。结合流式返回，用户通常可在较短等待时间内获取可用答案并继续追问。

# 六、结论与展望
本文面向开发者资讯场景，完成了一个可运行、可扩展、可解释的智能资讯聚合与检索增强系统。通过内容质量控制、Hybrid Search、Cross-Encoder 精排与用户画像重排序的组合设计，系统在工程层面实现了“从聚合到深问、从反馈到学习”的闭环能力。运行数据表明，系统能够有效压缩信息噪声并稳定产出高价值日报内容。

当前工作仍存在三方面不足：其一，个性化评估样本规模较小，尚需长期反馈数据支撑统计显著性；其二，异步预索引能力仍有提升空间，热点文章的预计算深度不足；其三，标签体系仍以生成式为主，缺少聚类驱动的主题演化分析。下一步将重点推进：基于 Redis 队列的增量预索引、基于向量聚类的热点簇发现与命名、以及更细粒度的多因子排序学习框架。

# 参考文献
[NOINDENT][1] Cormack G V, Clarke C L A, Buettcher S. Reciprocal rank fusion outperforms condorcet and individual rank learning methods[C]. Proceedings of SIGIR 2009, 2009.
[NOINDENT][2] Robertson S, Zaragoza H. The probabilistic relevance framework: BM25 and beyond[J]. Foundations and Trends in Information Retrieval, 2009, 3(4): 333-389.
[NOINDENT][3] Reimers N, Gurevych I. Sentence-BERT: Sentence embeddings using siamese BERT-networks[C]. EMNLP-IJCNLP, 2019.
[NOINDENT][4] Nogueira R, Cho K. Passage re-ranking with BERT[EB/OL]. arXiv:1901.04085, 2019.
[NOINDENT][5] Lewis P, Perez E, Piktus A, et al. Retrieval-augmented generation for knowledge-intensive NLP tasks[C]. NeurIPS, 2020.
[NOINDENT][6] Karpukhin V, Oguz B, Min S, et al. Dense passage retrieval for open-domain question answering[C]. EMNLP, 2020.
[NOINDENT][7] Manning C D, Raghavan P, Schutze H. Introduction to information retrieval[M]. Cambridge: Cambridge University Press, 2008.
[NOINDENT][8] FastAPI Documentation[EB/OL]. https://fastapi.tiangolo.com/, 2026-04-08.
[NOINDENT][9] Chroma Documentation[EB/OL]. https://docs.trychroma.com/, 2026-04-08.
[NOINDENT][10] Trafilatura Documentation[EB/OL]. https://trafilatura.readthedocs.io/, 2026-04-08.
[NOINDENT][11] DeepSeek API Documentation[EB/OL]. https://api-docs.deepseek.com/, 2026-04-08.
[NOINDENT][12] 北京航空航天大学第三十六届“冯如杯”竞赛主赛道论文撰写格式规范[R]. 2026.

# 附录
## 附录A 关键接口清单
[NOINDENT]1. 摘要服务：GET /api/v1/summary，GET /api/v1/history
[NOINDENT]2. 个性化服务：POST /api/v1/persona，POST /api/v1/rag/feedback
[NOINDENT]3. RAG 服务：POST /api/v1/rag/ingest，POST /api/v1/rag/query，POST /api/v1/rag/overview

## 附录B 核心配置项示例
[NOINDENT]1. RSS_FEEDS：支持 Hacker News、Ars Technica、OpenAI News、Hugging Face 等 10 个订阅源。
[NOINDENT]2. HISTORY_DAYS_TO_KEEP：历史数据保留天数，默认 7 天。
[NOINDENT]3. CHROMA_DB_DIR：向量库持久化目录，支持按 URL 删除旧集合。
