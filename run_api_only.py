"""
僅啟動儀表板 API（不啟動交易主程式）

用於前端開發：先執行 python run_api_only.py，再在 frontend 目錄執行 npm run dev。
預設 http://127.0.0.1:8888，前端 proxy 會轉發 /api 到此。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn
from config.settings import API_HOST, API_PORT

if __name__ == "__main__":
    uvicorn.run(
        "api.app:app",
        host=API_HOST,
        port=API_PORT,
        reload=True,
    )
