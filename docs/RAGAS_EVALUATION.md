# �?Jupyter �?RAGAS 实验

主实验入口是 `eval/ragas_experiment.ipynb`。Notebook 复用 `scripts/ragas_evaluate.py` 的采集与评分函数，因此命令行和交互实验使用同一套逻辑�?
## 1. 安装评估环境

```powershell
uv sync --frozen --group evaluation
uv run --frozen --group evaluation jupyter lab
```

从项目根目录启动 JupyterLab，然后打开 `eval/ragas_experiment.ipynb`�?
项目�?RAGAS 约束�?`0.4.x`，并�?`langchain-community` 约束�?`<0.4`。原因是 RAGAS 0.4.3 仍会导入一个在 LangChain Community 0.4 中移除的兼容模块；不加此约束时，依赖解析可能成功，但导入 RAGAS 会失败�?
## 2. 准备数据�?
复制 `eval/ragas_dataset.example.jsonl`，每行一个样本：

```json
{"id":"q1","question":"用户问题","reference":"人工标准答案","kb_id":1,"top_k":5}
```

`question` �?`reference` 必填，也兼容旧字�?`ground_truth`。正式实验建议至少准�?50�?00 条，并覆盖事实问答、跨段推理、无答案拒答、编�?专有名词和不同文档格式�?
## 3. 配置环境变量

RAG 生成模型�?RAGAS 裁判模型应独立配置：

```dotenv
RAG_EVAL_BASE_URL=http://localhost:8000
RAG_EVAL_TOKEN=你的JWT

RAGAS_LLM_API_KEY=你的DeepSeek或OpenAI兼容Key
RAGAS_LLM_BASE_URL=https://api.deepseek.com
RAGAS_LLM_MODEL=deepseek-chat

# response_relevancy 需�?Embedding 裁判服务
RAGAS_EMBEDDING_API_KEY=你的Embedding服务Key
RAGAS_EMBEDDING_BASE_URL=https://api.openai.com/v1
RAGAS_EMBEDDING_MODEL=text-embedding-3-small
```

没有现成 JWT 时，可改为配�?`RAG_EVAL_USERNAME` �?`RAG_EVAL_PASSWORD`，Notebook 会调�?`/login` 获取令牌�?
## 4. 两阶段实验方�?
1. 运行 Notebook �?3A，调�?`/embedding/rag/answer`，将回答、引用上下文、延迟和降级标记写入 `eval/results/responses_*.jsonl`�?2. 后续调整 RAGAS 指标或裁判模型时，运�?3B 读取历史响应，然后从�?4 节重新评分，不必再次请求业务 RAG�?
默认指标�?`faithfulness`、`response_relevancy`、`context_precision` �?`context_recall`。如果暂时没�?Embedding 裁判服务，可�?`METRICS` 中去�?`response_relevancy`�?
输出包括原始响应 JSONL、逐题 CSV、指标均值、延迟平均�?P95、降级率和空上下文率。当�?API 使用 citation �?`quote` 作为 `retrieved_contexts`，因此评价的是最终暴露给用户并写入引用的证据片段�?
## 5. 命令行备用方�?
Notebook 之外仍可直接运行�?
```powershell
uv run --frozen --group evaluation python scripts/ragas_evaluate.py `
  --dataset eval/my_ragas_dataset.jsonl `
  --token "你的JWT"
```

仅采集或复用响应�?
```powershell
uv run --frozen --group evaluation python scripts/ragas_evaluate.py --dataset eval/my_ragas_dataset.jsonl --token "JWT" --collect-only
uv run --frozen --group evaluation python scripts/ragas_evaluate.py --responses-file eval/results/responses_时间.jsonl
```
