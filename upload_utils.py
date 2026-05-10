import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class UploadRequest:
    source: Path | str | Callable[[], Path]
    target: str
    text: str
    summary: str = "batch upload file"


def _upload_file(
    text: str,
    target,
    summary: str,
    file: Path | Callable[[], Path] | None = None,
    url: str | None = None,
    force: bool = False,
) -> None:
    from pywikibot.site._upload import Uploader
    from wiki_utils import s

    while True:
        try:
            if url is not None:
                Uploader(s, target, source_url=url, text=text, comment=summary, ignore_warnings=force).upload()
            if file is not None:
                if callable(file):
                    file = file()
                Uploader(s, target, source_filename=str(file), text=text, comment=summary, ignore_warnings=force).upload()
            return
        except Exception as e:
            err = str(e)
            if "already exists" in err or "fileexists-no-change" in err:
                return
            if "http-timed-out" in err:
                continue
            if "was-deleted" in err:
                print(f"INFO: {target.title(with_ns=True)} was deleted, skipping reupload")
                return
            m = re.search(r"duplicate of \['([^']+)'", err)
            if m:
                from pywikibot import FilePage
                FilePage(s, f"File:{m.group(1)}").move(
                    target.title(with_ns=True, underscore=True), reason="rename file"
                )
                return
            raise


def process_uploads(requests: list[UploadRequest], force: bool = False) -> None:
    from pywikibot import FilePage
    from pywikibot.pagegenerators import PreloadingGenerator
    from wiki_utils import s

    seen: set[str] = set()
    tagged: list[tuple[FilePage, UploadRequest]] = []
    for r in requests:
        if r.target in seen:
            continue
        seen.add(r.target)
        title = r.target if r.target.startswith("File:") else f"File:{r.target}"
        tagged.append((FilePage(s, title), r))

    existing = {p.title() for p in PreloadingGenerator(fp for fp, _ in tagged) if p.exists()}

    for fp, r in tagged:
        if fp.title() in existing:
            continue
        url = r.source if isinstance(r.source, str) else None
        file = r.source if not isinstance(r.source, str) else None
        _upload_file(r.text, fp, r.summary, file=file, url=url, force=force)
