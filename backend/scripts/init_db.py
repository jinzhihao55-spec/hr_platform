"""建表。运行：python -m scripts.init_db"""
from app.core.database import init_db

if __name__ == "__main__":
    init_db()
    print("MySQL 表已创建。")
