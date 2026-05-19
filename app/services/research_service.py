"""
Simplified Deep Research Agent.

Given a research question, this agent:
1. Decomposes the question into 2-4 sub-queries (fast LLM call).
2. For each sub-query, searches the RAG corpus + fetches web results.
3. Synthesizes all findings into a structured research report (smart LLM call).

No LangGraph, no complex orchestration — just sequential LLM calls with
the existing RAG pipeline and a simple web search fallback.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.prompts import get_prompt
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)


async def research(
    question: str,
    max_sub_queries: int = 4,
    rag_top_k: int = 5,
) -> dict[str, Any]:
    """
    Run a simplified deep research cycle.

    Returns a dict with:
      - question: original question
      - sub_queries: list of decomposed queries
      - findings: list of {query, sources, summary} per sub-query
      - report: final synthesized report (markdown)
    """
    # Step 1: Decompose the question
    sub_queries = await _decompose(question, max_sub_queries)
    if not sub_queries:
        sub_queries = [question]

    # Step 2: Gather evidence for each sub-query
    findings = []
    for sq in sub_queries:
        evidence = await _gather_evidence(sq, top_k=rag_top_k)
        findings.append(evidence)

    # Step 3: Synthesize into a report
    report = await _synthesize(question, sub_queries, findings)

    return {
        "question": question,
        "sub_queries": sub_queries,
        "findings": findings,
        "report": report,
    }


async def _decompose(question: str, max_sub_queries: int) -> list[str]:
    """Use the fast LLM to decompose a research question into sub-queries."""
    prompt = get_prompt("research_decompose", question=question, max_sub_queries=max_sub_queries)
    try:
        response = await llm_service.llm.chat(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": question},
            ],
            tier="fast",
            label="research:decompose",
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=500,
        )
        data = json.loads(response.choices[0].message.content)
        queries = data.get("sub_queries", [])
        if isinstance(queries, list):
            return [str(q).strip() for q in queries if str(q).strip()][:max_sub_queries]
    except Exception as exc:
        logger.warning("Research decompose failed: %s", exc)
    return []


async def _gather_evidence(query: str, top_k: int = 5) -> dict[str, Any]:
    """Search RAG corpus and optionally web for evidence on a sub-query."""
    sources: list[dict[str, str]] = []

    # RAG search
    try:
        from app.services.rag_service import rag_service
        rag_results = await rag_service.query(query, top_k=top_k)
        for doc in rag_results:
            sources.append({
                "type": "rag",
                "title": doc.get("title", ""),
                "content": doc.get("content", "")[:500],
                "url": doc.get("url", ""),
            })
    except Exception as exc:
        logger.warning("RAG search failed for sub-query '%s': %s", query, exc)

    # Web search fallback (if Tavily is configured)
    try:
        from app.core.config import settings
        if settings.TAVILY_API_KEY:
            web_results = await _tavily_search(query, max_results=3)
            sources.extend(web_results)
    except Exception as exc:
        logger.debug("Web search skipped for sub-query '%s': %s", query, exc)

    # Summarize the gathered evidence
    if not sources:
        return {"query": query, "sources": [], "summary": "No evidence found."}

    evidence_text = "\n\n".join(
        f"[{i+1}] ({s['type']}) {s['title']}\n{s['content']}" 
        for i, s in enumerate(sources)
    )

    try:
        response = await llm_service.llm.chat(
            messages=[
                {"role": "system", "content": get_prompt("research_evidence_summary")},
                {"role": "user", "content": f"Query: {query}\n\nEvidence:\n{evidence_text}"},
            ],
            tier="fast",
            label="research:evidence",
            temperature=0.2,
            max_tokens=600,
        )
        summary = response.choices[0].message.content or ""
    except Exception:
        summary = evidence_text[:500]

    return {"query": query, "sources": sources, "summary": summary}


async def _synthesize(
    question: str,
    sub_queries: list[str],
    findings: list[dict[str, Any]],
) -> str:
    """Use the smart LLM to synthesize all findings into a research report."""
    findings_text = ""
    for i, f in enumerate(findings):
        findings_text += f"\n### Sub-query {i+1}: {f['query']}\n{f['summary']}\n"

    prompt = get_prompt("research_synthesize", question=question)

    try:
        response = await llm_service.llm.chat(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"# Research Question\n{question}\n\n# Findings\n{findings_text}"},
            ],
            tier="smart",
            label="research:synthesize",
            temperature=0.4,
            max_tokens=3000,
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        logger.exception("Research synthesis failed: %s", exc)
        return f"Research synthesis failed: {exc}"


async def _tavily_search(query: str, max_results: int = 3) -> list[dict[str, str]]:
    """Search the web using Tavily API."""
    import httpx
    from app.core.config import settings

    if not settings.TAVILY_API_KEY:
        return []

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.TAVILY_API_KEY,
                "query": query,
                "max_results": max_results,
                "include_raw_content": False,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    for r in data.get("results", []):
        results.append({
            "type": "web",
            "title": r.get("title", ""),
            "content": (r.get("content") or "")[:500],
            "url": r.get("url", ""),
        })
    return results
