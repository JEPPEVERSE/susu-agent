# susuAgent v0.3 本地测试页面

该页面直接使用 v0.3 `V03Orchestrator`。首次提交一道题时依次执行题目结构化、记忆检索、求解、验证、教学规划和教学执行；后续回答由 Teaching Executor 执行，并可检索 Misconception Card。完成节点会触发 StudentModel 总结和受审核的记忆更新提案。

## 启动

在项目根目录执行：

```powershell
& .\.venv\Scripts\python.exe .\local_web\server.py
```

浏览器会自动打开 `http://127.0.0.1:8765`。如不希望自动打开：

```powershell
& .\.venv\Scripts\python.exe .\local_web\server.py --no-browser
```

侧栏会展示 Solution、VerificationReport、TeachingStrategy、TeachingState 和长期 StudentModel，便于检查 artifact 是否只在首轮生成并被后续轮次复用。

页面内置轻量、安全的 Markdown 渲染。数学公式使用 MathJax；MathJax 通过 CDN 按需加载，无法联网时会保留可读的 LaTeX 原文。
