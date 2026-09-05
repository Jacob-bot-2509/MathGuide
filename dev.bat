@echo off
rem MathGuide 一键启动:同时拉起后端(8000)与前端(5173),各占一个窗口。
rem 关闭对应窗口即停止对应服务;修改后端代码后需重启后端窗口(前端为热更新)。

start "MG Backend  :8000" cmd /k "cd /d D:\code\backend && D:\code\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000"
start "MG Frontend :5173" cmd /k "cd /d D:\code\frontend && npm run dev"
