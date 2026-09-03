from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Annotated

import typer

from .apple_music import export_apple_music
from .config import Settings
from .exporters import parse_markdown_text, write_bundle
from .models import KnowledgeDocument, TranscriptSegment, VideoItem
from .naming import library_filename_stem, library_relative_directory
from .qr_login import bili_dl_login_and_save, login_and_save
from .repository import LibraryRepository
from .services import build_services
from .urls import extract_bilibili_bvid

app = typer.Typer(
    no_args_is_help=True,
    help="Turn Bilibili videos and Markdown into a local, searchable knowledge library.",
)


@app.command()
def init(data_dir: Annotated[Path | None, typer.Option(help="Data directory")] = None):
    """Create the local configuration and knowledge library directories."""
    settings = Settings.load(data_dir)
    settings.save()
    LibraryRepository(settings.database_path)
    typer.echo(f"Initialized: {settings.data_dir}")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8765, reload: bool = False):
    """Start the local GUI."""
    import uvicorn

    uvicorn.run("video2knowledge.web:create_app", host=host, port=port, reload=reload, factory=True)


@app.command("search")
def search_command(query: str, page: int = 1):
    """Search for Bilibili videos."""
    services = build_services(Settings.load())
    for item in asyncio.run(services.provider.search(query, page)):
        charging = " [charging]" if item.is_charging else ""
        typer.echo(f"{item.source_id}\t{item.author}\t{item.title}{charging}")


@app.command()
def login():
    """Log in through bili-dl's built-in QR code flow."""
    settings = Settings.load()
    bundled = Path.cwd() / "vendor" / "bili-dl"
    bili_dl_dir = settings.bili_dl_dir or bundled
    cookie_path = settings.data_dir / "bilibili-cookies.txt"
    native_config = bili_dl_login_and_save(bili_dl_dir, cookie_path, settings.media_dir)
    settings.bili_dl_dir = bili_dl_dir
    settings.cookie_file = cookie_path
    settings.save()
    typer.echo(f"bili-dl login succeeded: {native_config}")


@app.command("qr-login")
def qr_login(timeout: int = 180):
    """Log in with the Bilibili app without reading browser cookies."""
    settings = Settings.load()
    settings.ensure_dirs()
    cookie_path = settings.data_dir / "bilibili-cookies.txt"
    qr_path = settings.data_dir / "bilibili-login-qr.png"
    asyncio.run(login_and_save(cookie_path, qr_path, timeout))
    settings.cookie_file = cookie_path
    settings.save()
    typer.echo("Login succeeded; a dedicated cookie file has been configured.")


@app.command()
def process(
    url: str,
    title: str = "",
    author: str = "",
    language: str = "zh-CN",
    synthesize: bool = False,
    force_refresh: bool = False,
):
    """Download and process one video without starting another concurrent job."""
    settings = Settings.load()
    services = build_services(settings)
    source_id = extract_bilibili_bvid(url)
    item = asyncio.run(services.provider.resolve(source_id))
    if title:
        item.title = title
    if author:
        item.author = author
    job_id = services.repository.create_job(item, language, synthesize, force_refresh)
    outputs = asyncio.run(services.pipeline.run(job_id, item, language, synthesize, force_refresh))
    for kind, path in outputs.items():
        typer.echo(f"{kind}: {path}")


@app.command()
def speak(
    markdown_file: Path,
    title: str = "Knowledge Audio",
    author: str = "video2knowledge",
    language: str = "zh-CN",
    apple_music: bool = True,
):
    """Convert Markdown into speech with LRC timing and an optional Apple Music M4A."""
    settings = Settings.load()
    services = build_services(settings)
    paragraphs = parse_markdown_text(markdown_file.read_text(encoding="utf-8"))
    segments = [TranscriptSegment(0, 0, paragraph) for paragraph in paragraphs]
    source_id = re.sub(r"\W+", "-", markdown_file.stem).strip("-") or "knowledge-audio"
    item = VideoItem("markdown", source_id, title, markdown_file.resolve().as_uri(), author)
    stem = library_filename_stem(item)
    output_dir = settings.library_dir / library_relative_directory(item)
    wav = services.audio.synthesize(segments, output_dir / f"{stem}.wav", language)
    document = KnowledgeDocument(item, segments, language=language, audio_path=wav)
    outputs = write_bundle(document, output_dir)
    outputs["audio"] = wav
    if apple_music:
        outputs.update(export_apple_music(document, wav, output_dir))
    for kind, path in outputs.items():
        typer.echo(f"{kind}: {path}")


if __name__ == "__main__":
    app()
