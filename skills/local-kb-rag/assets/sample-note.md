# OpenVINO 本地部署速查笔记（示例语料）

> 本文件是 local-kb-rag 的示例语料，用于端到端测试 ingest → search → ask 链路。

## 什么是 OpenVINO

OpenVINO™ 是 Intel 开源的深度学习推理优化工具套件，可将模型部署到
CPU、集成显卡（iGPU）与神经处理单元（NPU）等异构算力上。
配套的 Optimum-intel 提供 `optimum-cli export openvino` 命令，
可把 Hugging Face / ModelScope 上的 Transformers 模型一键导出为 OpenVINO IR 格式。

## 如何把模型部署到 NPU

1. 用 Optimum-intel 将模型导出为 IR（`openvino_model.xml` + `openvino_model.bin`）。
2. NPU 只支持静态 shape：加载后需 `model.reshape(1, max_length)` 固定输入尺寸。
3. 编译时指定 `device="NPU"`；若某算子不被 NPU 支持，OpenVINO 会自动回退 CPU。
4. BGE 系列 Embedding 小模型非常适合 NPU：高吞吐、低功耗，且不占用 GPU 显存。

## RAG 异构分工建议

- **NPU**：Embedding（BGE-M3）与 Rerank（BGE-reranker-v2-m3），小模型高频调用。
- **iGPU**：LLM 生成（如 Qwen2.5-7B-Instruct INT4，约 5GB），吞吐优于 CPU。
- **CPU**：文档解析（PyMuPDF）与全链路兜底。

## 隐私设计

本地 RAG 的核心价值是「数据不出机」：语料、向量库、模型权重全部驻留本地磁盘，
推理全程 Localhost 完成，仅最终答案文本回传给 Agent 宿主。
首次模型下载完成后，整个系统可完全离线运行。
