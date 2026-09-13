# -*- coding: utf-8 -*-
"""切分逻辑冒烟测试（stub 掉 numpy，不依赖重型环境）。"""
import sys
import types
from pathlib import Path

sys.modules.setdefault("numpy", types.ModuleType("numpy"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from rag_pipeline import PARSERS, split_text  # noqa: E402

# 常规段落聚合
text = ("OpenVINO 第一段。\n\n" * 3) + "X" * 1200
chunks = split_text(text, 512, 64)
assert len(chunks) >= 3, f"expect >=3 chunks, got {len(chunks)}"
assert all(len(c) <= 512 for c, _ in chunks), "chunk exceeds chunk_size"

# 超长块 overlap 校验：相邻硬切块应有重叠
long_chunks = [(c, o) for c, o in chunks if "X" in c]
assert len(long_chunks) >= 2, "long text should be hard-split"
step_offsets = [o for _, o in long_chunks]
assert step_offsets[1] - step_offsets[0] == 512 - 64, "overlap step mismatch"

# offset 定位正确：offset 指向块首段在原文中的起点（段间空行已归一化，按首段前缀比对）
for c, o in chunks:
    first_line = c.split("\n", 1)[0][:20]
    assert text[o:o + len(first_line)] == first_line, f"offset mismatch at {o}"

# 空文本
assert split_text("", 512, 64) == []

# 解析器注册表
assert set(PARSERS) == {".pdf", ".md", ".markdown", ".txt"}

print("SMOKE-OK: chunks=%d parsers=%s" % (len(chunks), sorted(PARSERS)))
