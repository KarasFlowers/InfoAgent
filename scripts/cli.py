import asyncio
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.services.rss_service import fetch_all_feeds
from app.services.llm_service import llm_service
from app.services.db_service import db_service
from app.core.db import engine, init_db
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession

async def run_cli():
    print("🚀 正在初始化数据库并请求今日简报，这可能需要几十秒的时间，请稍候...")
    
    # Ensure tables exist
    await init_db()
    
    # Create a local DB session
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        # 1. Look in DB first
        data = await db_service.get_summary_by_date(session, today_str)
        
        # 2. If not found, fetch and generate
        if not data:
            print("⏳ 数据库中无今日缓存，正在向各种资讯源拉取最新文章并提交给 DeepSeek (AI 主编) 分析...")
            
            # Fetch RSS
            results = await fetch_all_feeds(settings.RSS_FEEDS)
            
            # Use LLM
            data = await llm_service.generate_daily_summary(results)
            
            if not data:
                print("❌ 获取简报失败。可能是网络问题或 API Key 报错。")
                return
                
            # Save to DB for next time
            await db_service.save_summary(session, data)
            print("✅ 简报已成功获取并自动保存在本地 SQLite 数据库中！")
        else:
            print("⚡ 触发秒回！直接从本地数据库读取今日历史简报。")

        # 3. Print the result beautifully
        print(f"\n========== 📅 {data.date} 科技简报 ==========\n")
        print(f"📖【今日主线】\n{data.overview}\n")
        
        print("📰【核心资讯】")
        for idx, item in enumerate(data.top_news, 1):
            print(f"{idx}. {item.headline}")
            for point in item.key_points:
                print(f"   - {point}")
            print(f"   🔗 来源: {item.original_link}")
            print()
            
        print("====================================================\n")

if __name__ == "__main__":
    asyncio.run(run_cli())
