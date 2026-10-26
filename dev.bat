@echo off
rem MathGuide one-click start: backend (8000) + frontend (5173), one window each.
rem Closing a window stops that service; reopen with this file.
rem Both ends hot-reload: backend dev_reload.py watches backend\*.py, frontend vite watches src.
rem NOTE: backend uses dev_reload.py instead of uvicorn --reload because the latter's
rem restart protocol (CTRL_C_EVENT console broadcast) hangs under Windows Terminal (ConPTY),
rem see backend/dev_reload.py header. Hot reload kills in-flight replies; the UI marks
rem them "answer interrupted" (SSE [DONE] contract, see backend/README.md).
rem To stop the backend cleanly press Ctrl+C in its window; closing with X may leave
rem an orphan uvicorn (cleaned up automatically on next start).

rem %~sdp0 = 本脚本所在目录的 8.3 短路径(无空格),避免在 cmd /k 的引号里再套引号;
rem 这样仓库放在含空格的路径下也能一键启动。
start "MG Backend  :8000" cmd /k "cd /d %~sdp0backend && title MG Backend :8000 && %~sdp0.venv\Scripts\python.exe dev_reload.py"
start "MG Frontend :5173" cmd /k "cd /d %~sdp0frontend && npm run dev"
