# -*- coding: utf-8 -*-
"""RAG 内核：解析 → 切分 → Embedding(NPU) → ChromaDB → Rerank(NPU) → LLM 生成(iGPU)。

设计要点：
- Embedding: BGE-M3, optimum-intel OVModelForFeatureExtraction, NPU 优先（静态 shape）
- Rerank:    BGE-reranker-v2-m3, OVModelForSequenceClassification, NPU 优先
- LLM:       Qwen2.5-7B-Instruct INT4, openvino_genai.LLMPipeline, iGPU 优先
- 向量库:    ChromaDB PersistentClient（本地磁盘，隐私不出机）
- 解析器插槽: PARSERS 注册表，后续可插拔 OCR/ASR 解析器（扩展位）
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime
from pathlib import Path

import common
from common import DATA_DIR, MODELS_DIR

# 必须在 import common（内含 sanitize_pythonpath）之后再引入重依赖，
# 防止外部 PYTHONPATH 污染目录里的异构 numpy 被优先加载
import numpy as np

log = common.setup_logging("rag_pipeline")

CITATION_PROMPT = (
    "你是一个严谨的本地知识库助手。仅根据下方提供的【上下文片段】回答问题，"
    "禁止编造上下文之外的内容；如果上下文不足以回答，明确说明「知识库中未找到相关内容」。"
    "回答时用 [1][2] 等编号标注引用的片段。\n\n"
    "【上下文片段】\n{context}\n\n【问题】\n{query}\n\n【回答】\n"
)


# ---------------------------------------------------------------------------
# 文档解析器（可插拔插槽：后续 OCR/ASR 解析器在此注册）
# ---------------------------------------------------------------------------
def parse_pdf(path: Path) -> list[dict]:
    """PyMuPDF 逐页抽取文本，保留页码元数据。"""
    import fitz  # PyMuPDF
    pages = []
    with fitz.open(str(path)) as doc:
        for i, page in enumerate(doc):
            text = page.get_text("text").strip()
            if text:
                pages.append({"text": text, "page": i + 1})
    return pages


def parse_markdown(path: Path) -> list[dict]:
    """Markdown/纯文本整读，page 恒为 1。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    return [{"text": text, "page": 1}] if text.strip() else []


PARSERS = {
    ".pdf": parse_pdf,
    ".md": parse_markdown,
    ".markdown": parse_markdown,
    ".txt": parse_markdown,
}


def split_text(text: str, chunk_size: int, overlap: int) -> list[tuple[str, int]]:
    """递归+重叠切分：先按段落/句子边界聚合，超限硬切；返回 (chunk, offset)。"""
    # 归一化换行，按段落切
    paras = re.split(r"\n\s*\n", text)
    pieces: list[tuple[str, int]] = []
    offset = 0
    for para in paras:
        para = para.strip()
        idx = text.find(para, offset)
        if idx < 0:
            idx = offset
        if para:
            pieces.append((para, idx))
        offset = idx + len(para)

    chunks: list[tuple[str, int]] = []
    buf, buf_off = "", 0
    for para, off in pieces:
        if not buf:
            buf, buf_off = para, off
        elif len(buf) + len(para) + 1 <= chunk_size:
            buf = buf + "\n" + para
        else:
            chunks.append((buf, buf_off))
            buf, buf_off = para, off
    if buf:
        chunks.append((buf, buf_off))

    # 超长块二次硬切（带 overlap）
    final: list[tuple[str, int]] = []
    for chunk, off in chunks:
        if len(chunk) <= chunk_size:
            final.append((chunk, off))
        else:
            step = max(chunk_size - overlap, 1)
            for start in range(0, len(chunk), step):
                sub = chunk[start:start + chunk_size]
                if sub.strip():
                    final.append((sub, off + start))
                if start + chunk_size >= len(chunk):
                    break
    return final


# ---------------------------------------------------------------------------
# OpenVINO 模型封装
# ---------------------------------------------------------------------------
class OVEmbedder:
    """BGE-M3 Embedding，NPU 优先。NPU 需静态 shape → reshape 到 [1, max_length]。"""

    def __init__(self, model_dir: Path, device: str, max_length: int = 512):
        from transformers import AutoTokenizer
        from optimum.intel import OVModelForFeatureExtraction

        self.device = device
        self.max_length = max_length
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
        t0 = time.time()
        self.model = OVModelForFeatureExtraction.from_pretrained(
            str(model_dir), device=device, compile=False)
        if device.startswith("NPU"):
            # NPU 仅支持静态 shape：固定 batch=1, seq=max_length
            self.model.reshape(1, max_length)
        self.model.compile()
        log.info("embedder loaded on %s in %.1fs", device, time.time() - t0)

    def encode(self, texts: list[str]) -> np.ndarray:
        """CLS 池化 + L2 归一化（BGE 系列约定）。"""
        vecs = []
        for text in texts:
            inputs = self.tokenizer(
                text, max_length=self.max_length, padding="max_length",
                truncation=True, return_tensors="np")
            out = self.model(**inputs)
            cls = out.last_hidden_state[:, 0]
            cls = cls / (np.linalg.norm(cls, axis=-1, keepdims=True) + 1e-12)
            vecs.append(cls[0])
        return np.asarray(vecs, dtype=np.float32)


class OVReranker:
    """BGE-reranker-v2-m3 精排，NPU 优先。输出 (query, passage) 相关性分。"""

    def __init__(self, model_dir: Path, device: str, max_length: int = 512):
        from transformers import AutoTokenizer
        from optimum.intel import OVModelForSequenceClassification

        self.max_length = max_length
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
        t0 = time.time()
        self.model = OVModelForSequenceClassification.from_pretrained(
            str(model_dir), device=device, compile=False)
        if device.startswith("NPU"):
            self.model.reshape(1, max_length)
        self.model.compile()
        log.info("reranker loaded on %s in %.1fs", device, time.time() - t0)

    def score(self, query: str, passages: list[str]) -> list[float]:
        scores = []
        for passage in passages:
            inputs = self.tokenizer(
                query, passage, max_length=self.max_length, padding="max_length",
                truncation=True, return_tensors="np")
            logits = self.model(**inputs).logits
            scores.append(float(logits.reshape(-1)[0]))
        return scores


class OVGenerator:
    """Qwen2.5 LLM 生成，openvino_genai.LLMPipeline，iGPU 优先。"""

    def __init__(self, model_dir: Path, device: str):
        import openvino_genai
        t0 = time.time()
        self.pipe = openvino_genai.LLMPipeline(str(model_dir), device)
        self.config = openvino_genai.GenerationConfig()
        log.info("llm loaded on %s in %.1fs", device, time.time() - t0)

    def generate(self, prompt: str, max_tokens: int = 512) -> str:
        self.config.max_new_tokens = max_tokens
        self.config.do_sample = False  # 问答确定性输出，抑制幻觉
        return str(self.pipe.generate(prompt, self.config))


# ---------------------------------------------------------------------------
# RAG 流水线
# ---------------------------------------------------------------------------
class RagPipeline:
    """常驻内核：模型加载一次，ingest/search/ask/list/remove 多次调用。"""

    def __init__(self):
        info = common.load_info()
        self.rag_conf = info["rag"]
        available = common.detect_devices()
        log.info("available OpenVINO devices: %s", available)
        self.devices: dict[str, str] = {}

        by_role = {m["role"]: m for m in info["models"]}

        emb_conf = by_role["embedding"]
        emb_dev = common.pick_device(emb_conf["device_preference"], available)
        self.embedder = self._load_with_fallback(
            OVEmbedder, MODELS_DIR / emb_conf["name"], emb_dev,
            max_length=emb_conf.get("max_length", 512))
        self.devices["embedding"] = self.embedder.device if hasattr(self.embedder, "device") else emb_dev

        rr_conf = by_role["reranker"]
        rr_dev = common.pick_device(rr_conf["device_preference"], available)
        self.reranker = self._load_with_fallback(
            OVReranker, MODELS_DIR / rr_conf["name"], rr_dev,
            max_length=rr_conf.get("max_length", 512))
        self.devices["reranker"] = rr_dev

        llm_conf = by_role["llm"]
        llm_dev = common.pick_device(llm_conf["device_preference"], available)
        self.generator = self._load_with_fallback(
            OVGenerator, MODELS_DIR / llm_conf["name"], llm_dev)
        self.devices["llm"] = llm_dev

        # ChromaDB 持久化向量库
        import chromadb
        self.chroma = chromadb.PersistentClient(path=str(DATA_DIR / "chroma"))
        self.collection = self.chroma.get_or_create_collection(
            name="local_kb", metadata={"hnsw:space": "cosine"})
        log.info("pipeline ready: devices=%s docs=%d", self.devices, len(self.doc_ids()))

    @staticmethod
    def _load_with_fallback(cls, model_dir: Path, device: str, **kwargs):
        """加速 device 加载失败自动回退 CPU（降级策略）。"""
        try:
            return cls(model_dir, device, **kwargs)
        except Exception as exc:  # noqa: BLE001
            if device != "CPU":
                log.warning("%s load failed on %s (%s), fallback to CPU", cls.__name__, device, exc)
                return cls(model_dir, "CPU", **kwargs)
            raise

    # -- 元数据 ------------------------------------------------------------
    def doc_ids(self) -> set[str]:
        metas = self.collection.get(include=["metadatas"]).get("metadatas") or []
        return {m["doc_id"] for m in metas if m}

    def stats(self) -> dict:
        return {"docs": len(self.doc_ids()), "chunks": self.collection.count(),
                "devices": self.devices}

    # -- ingest ------------------------------------------------------------
    def ingest(self, source: str = "", content: str = "", doc_id: str = "",
               chunk_size: int = 0, overlap: int = 0) -> dict:
        t0 = time.time()
        chunk_size = int(chunk_size) or self.rag_conf["chunk_size"]
        overlap = int(overlap) or self.rag_conf["chunk_overlap"]

        if source:
            path = Path(source).expanduser()
            if not path.is_file():
                raise ValueError(f"file not found: {source}")
            parser = PARSERS.get(path.suffix.lower())
            if parser is None:
                raise ValueError(f"unsupported file type: {path.suffix} "
                                 f"(supported: {', '.join(PARSERS)})")
            pages = parser(path)
            doc_name = path.name
            doc_id = doc_id or hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:12]
        elif content:
            pages = [{"text": content, "page": 1}]
            doc_name = doc_id or "inline"
            doc_id = doc_id or hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]
        else:
            raise ValueError("either 'source' or 'content' is required")

        if not pages:
            raise ValueError("document parsed to empty text")

        # 重复摄入 → 先删旧再写新（幂等更新）
        self.remove_source(doc_id, quiet=True)

        ids, texts, metas = [], [], []
        seq = 0
        for page in pages:
            for chunk, offset in split_text(page["text"], chunk_size, overlap):
                ids.append(f"{doc_id}:{seq}")
                texts.append(chunk)
                metas.append({
                    "doc_id": doc_id, "doc": doc_name, "chunk_id": seq,
                    "page": page["page"], "offset": offset,
                    "ingested_at": datetime.now().isoformat(timespec="seconds"),
                })
                seq += 1

        # 分批向量化写库（Embedding 在 NPU）
        batch = 16
        for i in range(0, len(ids), batch):
            embs = self.embedder.encode(texts[i:i + batch])
            self.collection.add(
                ids=ids[i:i + batch], embeddings=embs.tolist(),
                documents=texts[i:i + batch], metadatas=metas[i:i + batch])

        return {"doc_id": doc_id, "doc": doc_name, "chunks": seq,
                "elapsed_s": round(time.time() - t0, 2)}

    # -- search ------------------------------------------------------------
    def search(self, query: str, top_k: int = 0, rerank: bool = True,
               filter: dict | None = None) -> dict:
        t0 = time.time()
        if not query:
            raise ValueError("'query' is required")
        top_k = int(top_k) or self.rag_conf["top_k"]
        if self.collection.count() == 0:
            return {"hits": [], "elapsed_s": round(time.time() - t0, 2)}

        where = None
        if filter and filter.get("doc_id"):
            where = {"doc_id": filter["doc_id"]}

        # 粗召回：rerank 时取 top_k * factor 候选
        n = top_k * self.rag_conf["rerank_candidates_factor"] if rerank else top_k
        n = min(n, self.collection.count())
        qvec = self.embedder.encode([query])
        res = self.collection.query(
            query_embeddings=qvec.tolist(), n_results=n, where=where,
            include=["documents", "metadatas", "distances"])

        docs = res["documents"][0]
        metas = res["metadatas"][0]
        dists = res["distances"][0]
        hits = []
        for text, meta, dist in zip(docs, metas, dists):
            hits.append({
                "doc_id": meta["doc_id"], "doc": meta["doc"],
                "chunk_id": meta["chunk_id"], "text": text,
                "score": round(1.0 - dist, 4),  # cosine distance -> similarity
                "location": {"page": meta["page"], "offset": meta["offset"]},
            })

        # 精排（Rerank 在 NPU）
        if rerank and len(hits) > 1:
            scores = self.reranker.score(query, [h["text"] for h in hits])
            for h, s in zip(hits, scores):
                h["score"] = round(s, 4)
            hits.sort(key=lambda h: h["score"], reverse=True)
        hits = hits[:top_k]

        return {"hits": hits, "elapsed_s": round(time.time() - t0, 2)}

    # -- ask ---------------------------------------------------------------
    def ask(self, query: str, top_k: int = 0, max_tokens: int = 0) -> dict:
        t0 = time.time()
        max_tokens = int(max_tokens) or self.rag_conf["max_tokens"]
        found = self.search(query, top_k=top_k, rerank=True)
        hits = found["hits"]
        if not hits:
            return {"answer": "知识库中未找到相关内容（知识库为空或无匹配片段）。",
                    "citations": [], "elapsed_s": round(time.time() - t0, 2)}

        context = "\n\n".join(
            f"[{i + 1}] （来源：{h['doc']} 第{h['location']['page']}页）\n{h['text']}"
            for i, h in enumerate(hits))
        prompt = CITATION_PROMPT.format(context=context, query=query)
        answer = self.generator.generate(prompt, max_tokens=max_tokens).strip()

        # 引用强制回填真实 chunk 文本（防幻觉）
        citations = [{
            "index": i + 1, "doc_id": h["doc_id"], "doc": h["doc"],
            "chunk_id": h["chunk_id"], "page": h["location"]["page"],
            "text": h["text"][:300],
        } for i, h in enumerate(hits)]

        return {"answer": answer, "citations": citations,
                "elapsed_s": round(time.time() - t0, 2)}

    # -- sources -----------------------------------------------------------
    def list_sources(self) -> dict:
        metas = self.collection.get(include=["metadatas"]).get("metadatas") or []
        agg: dict[str, dict] = {}
        for m in metas:
            entry = agg.setdefault(m["doc_id"], {
                "doc_id": m["doc_id"], "doc": m["doc"],
                "chunks": 0, "ingested_at": m["ingested_at"]})
            entry["chunks"] += 1
        return {"sources": sorted(agg.values(), key=lambda x: x["ingested_at"])}

    def remove_source(self, doc_id: str, quiet: bool = False) -> dict:
        if not doc_id:
            raise ValueError("'doc_id' is required")
        existing = self.collection.get(where={"doc_id": doc_id})
        n = len(existing.get("ids") or [])
        if n == 0 and not quiet:
            raise ValueError(f"doc_id not found: {doc_id}")
        if n:
            self.collection.delete(where={"doc_id": doc_id})
        return {"removed_chunks": n}
