import asyncio
import feedparser
import httpx
from pydantic import ValidationError
from app.models.schemas import RSSItem, RSSResponse
from app.services.redis_service import redis_service
import logging

logger = logging.getLogger(__name__)

async def fetch_and_parse_feed(url: str, client: httpx.AsyncClient) -> RSSResponse | None:
    """
    Fetches a single RSS feed, checks cache first, and parses it into our standard schema.
    """
    try:
        # Cache Key logic
        cache_key = f"rss_feed_{url}"
        
        # 1. Check Redis Cache
        cached_data = await redis_service.get_cache(cache_key)
        if cached_data:
            logger.info(f"Cache hit for {url}")
            return RSSResponse(**cached_data)

        # 2. Cache Miss - Fetch the RSS XML
        logger.info(f"Fetching from web: {url}")
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()
        
        # Parse the XML using feedparser
        feed = feedparser.parse(response.text)
        
        if not feed.entries:
            logger.warning(f"No entries found for {url}")
            return RSSResponse(source_url=url, items=[])
            
        source_title = feed.feed.get('title', url)
        
        items = []
        for entry in feed.entries[:10]:  # Limit to 10 most recent per feed
            try:
                # Extract basic fields safely with defaults
                published = entry.get('published', '') or entry.get('updated', '') 
                summary = entry.get('summary', '') or entry.get('description', '')
                
                # Strip HTML from summary (basic cleaning)
                # In production, might want a more robust HTML parser like BeautifulSoup here
                
                item = RSSItem(
                    title=entry.get('title', 'Unknown Title'),
                    link=entry.get('link', ''),
                    published=published,
                    summary=summary[:500],  # preview
                    source=source_title
                )
                items.append(item)
            except ValidationError as e:
                logger.error(f"Validation error for entry in {url}: {e}")
                continue
                
        # 3. Cache the successful result
        response_obj = RSSResponse(source_url=url, items=items)
        try:
            # Pydantic model dump (json-compatible dict)
            # Depending on pydantic version, it could be .model_dump() or .dict()
            # We'll use model_dump() which is the v2 standard
            await redis_service.set_cache(cache_key, response_obj.model_dump(), expire_seconds=900)
            logger.info(f"Saved to cache: {url}")
        except Exception as e:
            logger.error(f"Failed to save to cache {url}: {e}")
            
        return response_obj
        
    except httpx.HTTPError as e:
        logger.error(f"HTTP error fetching feed {url}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error parsing feed {url}: {e}")
        
    return None

async def fetch_all_feeds(urls: list[str]) -> list[RSSResponse]:
    """
    Concurrently fetches multiple RSS feeds.
    """
    # Use a custom user agent as some RSS endpoints block default Python ones
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    }
    
    async with httpx.AsyncClient(headers=headers) as client:
        # Create a list of async tasks
        tasks = [fetch_and_parse_feed(url, client) for url in urls]
        # Execute them concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
    # Filter out None values or exceptions
    valid_results = []
    for result in results:
        if isinstance(result, RSSResponse):
            valid_results.append(result)
        elif isinstance(result, Exception):
            logger.error(f"Fetch task failed with exception: {result}")
            
    return valid_results
