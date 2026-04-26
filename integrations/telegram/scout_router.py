"""FastAPI router for TG Scout API endpoints."""

from __future__ import annotations

import logging
from typing import Annotated

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from telegram import Bot

from app.config import Settings
from integrations.telegram.outreach import OutreachManager
from integrations.telegram.pitch import PitchDraft, PitchGenerator
from integrations.telegram.scorer import RelevanceScore, RelevanceScorer
from integrations.telegram.scout import ChannelInfo, TelegramScout
from integrations.telegram.tgstat_client import TGStatClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/scout", tags=["tg-scout"])

_settings = Settings()
_engine = create_async_engine(_settings.database_url, echo=False, pool_pre_ping=True)
_anthropic_client = anthropic.AsyncAnthropic(api_key=_settings.anthropic_api_key)


async def get_db():
    async with AsyncSession(_engine) as session:
        yield session


DbDep = Annotated[AsyncSession, Depends(get_db)]


# ── Request / Response models ─────────────────────────────────────────────────


class SearchRequest(BaseModel):
    keywords: list[str]
    min_subscribers: int = 1000
    min_er: float = 0.01


class SearchResponse(BaseModel):
    channels: list[ChannelInfo]
    count: int


class EnrichRequest(BaseModel):
    channels: list[ChannelInfo]


class EnrichResponse(BaseModel):
    channels: list[ChannelInfo]
    count: int


class ScoreRequest(BaseModel):
    channels: list[ChannelInfo]
    product: str


class ScoreResponse(BaseModel):
    scores: list[RelevanceScore]
    count: int


class GenerateRequest(BaseModel):
    channels: list[ChannelInfo]
    scores: list[RelevanceScore]
    product: str


class GenerateResponse(BaseModel):
    drafts: list[PitchDraft]
    count: int


class ChannelResponse(BaseModel):
    username: str
    title: str
    subscriber_count: int
    er: float
    score: int | None
    status: str
    topics: list[str]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/search", response_model=SearchResponse)
async def search_channels(
    request: SearchRequest,
    session: DbDep,
) -> SearchResponse:
    scout = TelegramScout(
        api_id=_settings.telethon_api_id,
        api_hash=_settings.telethon_api_hash,
        session_path=_settings.telethon_session_path,
    )
    try:
        channels = await scout.search_channels(
            request.keywords, request.min_subscribers, request.min_er
        )
        await scout.save_channels(session, channels)
        return SearchResponse(channels=channels, count=len(channels))
    except Exception as exc:
        logger.error("search_channels failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/enrich", response_model=EnrichResponse)
async def enrich_channels(request: EnrichRequest) -> EnrichResponse:
    client = TGStatClient(_settings.tgstat_api_key)
    enriched = await client.enrich_channels(request.channels)
    return EnrichResponse(channels=enriched, count=len(enriched))


@router.post("/score", response_model=ScoreResponse)
async def score_channels(
    request: ScoreRequest,
    session: DbDep,
) -> ScoreResponse:
    scorer = RelevanceScorer(_anthropic_client)
    scores = await scorer.batch_score(request.channels, request.product)
    await scorer.save_scores(session, scores)
    return ScoreResponse(scores=scores, count=len(scores))


@router.post("/pitches/generate", response_model=GenerateResponse)
async def generate_pitches(
    request: GenerateRequest,
    session: DbDep,
) -> GenerateResponse:
    if len(request.channels) != len(request.scores):
        raise HTTPException(status_code=400, detail="channels and scores lists must be same length")
    pitcher = PitchGenerator(_anthropic_client)
    pairs = list(zip(request.channels, request.scores, strict=False))
    drafts = await pitcher.batch_generate(pairs, request.product)
    for draft in drafts:
        await pitcher.save_draft(session, draft)
    return GenerateResponse(drafts=drafts, count=len(drafts))


@router.post("/digest/send")
async def send_digest(session: DbDep) -> dict[str, str]:
    bot = Bot(token=_settings.telegram_bot_token)
    outreach = OutreachManager(_settings)
    try:
        await outreach.send_weekly_digest(session, bot)
        return {"status": "ok"}
    except Exception as exc:
        logger.error("send_digest failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/channels", response_model=list[ChannelResponse])
async def list_channels(
    session: DbDep,
) -> list[ChannelResponse]:
    import json

    sql = text("""
        SELECT c.username, c.title, c.subscriber_count, c.er,
               c.status, c.topics,
               MAX(cs.score) AS score
        FROM tg_channels c
        LEFT JOIN tg_channel_scores cs ON cs.channel_id = c.id
        GROUP BY c.id, c.username, c.title, c.subscriber_count, c.er, c.status, c.topics
        ORDER BY score DESC NULLS LAST
        LIMIT 100
        """)
    result = await session.execute(sql)
    rows = result.mappings().all()

    out: list[ChannelResponse] = []
    for row in rows:
        topics = row["topics"]
        if isinstance(topics, str):
            topics = json.loads(topics)
        out.append(
            ChannelResponse(
                username=row["username"],
                title=row["title"],
                subscriber_count=row["subscriber_count"],
                er=float(row["er"]),
                score=row["score"],
                status=row["status"],
                topics=topics or [],
            )
        )
    return out
