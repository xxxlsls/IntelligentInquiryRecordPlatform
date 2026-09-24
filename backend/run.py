"""
开发/演示环境启动脚本。

使用 uvicorn 以本地单进程方式启动服务（生产环境建议使用 gunicorn + uvicorn worker，
并置于 Nginx 反向代理之后，配合 HTTPS 与进程守护）。

用法：
    python run.py
默认监听 0.0.0.0:8000，可通过环境变量 HOST/PORT 覆盖。
"""

import os

import uvicorn

from app.core.config import settings


def main() -> None:
    """启动 uvicorn 服务。"""
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    # 调试模式开启热重载（DEBUG=True 时）
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=settings.DEBUG,
    )


if __name__ == "__main__":
    main()
