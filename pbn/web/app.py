"""HTTP layer: thin JSON routes over Workspace, plus the static single-page app.

Routes are grouped by pipeline step. A later step (segment, vectorize, layout, hpgl) adds its
Workspace methods, a route group here and a module in static/js/steps/.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import unquote

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .workspace import Workspace

STATIC = Path(__file__).parent / "static"


def create_app(ws: Workspace) -> Starlette:
    async def call(fn, *args):
        return JSONResponse(await run_in_threadpool(fn, *args))

    async def body(request: Request) -> dict:
        try:
            data = await request.json()
        except ValueError:
            raise ValueError("request body must be JSON") from None
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    # -- step: source image -------------------------------------------------------------------

    async def upload_image(request: Request):
        name = unquote(request.headers.get("x-filename", ""))  # URI-encoded: headers are latin-1
        return await call(ws.add_image, await request.body(), name)

    async def image_file(request: Request):
        return FileResponse(ws.image_path(request.path_params["id"]), headers={"Cache-Control": "max-age=86400"})

    async def list_projects(request: Request):
        return await call(ws.projects)

    async def project_thumb(request: Request):
        return FileResponse(await run_in_threadpool(ws.project_thumb, request.query_params.get("path", "")))

    async def open_project(request: Request):
        return await call(ws.open_project, (await body(request)).get("path", ""))

    # -- step: inventory ----------------------------------------------------------------------

    async def list_inventories(request: Request):
        return await call(ws.inventories)

    async def get_inventory(request: Request):
        return await call(ws.inventory, request.query_params.get("id", ""))

    async def upload_inventory(request: Request):
        b = await body(request)
        return await call(ws.save_inventory, str(b.get("name", "")), str(b.get("text", "")), str(b.get("filename", "")))

    # -- step: colour mapping -----------------------------------------------------------------

    async def clusters(request: Request):
        try:
            n = int(request.query_params.get("n", "24"))
        except ValueError:
            raise ValueError("n must be a number") from None
        return await call(ws.clusters, request.path_params["id"], n)

    async def pick(request: Request):
        b = await body(request)
        return await call(ws.pick, request.path_params["id"], str(b.get("inventory", "")), int(b.get("k", 0)),
                          list(b.get("fixed", [])), b.get("candidates"))

    async def quantize(request: Request):
        b = await body(request)
        return await call(ws.quantize, request.path_params["id"], b.get("palette", []), dict(b.get("quantize", {})))

    # -- step: result -------------------------------------------------------------------------

    async def create_project(request: Request):
        b = await body(request)
        return await call(ws.create_project, str(b.get("name", "")), str(b.get("image", "")),
                          b.get("palette", []), dict(b.get("quantize", {})))

    async def save_palette(request: Request):
        b = await body(request)
        return await call(ws.save_palette, str(b.get("path", "")), b.get("palette", []))

    def error(status: int):
        async def handler(request: Request, exc: Exception):
            msg = exc.args[0] if exc.args else type(exc).__name__
            return JSONResponse({"error": str(msg)}, status_code=status)
        return handler

    routes = [
        Route("/api/images", upload_image, methods=["POST"]),
        Route("/api/images/{id}/work.png", image_file),
        Route("/api/projects", list_projects),
        Route("/api/projects/thumb", project_thumb),
        Route("/api/projects/open", open_project, methods=["POST"]),
        Route("/api/inventories", list_inventories),
        Route("/api/inventories/get", get_inventory),
        Route("/api/inventories", upload_inventory, methods=["POST"]),
        Route("/api/images/{id}/clusters", clusters),
        Route("/api/images/{id}/pick", pick, methods=["POST"]),
        Route("/api/images/{id}/quantize", quantize, methods=["POST"]),
        Route("/api/projects", create_project, methods=["POST"]),
        Route("/api/projects/palette", save_palette, methods=["PUT"]),
        Mount("/", StaticFiles(directory=STATIC, html=True)),
    ]
    return Starlette(routes=routes, exception_handlers={
        ValueError: error(400), TypeError: error(400), LookupError: error(404), FileExistsError: error(409),
        subprocess.CalledProcessError: error(500)})


def serve(root: str | Path = ".", host: str = "127.0.0.1", port: int = 8000, open_browser: bool = False) -> None:
    import uvicorn

    app = create_app(Workspace(root))
    url = f"http://{host}:{port}/"
    print(f"plot-by-numbers web app: {url}  (root: {Path(root).resolve()})")
    if open_browser:
        import threading
        import webbrowser
        threading.Timer(1.0, webbrowser.open, (url,)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
