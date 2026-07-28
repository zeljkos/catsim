"""FastAPI backend: static frontend, WebSocket event relay, command endpoint.

Exists to render bus events and issue commands back onto the bus — zero
physics; layout and DEM knowledge is fetched from the block's query address
and passed through untouched.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from catsim.bus import Command, ZmqPublisher, ZmqSubscriber, decode_event, query
from catsim.dashboard.config import DashboardConfig
from catsim.dashboard.hub import EventHub
from catsim.scenario import ScenarioRunner, list_scenarios, load_scenario

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    config: DashboardConfig,
    *,
    frontend_address: str,
    backend_address: str,
) -> FastAPI:
    """Build the dashboard app against a running bus.

    Args:
        config: Frozen dashboard configuration (from YAML).
        frontend_address: Bus address commands are published to.
        backend_address: Bus address events are subscribed from.

    Returns:
        The FastAPI application.
    """
    hub = EventHub()

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        subscriber = ZmqSubscriber(backend_address)
        publisher = ZmqPublisher(frontend_address)
        app.state.publisher = publisher
        hub.start(subscriber, asyncio.get_running_loop())
        try:
            yield
        finally:
            hub.stop()
            subscriber.close()
            publisher.close()

    app = FastAPI(title=config.title, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        """Serve the single-page frontend."""
        return FileResponse(_STATIC_DIR / "index.html")

    @app.get("/api/config")
    async def api_config() -> dict[str, Any]:
        """The YAML-driven knobs the frontend renders itself from."""
        return dict(json.loads(config.model_dump_json()))

    @app.get("/api/layout")
    async def api_layout() -> dict[str, Any]:
        """Fetch the announced block's geometry from its query address."""
        configured = hub.latest_configured
        if configured is None:
            raise HTTPException(status_code=503, detail="no block announced yet")
        payload = await asyncio.to_thread(query, configured.query_address, "layout")
        return dict(json.loads(payload))

    @app.get("/api/scenarios")
    async def api_scenarios() -> list[dict[str, str]]:
        """Name and one-line description of every shipped scenario."""
        return [
            {"name": s.name, "description": s.description}
            for s in list_scenarios(config.scenario_dir)
        ]

    @app.post("/api/scenarios/{name}")
    async def api_run_scenario(name: str) -> dict[str, str]:
        """Start a scenario runner in the background; it publishes bus commands."""
        try:
            scenario = load_scenario(name, config.scenario_dir)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"unknown scenario {name!r}") from exc
        threading.Thread(
            target=_run_scenario_thread,
            args=(scenario, frontend_address, backend_address),
            daemon=True,
        ).start()
        return {"status": "started", "name": scenario.name}

    @app.post("/api/command")
    async def api_command(request: Request) -> dict[str, str]:
        """Validate a console command against the bus schema and publish it."""
        body = await request.body()
        try:
            event = decode_event(body)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not isinstance(event, Command):
            raise HTTPException(status_code=422, detail=f"{event.type!r} is not a command")
        app.state.publisher.publish(event)
        return {"status": "published", "type": event.type}

    @app.websocket("/ws")
    async def ws_events(websocket: WebSocket) -> None:
        """Stream every bus event to the client as JSON text frames."""
        await websocket.accept()
        queue = hub.register()
        try:
            while True:
                await websocket.send_text(await queue.get())
        except WebSocketDisconnect:
            pass
        finally:
            hub.unregister(queue)

    return app


def _run_scenario_thread(scenario: Any, frontend_address: str, backend_address: str) -> None:
    """Drive one scenario to completion with its own bus sockets."""
    publisher = ZmqPublisher(frontend_address)
    subscriber = ZmqSubscriber(backend_address)
    try:
        ScenarioRunner(scenario, publisher).run(subscriber)
    finally:
        publisher.close()
        subscriber.close()
