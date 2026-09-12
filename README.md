# WaterPulse AI Agent V9.1 — DeepSeek UI Runtime Fix

本版修复的是右上角一直停留在“服务检查中”的真正原因。

根因不是 Railway Variable 本身，而是前端在执行到 AI 状态检查之前已经报 JavaScript 错误：
- V8.9 删除了“已加入本次分析”文件横条；
- 但脚本仍然执行 `$('#removeFile').onclick=...`；
- 由于 `removeFile` 已不存在，浏览器脚本提前中断；
- 因此 `init()` 根本没有执行，右上角永远停留在初始文案“服务检查中”。

V9.1 已修复：
- 删除对已不存在 `removeFile` 的直接引用；
- 正确补上 `els.attach = #attachBtn`；
- 状态检查增加超时，不会无限卡住；
- 检测到 Railway Key 后先显示“DeepSeek 已配置”；
- 真正 API 测试成功后显示“DeepSeek 已连接”；
- API 测试失败/超时时显示“DeepSeek 已配置 · 连接待确认”。

部署后检查：
1. `/api/health` → version = 9.1
2. `/api/agent/status` → deepseek_configured=true 说明 Railway 变量已读到
3. `/api/deepseek/test` → ok=true 说明 DeepSeek API 真正连通

DeepSeek Key 仍只应放在 Railway Variables，不写入 GitHub。
