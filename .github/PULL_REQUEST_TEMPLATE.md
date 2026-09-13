## 变更说明

<!-- 这个 PR 做了什么，为什么需要它 -->

## 变更类型

- [ ] Bug 修复（不破坏现有行为）
- [ ] 新功能（不破坏现有行为）
- [ ] 破坏性变更（会影响既有 CLI / MCP 工具行为，请在下方说明影响与迁移方式）
- [ ] 文档 / 仓库结构
- [ ] 重构 / 性能优化
- [ ] CI / 构建

## 关联 Issue

<!-- 例如：Closes #12 -->

## 影响面自查

- [ ] **Skill 包自包含**：`skills/local-kb-rag/` 内的相对路径只依赖该目录内部文件，未引用仓库根文件
- [ ] **未在 `skills/local-kb-rag/` 内新增 `README.md`**
- [ ] **固定入口未被改名**：`scripts/run.ps1`、`scripts/mcp_adapter.py` 的路径保持稳定
- [ ] **文档与代码同步**：README 路径、SKILL.md 工具表、退出码表已同步更新
- [ ] **涉及高影响改动已在下方显著标出**（named pipe 协议 / authkey、MCP 工具名称与参数、默认模型与设备偏好、chunk 参数、退出码语义）

## 验证记录

<!-- 实际运行过的命令与结果，不要只写「已测试」 -->

```text
# 必跑
python skills/local-kb-rag/tests/test_split_smoke.py
python .github/scripts/check_metadata.py

# 可选（需 skill-creator）
python <skill-creator>/scripts/quick_validate.py skills/local-kb-rag

# 可选（需 Windows AIPC + 已下载模型，耗时长）
powershell -ExecutionPolicy Bypass -File skills/local-kb-rag/tests/test-e2e.ps1
```

结果：

```text
<!-- 粘贴关键输出，例如 SMOKE-OK: chunks=... / METADATA-OK / PASS: n FAIL: 0 -->
```

## 资源影响

<!-- 若改动 info.json / requirements.txt，说明磁盘、内存、模型下载量的变化 -->

## 补充说明

<!-- 任何审阅者需要知道的取舍、已知限制或后续工作 -->
