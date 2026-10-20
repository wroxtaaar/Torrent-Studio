"""Moved out of main.py (see docs/main-split-plan.md)."""

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from search_providers import _search_1337x_uncached
from seedr_api import (
    get_seedr_metadata_tree,
    seedr_add,
    seedr_file_delete,
    seedr_folder_payload,
    seedr_quota,
)
from seedr_client import arr, normalize_file
from settings import logger
from torrent_metadata import MagnetRequest

router = APIRouter()


@router.get("/api/v2/torrents/files")
async def empty_torrent_files(hash: str):
    return []

@router.post("/api/v2/torrents/pause")
async def noop_pause(body: dict[str, Any]):
    return {}

@router.post("/api/v2/torrents/resume")
async def noop_resume(body: dict[str, Any]):
    return {}

@router.post("/api/v2/torrents/delete")
async def noop_delete(body: dict[str, Any]):
    return {}

@router.post("/api/v2/torrents/filePrio")
async def noop_prio(body: dict[str, Any]):
    return {}

@router.get("/api/files")
async def files_compat(
    folder: str = "/",
    search: str = "",
    type: str = "all",
    folder_id: str = "",
):
    # Only load files for the folder currently open in the UI. Folder metadata
    # is returned separately by /api/folders.
    target_id = folder_id.strip()
    if not target_id:
        target_id = "0" if folder in {"/", "/Torrent Studio"} else ""

    if not target_id.isdigit():
        metadata = await get_seedr_metadata_tree()
        for item in metadata.get("folders", []) if isinstance(metadata, dict) else []:
            if str(item.get("path") or "") == folder:
                target_id = str(item.get("id") or "")
                break

    if not target_id.isdigit():
        return []

    payload = await seedr_folder_payload(target_id)
    result = []
    for raw in arr(payload, ("files", "items")):
        f = normalize_file(raw, target_id)
        name = f["name"]
        if search and search.lower() not in name.lower():
            continue

        lower = name.lower()
        if type != "all":
            if type == "video" and not re.search(r"\.(mkv|mp4|m4v|webm|avi|mov|m3u8|ts)$", lower):
                continue
            if type == "audio" and not re.search(r"\.(mp3|wav|flac|aac|ogg|m4a)$", lower):
                continue
            if type == "document" and not re.search(r"\.(pdf|txt|doc|docx|xls|xlsx|ppt|pptx|csv)$", lower):
                continue
            if type == "archive" and not re.search(r"\.(zip|rar|7z|tar|gz|bz2)$", lower):
                continue

        folder_path = folder if folder not in {"", "/"} else "/Torrent Studio"
        result.append({
            "id": f["id"],
            "name": name,
            "path": folder_path.rstrip("/") + "/" + name,
            "folder": folder_path,
            "size": f["size"],
            "type": "video" if re.search(r"\.(mp4|mkv|webm|avi|mov|m4v|m3u8|ts)$", lower) else "other",
            "mimeType": "video/mp4" if re.search(r"\.mp4$", lower) else "application/octet-stream",
            "createdAt": 0,
            "isStreamable": bool(re.search(r"\.(mp4|mkv|webm|avi|mov|m3u8|ts|mp3|m4a|flac|aac|ogg)$", lower)),
            "ownerId": "seedr",
            "ownerName": "Seedr",
            "downloadUrl": f"/api/seedr/files/{f['id']}/download",
            "streamUrl": "",
        })
    return result


@router.get("/api/folders")
async def folders_compat():
    metadata = await get_seedr_metadata_tree()
    return [
        {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or "Folder"),
            "path": str(item.get("path") or "/"),
            "ownerId": "seedr",
            "ownerName": "Seedr",
            "isShared": False,
            "permissions": {},
            "createdAt": 0,
            "filesCount": int(item.get("filesCount") or 0),
            "totalSize": int(item.get("totalSize") or 0),
        }
        for item in metadata.get("folders", [])
    ] if isinstance(metadata, dict) else []

@router.get("/api/storage/stats")
async def storage_stats():
    q = await seedr_quota()
    metadata = await get_seedr_metadata_tree()
    root = metadata.get("root") if isinstance(metadata, dict) else {}
    used = int(q.get("usedSpace") or 0)
    total = int(q.get("maxSpace") or 0)
    pct = (used / total * 100) if total else 0
    return {
        "totalBytes": total,
        "usedBytes": used,
        "freeBytes": max(0, total-used),
        "usedPercentage": pct,
        "filesCount": int((root or {}).get("filesCount") or 0),
        "torrentsCount": 0,
        "isUnlimited": False,
        "serverCapacityLabel": "Seedr cloud storage",
        "alertLevel": "critical" if pct > 90 else "warning" if pct > 80 else "normal",
    }

@router.get("/api/users")
async def users():
    user = {"id": "seedr-user", "name": "Seedr User", "email": "", "role": "admin", "avatar": ""}
    return {"users": [user], "activeUserId": user["id"], "activeUser": user}

@router.get("/api/logs")
async def logs():
    return []

@router.post("/api/logs/clear")
async def clear_logs():
    return {}

@router.get("/api/notifications")
async def notifications():
    return []

@router.post("/api/notifications/read")
async def notifications_read():
    return {}

@router.post("/api/notifications/test")
async def notifications_test():
    return {}

@router.get("/api/cleanup/settings")
async def cleanup_settings():
    return {"autoCleanCompletedDays": 7, "autoPurgeOrphans": False, "autoCleanTempFiles": False, "storageThresholdPercent": 80}

@router.post("/api/cleanup/settings")
async def update_cleanup_settings(body: dict[str, Any]):
    return body

@router.post("/api/cleanup/run")
async def run_cleanup():
    return {"bytesFreed": 0, "filesRemoved": 0, "tempRemoved": 0, "orphansRemoved": 0}


@router.get("/api/qbt/settings")
async def qbt_settings():
    return {"isExternal": False, "host": "", "username": "", "connected": False, "version": "Seedr backend"}

@router.post("/api/qbt/settings")
async def update_qbt_settings(body: dict[str, Any]):
    return {"isExternal": False, "host": "", "username": "", "connected": False, "version": "Seedr backend"}

@router.post("/api/files/delete")
async def delete_file_compat(body: dict[str, Any]):
    return await seedr_file_delete(str(body.get("id") or ""))

@router.post("/api/files/rename")
async def rename_file_compat(body: dict[str, Any]):
    raise HTTPException(501, "Rename is not exposed by this Seedr API deployment")

@router.post("/api/files/move")
async def move_file_compat(body: dict[str, Any]):
    raise HTTPException(501, "Move is not exposed by this Seedr API deployment")

@router.post("/api/files/folder")
async def create_folder_compat(body: dict[str, Any]):
    raise HTTPException(501, "Folder creation is not exposed by this Seedr API deployment")

@router.post("/api/folders/share")
async def share_folder_compat(body: dict[str, Any]):
    raise HTTPException(501, "Sharing is not provided by Seedr")

@router.post("/api/users/switch")
async def switch_user(body: dict[str, Any]):
    return {"activeUser": {"id": "seedr-user", "name": "Seedr User", "email": "", "role": "admin", "avatar": ""}}

@router.post("/api/users/create")
async def create_user(body: dict[str, Any]):
    raise HTTPException(501, "Multi-user accounts are not provided by this deployment")

@router.get("/api/search/torrents/add")
async def search_add_info():
    return JSONResponse({"added": False, "reason": "Use the Seedr magnet action"}, status_code=405)

@router.post("/api/search/torrents/add")
async def search_torrent_add(body: dict[str, Any]):
    source = str(body.get("source") or "")
    magnet = source if source.lower().startswith("magnet:") else ""
    if not magnet and body.get("infoHash"):
        magnet = "magnet:?xt=urn:btih:" + str(body["infoHash"])
    if not magnet:
        return {"added": False, "reason": "no_magnet_or_info_hash"}
    result = await seedr_add(
        MagnetRequest(
            magnet=magnet,
            torrent_name=str(body.get("torrent_name") or "").strip() or None,
        )
    )
    return {"added": True, **result}

# Dedicated episode lookup for the standalone Marvel scanner. Reuse Home's
# existing multi-provider search pipeline rather than scraping 1337x directly.
@router.get("/api/search/episode")
async def search_episode_release(
    title: str = Query(..., min_length=1, max_length=180),
    season: int = Query(..., ge=1, le=99),
    episode: int = Query(..., ge=1, le=999),
):
    query = f"{title.strip()} S{season:02d}E{episode:02d}"
    try:
        candidates = await _search_1337x_uncached(query, allow_series_fallback=False)
    except Exception as exc:
        logger.warning("Episode release search failed for %r: %s", query, exc)
        raise HTTPException(status_code=502, detail="Episode release search temporarily failed")

    token = re.compile(rf"(?i)(?<![A-Z0-9])S{season:02d}E{episode:02d}(?![0-9])")
    rejected_pack = re.compile(r"(?i)\b(complete series|season pack|all seasons|complete season)\b")
    results = []
    seen = set()
    for item in candidates if isinstance(candidates, list) else []:
        name = str(item.get("title") or "").strip()
        if not name or not token.search(name) or rejected_pack.search(name):
            continue
        link = str(item.get("url") or item.get("detailUrl") or item.get("magnet") or "").strip()
        identity = link or name.casefold()
        if identity in seen:
            continue
        seen.add(identity)
        results.append({
            "title": name,
            "url": link,
            "episode": f"S{season:02d}E{episode:02d}",
            "provider": str(item.get("indexer") or item.get("provider") or ""),
            "seeders": item.get("seeders"),
            "size": item.get("size"),
            "infoHash": item.get("infoHash") or item.get("info_hash"),
            "magnet": item.get("magnet") or item.get("magnetUrl"),
        })
        if len(results) >= 8:
            break
    return {
        "status": "found" if results else "not_found",
        "query": query,
        "results": results,
        "providers": sorted({item["provider"] for item in results if item["provider"]}),
    }
