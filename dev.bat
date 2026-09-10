@echo off
rem MathGuide 一键启动:同时拉起后端(8000)与前端(5173),各占一个窗口。
rem 关闭对应窗口即停止对应服务。
rem 前后端都是热更新:后端 dev_reload.py 监听 backend\*.py,前端 vite 监听 src。
rem 不用 uvicorn 自带的 --reload —— 它的重启协议(CTRL_C_EVENT 控制台广播)
rem 在 Windows Terminal(ConPTY)下失效会卡死,详见 backend/dev_reload.py 头注。
rem 热重载会掐断正在生成的那条回答,界面上标为「回答已中断」
rem (前端靠 SSE 的 [DONE] 收尾标记识别,见 backend/README.md)。
rem 停后端请在后端窗口按 Ctrl+C;直接点 X 会留下孤儿进程(下次启动会自动清)。

start "MG Backend  :8000" cmd /k "cd /d D:\code\backend && title MG Backend :8000 && D:\code\.venv\Scripts\python.exe dev_reload.py"
start "MG Frontend :5173" cmd /k "cd /d D:\code\frontend && npm run dev"
