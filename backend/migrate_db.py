"""一次性数据库迁移脚本：为旧版 template 表补齐 LLM 语义向量相关列。

背景：接入大模型后 Template 模型新增了 embedding / embedding_model /
embedding_updated_at 三列，但历史 SQLite 库由 create_all() 建立，不会为
已存在的表补列，导致启动种子数据初始化报错 no such column: template.embedding。

本脚本幂等：仅添加实际缺失的列，可安全多次执行。执行后即可正常启动服务。
"""

import sqlite3

DB_PATH = "inquiry_platform.db"

# 需要确保存在的列：列名 -> SQLite 列定义
REQUIRED_COLUMNS = {
    "embedding": "TEXT",
    "embedding_model": "VARCHAR(64)",
    "embedding_updated_at": "DATETIME",
}


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        # 读取 template 表现有列名
        cursor.execute("PRAGMA table_info(template)")
        existing = {row[1] for row in cursor.fetchall()}

        added = []
        for col, ddl in REQUIRED_COLUMNS.items():
            if col not in existing:
                cursor.execute(f"ALTER TABLE template ADD COLUMN {col} {ddl}")
                added.append(col)

        conn.commit()
        if added:
            print(f"已补齐缺失列：{added}")
        else:
            print("无需迁移，所有列均已存在。")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
