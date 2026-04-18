import asyncio
import httpx

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


async def main():
    print("🚀 正在请求今日简报，这可能需要几十秒的时间，请稍候...")
    
    timeout = httpx.Timeout(120.0) # The LLM call might take a while
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.get("http://127.0.0.1:8000/api/v1/summary")
            response.raise_for_status()
            
            data = response.json()
            
            print(f"\n========== 📅 {data['date']} 科技简报 ==========\n")
            print(f"📖【今日主线】\n{data['overview']}\n")
            
            print("📰【核心资讯】")
            for idx, item in enumerate(data['top_news'], 1):
                print(f"{idx}. {item['headline']}")
                for point in item['key_points']:
                    print(f"   - {point}")
                print(f"   🔗 来源: {item['original_link']}")
                print()
                
            print("====================================================\n")
            print("✅ 简报已成功获取并自动保存在本地数据库中！")
            
        except httpx.ConnectError:
            print("❌ 连接失败！请确保 FastAPI 后端服务已启动 (在另一个终端运行 uvicorn main:app --reload)")
        except Exception as e:
            print(f"❌ 发生错误: {e}")

if __name__ == "__main__":
    asyncio.run(main())
